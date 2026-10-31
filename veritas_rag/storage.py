import time
import math
import re
import os
import json
import hashlib
from collections import Counter
from typing import List, Dict, Any, Optional, Tuple
from veritas_rag.models import DocumentChunk, SearchFilters, Citation, QueryResponse
from veritas_rag.config import config
from veritas_rag.embeddings import embedding_service
from veritas_rag.field_extractor import extract_labelled_fields
from veritas_rag.chunker import chunker

class StorageService:
    def __init__(self):
        self.client = None
        self.db = None
        self.collection = None
        self.is_connected = False
        self.active_mode = "Local Vector + BM25 (Persistent Local Store)"
        self._data_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store.json")
        
        # In-memory storage for zero-config fallback & benchmarking
        self._chunks: Dict[str, DocumentChunk] = {}
        self._documents: Dict[str, Dict[str, Any]] = {}
        self._query_history: Dict[str, QueryResponse] = {}
        # Ephemeral field-level evidence chunks are addressable from the citation UI
        # but are not inserted into the vector/BM25 corpus.
        self._field_chunks: Dict[str, DocumentChunk] = {}
        
        # Load persisted data from disk if available
        self._load_from_disk()
        
        # Check environment variable for MongoDB Atlas URI
        env_uri = os.getenv("MONGODB_URI", config.mongodb_uri)
        if env_uri:
            self.connect_mongodb(env_uri, config.mongodb_database, config.mongodb_collection)

    def _save_to_disk(self):
        """Atomically writes data_store.json via temp file to prevent corruption."""
        import tempfile
        try:
            data = {
                "documents": self._documents,
                "chunks": {cid: c.model_dump() for cid, c in self._chunks.items()}
            }
            dir_path = os.path.dirname(self._data_file)
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.replace(tmp_path, self._data_file)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as e:
            print(f"[StorageService] Failed to save to disk: {e}")

    def _load_from_disk(self):
        if os.path.exists(self._data_file):
            try:
                with open(self._data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._documents = data.get("documents", {})
                    for record in self._documents.values():
                        record.setdefault("metadata", {}).setdefault("owner_id", config.owner_id)
                    chunks_raw = data.get("chunks", {})
                    for cid, cdata in chunks_raw.items():
                        cdata.setdefault("metadata", {}).setdefault("owner_id", config.owner_id)
                        self._chunks[cid] = DocumentChunk(**cdata)
                print(f"[StorageService] Restored {len(self._documents)} documents and {len(self._chunks)} chunks from disk.")
            except Exception as e:
                print(f"[StorageService] Error loading from disk: {e}")

    def connect_mongodb(self, uri: str, db_name: str, coll_name: str) -> Tuple[bool, str]:
        """Attempts connection to MongoDB Atlas Vector Search."""
        if not uri:
            self.is_connected = False
            self.active_mode = "Local Vector + BM25 (Persistent Local Store)"
            return False, "No MongoDB URI provided. Running on Local Fallback Engine."
        if not config.gemini_api_key:
            self.is_connected = False
            self.active_mode = "Local Vector + BM25 (Persistent Local Store)"
            return False, "Configure GEMINI_API_KEY before connecting Atlas; Atlas retrieval requires the configured Gemini embedding space."

        try:
            from pymongo import MongoClient
            self.client = MongoClient(uri, serverSelectionTimeoutMS=4000)
            # Ping to verify
            self.client.admin.command('ping')
            self.db = self.client[db_name]
            self.collection = self.db[coll_name]
            self.is_connected = True
            self.active_mode = "MongoDB Atlas Vector Search: connected"
            config.mongodb_uri = uri
            config.mongodb_database = db_name
            config.mongodb_collection = coll_name

            # This app's existing collections predate owner metadata and are single-deployment stores.
            # Migrate only unowned legacy records; never rewrite an explicitly assigned owner.
            self.collection.update_many(
                {"metadata.owner_id": {"$exists": False}},
                {"$set": {"metadata.owner_id": config.owner_id}},
            )
            self.db["documents"].update_many(
                {"metadata.owner_id": {"$exists": False}},
                {"$set": {"metadata.owner_id": config.owner_id}},
            )

            # Ensure unique index on chunk id to prevent duplicate inserts
            try:
                self.collection.create_index("id", unique=True, background=True)
            except Exception:
                pass  # Index may already exist

            expected_model = embedding_service.current_model_name
            expected_dim = embedding_service.vector_dim
            local_mismatch = any(
                chunk.embedding_model != expected_model or chunk.embedding_dim != expected_dim
                for chunk in self._chunks.values()
            )
            owner_filter = {"metadata.owner_id": config.owner_id}
            atlas_models = self.collection.distinct("embedding_model", owner_filter)
            atlas_dimensions = self.collection.distinct("embedding_dim", owner_filter)
            atlas_mismatch = bool(self.collection.count_documents(owner_filter)) and (
                atlas_models != [expected_model] or atlas_dimensions != [expected_dim]
            )
            if local_mismatch or atlas_mismatch:
                # Re-embed the full collection before Atlas retrieval; fail closed on provider errors.
                self.re_embed_all_chunks()

            # Idempotently sync local chunks and document records into Atlas.
            from pymongo import UpdateOne
            if self._chunks:
                operations = [
                    UpdateOne({"id": chunk.id}, {"$set": chunk.model_dump()}, upsert=True)
                    for chunk in self._chunks.values() if self._matches_filter(chunk, None)
                ]
                if operations:
                    self.collection.bulk_write(operations, ordered=False)
            if self._documents:
                document_operations = [
                    UpdateOne({"id": doc_id}, {"$set": record}, upsert=True)
                    for doc_id, record in self._documents.items()
                    if (record.get("metadata") or {}).get("owner_id") == config.owner_id
                ]
                if document_operations:
                    self.db["documents"].bulk_write(document_operations, ordered=False)

            self._load_documents_from_atlas()
            readiness = self.atlas_index_readiness()
            return True, "Connected to Atlas. " + ("Both search indexes are ready." if readiness["ready"] else "Search indexes are not ready; retrieval will use the local fallback until vector_index and chunk_text report READY.")
        except Exception as e:
            self.is_connected = False
            self.active_mode = "Local Vector + BM25 (Persistent Local Store)"
            return False, f"Could not connect to MongoDB Atlas ({str(e)}). Active in Local In-Memory Fallback Mode."

    def atlas_index_readiness(self) -> Dict[str, Any]:
        result = {"vector_index": "unavailable", "chunk_text": "unavailable", "ready": False}
        if not (self.is_connected and self.collection is not None):
            return result
        try:
            indexes = list(self.collection.list_search_indexes())
            states = {item.get("name"): item.get("status", "unknown") for item in indexes}
            result["vector_index"] = states.get(config.vector_index_name, "missing")
            result["chunk_text"] = states.get("chunk_text", "missing")
            result["ready"] = result["vector_index"] == "READY" and result["chunk_text"] == "READY"
        except Exception as exc:
            result["error"] = str(exc)
        return result

    def count_chunks(self) -> int:
        """Returns total chunk count across active storage backend."""
        if self.is_connected and self.collection is not None:
            try:
                return self.collection.count_documents({"metadata.owner_id": config.owner_id})
            except Exception:
                pass
        return sum(1 for chunk in self._chunks.values() if self._matches_filter(chunk, None))

    def count_documents(self) -> int:
        """Returns total document count across the active storage backend."""
        if self.is_connected and self.db is not None:
            try:
                return self.db["documents"].count_documents({"metadata.owner_id": config.owner_id})
            except Exception as exc:
                print(f"[StorageService] Atlas document count failed: {exc}")
        return sum(1 for record in self._documents.values() if (record.get("metadata") or {}).get("owner_id") == config.owner_id)

    def reset(self, owner_id: Optional[str] = None):
        """Cleanses knowledge base in both MongoDB Atlas (if connected) and local cache."""
        owner_id = owner_id or config.owner_id
        doc_ids = [doc_id for doc_id, record in self._documents.items() if (record.get("metadata") or {}).get("owner_id") == owner_id]
        if self.is_connected and self.collection is not None:
            try:
                owner_query = {"metadata.owner_id": owner_id}
                self.collection.delete_many(owner_query)
                self.db["documents"].delete_many(owner_query)
                if doc_ids:
                    self.db["field_extractions"].delete_many({"doc_id": {"$in": doc_ids}})
            except Exception as e:
                print(f"[StorageService] Failed to clear Atlas collections: {e}")
        self._chunks = {cid: chunk for cid, chunk in self._chunks.items() if (chunk.metadata or {}).get("owner_id") != owner_id}
        self._documents = {doc_id: record for doc_id, record in self._documents.items() if (record.get("metadata") or {}).get("owner_id") != owner_id}
        self._field_chunks = {cid: chunk for cid, chunk in self._field_chunks.items() if (chunk.metadata or {}).get("owner_id") != owner_id}
        self._query_history.clear()
        self._save_to_disk()

    def store_query_result(self, query_id: str, response: QueryResponse):
        """Caches query results server-side for authentic report generation."""
        self._query_history[query_id] = response
        # Keep cache bounded to last 100 queries
        if len(self._query_history) > 100:
            oldest_key = next(iter(self._query_history))
            del self._query_history[oldest_key]

    def get_query_result(self, query_id: str) -> Optional[QueryResponse]:
        """Retrieves stored server-side query result."""
        return self._query_history.get(query_id)

    def re_embed_all_chunks(self) -> int:
        """Re-embeds all existing chunks when the embedding key or model switches."""
        chunk_map = {chunk.id: chunk for chunk in self._chunks.values() if self._matches_filter(chunk, None)}
        if self.is_connected and self.collection is not None:
            records = self.collection.find({"metadata.owner_id": config.owner_id}, {"_id": 0})
            for record in records:
                chunk = DocumentChunk(**record)
                chunk_map[chunk.id] = chunk
        chunk_list = list(chunk_map.values())
        if not chunk_list:
            return 0

        texts = [chunker.get_embedding_text(c) for c in chunk_list]
        new_embeddings = embedding_service.get_embeddings_batch(texts)
        active_dim = embedding_service.vector_dim
        active_model = embedding_service.current_model_name

        for idx, c in enumerate(chunk_list):
            c.embedding = new_embeddings[idx]
            c.embedding_dim = len(new_embeddings[idx])
            c.embedding_model = active_model
            self._chunks[c.id] = c

        self._save_to_disk()

        if self.is_connected and self.collection is not None:
            try:
                from pymongo import UpdateOne
                operations = [
                    UpdateOne(
                        {"id": c.id},
                        {"$set": {
                            "embedding": c.embedding,
                            "embedding_dim": c.embedding_dim,
                            "embedding_model": c.embedding_model
                        }},
                        upsert=True
                    )
                    for c in chunk_list
                ]
                if operations:
                    self.collection.bulk_write(operations, ordered=False)
            except Exception as exc:
                raise RuntimeError(f"Failed to update Atlas embeddings in batch: {exc}") from exc

        return len(chunk_list)

    def add_document(self, doc_id: str, title: str, metadata: Dict[str, Any], raw_text: str = ""):
        metadata = dict(metadata)
        metadata.setdefault("owner_id", config.owner_id)
        metadata.setdefault("uploaded_at", time.time())
        doc_record = {
            "id": doc_id,
            "title": title,
            "metadata": metadata,
            "raw_text": raw_text,
            "extracted_fields": extract_labelled_fields(raw_text),
            "chunk_count": 0,
            "created_at": time.time()
        }
        self._documents[doc_id] = doc_record
        # Write document record to Atlas if connected
        if self.is_connected and self.db is not None:
            try:
                docs_collection = self.db["documents"]
                docs_collection.update_one(
                    {"id": doc_id},
                    {"$set": doc_record},
                    upsert=True
                )
            except Exception as e:
                print(f"[StorageService] Failed to write document record to Atlas: {e}")

    def add_chunks(self, chunks: List[DocumentChunk]):
        """Saves chunks with embeddings to MongoDB Atlas and local memory."""
        # Embed title + section + content so short passages retain document context.
        missing_chunks = [c for c in chunks if not c.embedding]
        enriched_texts = [
            chunker.get_embedding_text(c)
            for c in missing_chunks
        ]

        if enriched_texts:
            new_embeddings = embedding_service.get_embeddings_batch(enriched_texts)
            active_dim = embedding_service.vector_dim
            active_model = embedding_service.current_model_name
            for chunk, vector in zip(missing_chunks, new_embeddings):
                chunk.embedding = vector
                chunk.embedding_dim = active_dim
                chunk.embedding_model = active_model
        else:
            active_dim = embedding_service.vector_dim
            active_model = embedding_service.current_model_name

        for c in chunks:
            if c.embedding is None:
                raise RuntimeError(f"Chunk {c.id} has no embedding; refusing to index an incomplete vector.")
            c.embedding_dim = len(c.embedding)
            c.embedding_model = c.embedding_model or active_model
            self._chunks[c.id] = c
            if c.doc_id in self._documents:
                self._documents[c.doc_id]["chunk_count"] += 1

        self._save_to_disk()

        # Idempotent Atlas upserts avoid duplicate-key failures on repeated uploads.
        if self.is_connected and self.collection is not None:
            try:
                from pymongo import UpdateOne
                operations = [
                    UpdateOne({"id": c.id}, {"$set": c.model_dump()}, upsert=True)
                    for c in chunks
                ]
                if operations:
                    self.collection.bulk_write(operations, ordered=False)
                for doc_id in {chunk.doc_id for chunk in chunks}:
                    document = self._documents.get(doc_id)
                    if document:
                        self.db["documents"].update_one(
                            {"id": doc_id},
                            {"$set": {"chunk_count": document.get("chunk_count", 0)}},
                            upsert=True
                        )
            except Exception as e:
                raise RuntimeError(f"Failed to upsert chunks into Atlas: {e}") from e

    def delete_document(self, doc_id: str) -> bool:
        if doc_id not in self._documents and self.is_connected and self.db is not None:
            self._load_documents_from_atlas()
        if doc_id not in self._documents:
            return False

        del self._documents[doc_id]
        self._chunks = {cid: c for cid, c in self._chunks.items() if c.doc_id != doc_id}
        self._field_chunks = {cid: c for cid, c in self._field_chunks.items() if c.doc_id != doc_id}
        self._save_to_disk()

        if self.is_connected and self.db is not None:
            try:
                self.collection.delete_many({"doc_id": doc_id, "metadata.owner_id": config.owner_id})
                self.db["documents"].delete_one({"id": doc_id, "metadata.owner_id": config.owner_id})
                self.db["field_extractions"].delete_many({"doc_id": doc_id})
            except Exception as exc:
                print(f"[StorageService] Failed to delete document from Atlas: {exc}")
        return True

    def _load_documents_from_atlas(self) -> None:
        if not (self.is_connected and self.db is not None):
            return
        try:
            docs_collection = self.db["documents"]
            projection = {"_id": 0}
            for record in docs_collection.find({}, projection):
                doc_id = record.get("id")
                if doc_id:
                    self._documents[doc_id] = record
        except Exception as exc:
            print(f"[StorageService] Could not load document records from Atlas: {exc}")

    def list_documents(self) -> List[Dict[str, Any]]:
        if self.is_connected and not self._documents:
            self._load_documents_from_atlas()
        return [record for record in self._documents.values() if (record.get("metadata") or {}).get("owner_id") == config.owner_id]

    def search_labelled_fields(
        self, field_key: str, filters: Optional[SearchFilters] = None
    ) -> List[Dict[str, Any]]:
        """Search extracted form fields directly, without relying on embedding similarity."""
        records = dict(self._documents)
        if self.is_connected and self.db is not None:
            self._load_documents_from_atlas()
            records.update(self._documents)

        matches: List[Dict[str, Any]] = []
        for doc_id, record in records.items():
            if (record.get("metadata") or {}).get("owner_id") != config.owner_id:
                continue
            if filters and filters.doc_ids and doc_id not in filters.doc_ids:
                continue
            metadata = record.get("metadata") or {}
            if filters and filters.category and metadata.get("category") != filters.category:
                continue
            year = metadata.get("year")
            if filters and filters.min_year and (year or 0) < filters.min_year:
                continue
            if filters and filters.max_year and (year or 9999) > filters.max_year:
                continue
            if filters and filters.content_type and metadata.get("content_type") != filters.content_type:
                continue
            uploaded = metadata.get("uploaded_at", 0)
            if filters and filters.upload_after and uploaded < filters.upload_after:
                continue
            if filters and filters.upload_before and uploaded > filters.upload_before:
                continue

            fields = record.get("extracted_fields")
            if not isinstance(fields, list):
                fields = extract_labelled_fields(record.get("raw_text", ""))
                record["extracted_fields"] = fields

            for item in fields:
                if item.get("field_key") != field_key or not str(item.get("value", "")).strip():
                    continue

                source_line = str(item.get("source_line") or f"{item.get('label', field_key)}: {item.get('value')}")
                section = str(item.get("section") or "Form fields")
                page_number = int(item.get("page_number") or 1)
                digest = hashlib.sha1(f"{doc_id}|{field_key}|{page_number}|{source_line}".encode("utf-8")).hexdigest()[:12]
                chunk_id = f"fld_{digest}"

                field_chunk = DocumentChunk(
                    id=chunk_id,
                    doc_id=doc_id,
                    doc_title=record.get("title", "Untitled"),
                    section=section,
                    page_number=page_number,
                    content=source_line,
                    metadata={
                        **metadata,
                        "field_extraction": True,
                        "field_key": field_key,
                        "field_label": item.get("label", field_key),
                    }
                )
                self._field_chunks[chunk_id] = field_chunk
                if self.is_connected and self.db is not None:
                    try:
                        self.db["field_extractions"].update_one(
                            {"id": chunk_id},
                            {"$set": field_chunk.model_dump()},
                            upsert=True
                        )
                    except Exception as exc:
                        raise RuntimeError(f"Could not persist field evidence for {doc_id}: {exc}") from exc
                citation = Citation(
                    id=chunk_id,
                    doc_id=doc_id,
                    doc_title=record.get("title", "Untitled"),
                    section=section,
                    page_number=page_number,
                    snippet=source_line,
                    similarity_score=1.0,
                    keyword_score=1.0,
                    combined_score=1.0,
                    metadata={
                        **metadata,
                        "field_extraction": True,
                        "field_key": field_key,
                        "field_label": item.get("label", field_key),
                    }
                )
                matches.append({
                    "field_key": field_key,
                    "label": item.get("label", field_key),
                    "value": str(item.get("value", "")).strip(),
                    "source_line": source_line,
                    "page_number": page_number,
                    "doc_title": record.get("title", "Untitled"),
                    "citation": citation,
                })
        return matches

    def get_chunk(self, chunk_id: str) -> Optional[DocumentChunk]:
        if chunk_id in self._field_chunks:
            return self._field_chunks[chunk_id]
        if chunk_id.startswith("fld_") and self.is_connected and self.db is not None:
            try:
                record = self.db["field_extractions"].find_one({"id": chunk_id}, {"_id": 0})
                if record:
                    return DocumentChunk(**record)
            except Exception as exc:
                print(f"[StorageService] Atlas field evidence lookup failed: {exc}")
        chunk = self._chunks.get(chunk_id)
        if chunk is not None:
            return chunk
        if self.is_connected and self.collection is not None:
            try:
                record = self.collection.find_one({"id": chunk_id})
                if record:
                    record.pop("_id", None)
                    return DocumentChunk(**record)
            except Exception as exc:
                print(f"[StorageService] Atlas chunk lookup failed: {exc}")
        return None

    def hybrid_search(
        self, 
        query: str, 
        filters: Optional[SearchFilters] = None, 
        top_k: int = 5,
        use_hybrid: bool = True,
        search_mode: str = "hybrid" # "hybrid", "dense", "lexical"
    ) -> Tuple[List[Citation], Dict[str, Any]]:
        """
        Executes hybrid search (Vector Semantic + BM25/Keyword) with Reciprocal Rank Fusion.
        Returns top citations and a complete retrieval trace for 'Explain Vector Search Results'.
        """
        start_time = time.perf_counter()
        if search_mode == "lexical":
            query_embedding = []
            embed_time = 0.0
        else:
            query_embedding = embedding_service.get_embedding(query)
            embed_time = (time.perf_counter() - start_time) * 1000
            self._validate_embedding_space(query_embedding, filters)

        # Build sample / actual MongoDB $vectorSearch aggregation pipeline
        mongo_filter = self._build_mongo_filter(filters)
        atlas_pipeline = [
            {
                "$vectorSearch": {
                    "index": config.vector_index_name,
                    "path": "embedding",
                    "queryVector": "[float_array_dim_" + str(len(query_embedding)) + "]",
                    "numCandidates": top_k * 10,
                    "limit": top_k * 4,
                    "filter": mongo_filter
                }
            },
            {
                "$project": {
                    "id": 1,
                    "doc_id": 1,
                    "doc_title": 1,
                    "section": 1,
                    "page_number": 1,
                    "content": 1,
                    "metadata": 1,
                    "score": {"$meta": "vectorSearchScore"}
                }
            }
        ]

        explain_plan = {
            "headline": "MongoDB Atlas Vector Search: connected" if self.is_connected else "Local Vector + BM25 (Persistent Local Store)",
            "mode": self.active_mode,
            "search_mode": search_mode,
            "retrieval_backend": "atlas_pending" if self.is_connected else "local",
            "query": query,
            "filters_applied": filters.model_dump() if filters else None,
            "num_candidates_scanned": self.count_chunks(),
            "top_k_requested": top_k,
            "hybrid_enabled": use_hybrid,
            "aggregation_pipeline": atlas_pipeline,
            "candidates_pre_rrf": [],
            "candidates_post_rrf": [],
            "latency_breakdown": {}
        }

        search_start = time.perf_counter()

        # 1. MongoDB Atlas Path (if live)
        if self.is_connected and self.collection is not None:
            try:
                citations, mongo_explain = self._search_mongodb_atlas(
                    query, query_embedding, filters, top_k, use_hybrid, search_mode
                )
                search_time = (time.perf_counter() - search_start) * 1000
                total_time = (time.perf_counter() - start_time) * 1000
                explain_plan["aggregation_pipeline"] = mongo_explain
                explain_plan["retrieval_backend"] = "mongodb_atlas"
                explain_plan["latency_breakdown"] = {
                    "embedding_time_ms": round(embed_time, 2),
                    "retrieval_time_ms": round(search_time, 2),
                    "total_search_time_ms": round(total_time, 2)
                }
                return citations, explain_plan
            except Exception as e:
                explain_plan["atlas_error"] = str(e)
                print(f"[StorageService] Atlas search error, using local fallback: {e}")

        # 2. Local Hybrid Search
        citations, trace_details = self._search_local_hybrid_traced(
            query, query_embedding, filters, top_k, use_hybrid, search_mode
        )
        search_time = (time.perf_counter() - search_start) * 1000
        total_time = (time.perf_counter() - start_time) * 1000

        explain_plan["candidates_pre_rrf"] = trace_details.get("pre_rrf", [])
        explain_plan["retrieval_backend"] = "local_fallback" if self.is_connected else "local"
        explain_plan["candidates_post_rrf"] = trace_details.get("post_rrf", [])
        explain_plan["latency_breakdown"] = {
            "embedding_time_ms": round(embed_time, 2),
            "retrieval_time_ms": round(search_time, 2),
            "total_search_time_ms": round(total_time, 2)
        }
        return citations, explain_plan

    def _search_local_hybrid_traced(
        self,
        query: str,
        query_embedding: List[float],
        filters: Optional[SearchFilters],
        top_k: int,
        use_hybrid: bool,
        search_mode: str = "hybrid"
    ) -> Tuple[List[Citation], Dict[str, Any]]:
        stopwords = {
            "what", "is", "the", "a", "an", "and", "or", "of", "in", "for", "to", "with",
            "on", "at", "by", "from", "as", "be", "this", "that", "it", "are", "was",
            "were", "will", "would", "can", "could", "should", "how", "why", "when", "where", "who"
        }
        raw_words = re.findall(r'\b[a-z0-9]+\b', query.lower())
        query_words = set(w for w in raw_words if w not in stopwords)
        if not query_words:
            query_words = set(raw_words)
        
        candidates: List[DocumentChunk] = []
        for chunk in self._chunks.values():
            if not self._matches_filter(chunk, filters):
                continue
            candidates.append(chunk)

        if not candidates:
            return [], {"pre_rrf": [], "post_rrf": []}

        # Vector scores
        vector_ranked = []
        for chunk in candidates:
            sim = self._cosine_similarity(query_embedding, chunk.embedding or [])
            vector_ranked.append((chunk, sim))
        vector_ranked.sort(key=lambda x: x[1], reverse=True)

        # BM25 lexical ranking (k1=1.5, b=0.75), using term and document frequencies.
        query_terms = set(query_words)
        tokenized_docs: Dict[str, List[str]] = {}
        document_frequency = Counter()
        for chunk in candidates:
            searchable_text = f"{chunk.doc_title} {chunk.section or ''} {chunk.content}".lower()
            tokens = [w for w in re.findall(r'\b[a-z0-9]+\b', searchable_text) if w not in stopwords]
            tokenized_docs[chunk.id] = tokens
            for term in query_terms.intersection(set(tokens)):
                document_frequency[term] += 1

        corpus_size = len(candidates)
        average_doc_length = (
            sum(len(tokens) for tokens in tokenized_docs.values()) / corpus_size
            if corpus_size else 0.0
        )
        k1, b = 1.5, 0.75
        keyword_ranked = []
        for chunk in candidates:
            tokens = tokenized_docs[chunk.id]
            frequencies = Counter(tokens)
            doc_length = len(tokens)
            score = 0.0
            for term in query_terms:
                term_frequency = frequencies.get(term, 0)
                if not term_frequency:
                    continue
                doc_freq = document_frequency.get(term, 0)
                idf = math.log(1.0 + (corpus_size - doc_freq + 0.5) / (doc_freq + 0.5))
                length_norm = k1 * (1.0 - b + b * doc_length / average_doc_length) if average_doc_length else k1
                score += idf * (term_frequency * (k1 + 1.0) / (term_frequency + length_norm))
            keyword_ranked.append((chunk, score))
        keyword_ranked.sort(key=lambda x: x[1], reverse=True)

        # Build Pre-RRF candidate trace
        pre_rrf_trace = []
        for i in range(min(5, len(candidates))):
            v_chunk, v_s = vector_ranked[i]
            k_chunk, k_s = keyword_ranked[i]
            pre_rrf_trace.append({
                "rank": i + 1,
                "dense_candidate": {"title": v_chunk.doc_title, "section": v_chunk.section, "score": round(v_s, 4)},
                "lexical_candidate": {"title": k_chunk.doc_title, "section": k_chunk.section, "score": round(k_s, 4)}
            })

        # Reciprocal Rank Fusion (RRF)
        rrf_k = 60
        rrf_scores: Dict[str, float] = {}
        vector_scores: Dict[str, float] = {}
        kw_scores: Dict[str, float] = {}

        if search_mode == "dense" or (not use_hybrid and search_mode != "lexical"):
            # Dense vector only
            for rank, (chunk, v_score) in enumerate(vector_ranked):
                vector_scores[chunk.id] = v_score
                kw_scores[chunk.id] = 0.0
                rrf_scores[chunk.id] = v_score
        elif search_mode == "lexical":
            # Lexical BM25 only
            for rank, (chunk, k_score) in enumerate(keyword_ranked):
                vector_scores[chunk.id] = 0.0
                kw_scores[chunk.id] = k_score
                rrf_scores[chunk.id] = k_score
        else:
            # Full Hybrid RRF
            for rank, (chunk, v_score) in enumerate(vector_ranked):
                vector_scores[chunk.id] = v_score
                rrf_scores[chunk.id] = rrf_scores.get(chunk.id, 0.0) + (1.0 / (rrf_k + rank + 1))

            for rank, (chunk, k_score) in enumerate(keyword_ranked):
                # Only grant RRF rank to chunks with non-zero keyword score
                if k_score > 0:
                    kw_scores[chunk.id] = k_score
                    rrf_scores[chunk.id] = rrf_scores.get(chunk.id, 0.0) + (1.0 / (rrf_k + rank + 1))
                else:
                    kw_scores[chunk.id] = 0.0

        # Sort candidates
        sorted_chunks = sorted(candidates, key=lambda c: rrf_scores.get(c.id, 0.0), reverse=True)
        sorted_chunks = self._diversify_results(sorted_chunks, top_k, query)
        results = []
        post_rrf_trace = []

        for rank_idx, c in enumerate(sorted_chunks):
            v_score = vector_scores.get(c.id, 0.0)
            k_score = kw_scores.get(c.id, 0.0)
            rrf_score = rrf_scores.get(c.id, 0.0)

            # Display the actual RRF score (not a manually weighted blend)
            citation = Citation(
                id=c.id,
                doc_id=c.doc_id,
                doc_title=c.doc_title,
                section=c.section,
                page_number=c.page_number,
                snippet=c.content,
                similarity_score=round(float(v_score), 4),
                keyword_score=round(float(k_score), 4),
                combined_score=round(float(rrf_score), 4),
                metadata=c.metadata
            )
            results.append(citation)

            post_rrf_trace.append({
                "rank": rank_idx + 1,
                "doc_title": c.doc_title,
                "section": c.section,
                "page": c.page_number,
                "vector_sim": round(float(v_score), 4),
                "lexical_score": round(float(k_score), 4),
                "rrf_score": round(float(rrf_score), 4)
            })

        return results, {"pre_rrf": pre_rrf_trace, "post_rrf": post_rrf_trace}

    def _search_mongodb_atlas(
        self,
        query: str,
        query_embedding: List[float],
        filters: Optional[SearchFilters],
        top_k: int,
        use_hybrid: bool,
        search_mode: str = "hybrid"
    ) -> Tuple[List[Citation], List[Dict[str, Any]]]:
        mongo_filter = self._build_mongo_filter(filters)

        if search_mode == "dense":
            pipeline = [
                {"$vectorSearch": {
                    "index": config.vector_index_name,
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": top_k * 10,
                    "limit": top_k * 4,
                    **({"filter": mongo_filter} if mongo_filter else {})
                }},
                {"$project": {
                    "id": 1, "doc_id": 1, "doc_title": 1, "section": 1,
                    "page_number": 1, "content": 1, "metadata": 1,
                    "score": {"$meta": "vectorSearchScore"}
                }}
            ]
            cursor = self.collection.aggregate(pipeline)
            results = [self._atlas_citation(doc, doc.get("score", 0.0)) for doc in cursor]
            return self._diversify_results(results, top_k, query), pipeline

        if search_mode == "lexical":
            search_compound = {
                "must": [{
                    "text": {"query": query, "path": ["content", "doc_title", "section"]}
                }]
            }
            atlas_filters = self._build_atlas_search_filters(filters)
            if atlas_filters:
                search_compound["filter"] = atlas_filters
            pipeline = [
                {"$search": {"index": "chunk_text", "compound": search_compound}},
                {"$limit": top_k * 4},
                {"$project": {
                    "id": 1, "doc_id": 1, "doc_title": 1, "section": 1,
                    "page_number": 1, "content": 1, "metadata": 1,
                    "score": {"$meta": "searchScore"}
                }}
            ]
            cursor = self.collection.aggregate(pipeline)
            results = [self._atlas_citation(doc, doc.get("score", 0.0)) for doc in cursor]
            return self._diversify_results(results, top_k, query), pipeline

        # Use MongoDB $rankFusion for hybrid retrieval.
        try:
            vector_sub = {
                "$vectorSearch": {
                    "index": config.vector_index_name,
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": top_k * 10,
                    "limit": top_k * 4,  # oversample before RRF merge
                }
            }
            if mongo_filter:
                vector_sub["$vectorSearch"]["filter"] = mongo_filter

            search_compound = {
                "must": [{
                    "text": {
                        "query": query,
                        "path": ["content", "doc_title", "section"]
                    }
                }]
            }
            atlas_filters = self._build_atlas_search_filters(filters)
            if atlas_filters:
                search_compound["filter"] = atlas_filters
            keyword_sub = [
                {"$search": {"index": "chunk_text", "compound": search_compound}},
                {"$limit": top_k * 4}
            ]

            pipeline = [
                {
                    "$rankFusion": {
                        "input": {
                            "pipelines": {
                                "vector": [vector_sub],
                                "keyword": keyword_sub
                            }
                        },
                        "combination": {
                            "weights": {
                                "vector": 1,
                                "keyword": 1 if use_hybrid else 0
                            }
                        },
                        "scoreDetails": True
                    }
                },
                {"$limit": top_k * 4},
                {
                    "$project": {
                        "id": 1,
                        "doc_id": 1,
                        "doc_title": 1,
                        "section": 1,
                        "page_number": 1,
                        "content": 1,
                        "metadata": 1,
                        "scoreDetails": {"$meta": "searchScoreDetails"}
                    }
                }
            ]

            cursor = self.collection.aggregate(pipeline)
            results = []
            for doc in cursor:
                score_details = doc.get("scoreDetails", {})
                rrf_score = score_details.get("value", 0.0) if isinstance(score_details, dict) else 0.0
                cit = Citation(
                    id=doc.get("id", str(doc.get("_id"))),
                    doc_id=doc.get("doc_id", "unknown"),
                    doc_title=doc.get("doc_title", "Untitled"),
                    section=doc.get("section", ""),
                    page_number=doc.get("page_number", 1),
                    snippet=doc.get("content", ""),
                    similarity_score=round(rrf_score, 4),
                    combined_score=round(rrf_score, 4),
                    metadata=doc.get("metadata", {})
                )
                results.append(cit)

            if not results:
                print(f"[StorageService] WARNING: Atlas $rankFusion returned 0 results for query: '{query[:80]}' — "
                      "check that the Atlas vector index exists and chunks are inserted.")

            return self._diversify_results(results, top_k, query), pipeline

        except Exception as rank_fusion_err:
            raise RuntimeError(
                f"Atlas hybrid $rankFusion unavailable; using local hybrid fallback: {rank_fusion_err}"
            ) from rank_fusion_err

    def _atlas_citation(self, doc: Dict[str, Any], score: float) -> Citation:
        return Citation(
            id=doc.get("id", str(doc.get("_id"))),
            doc_id=doc.get("doc_id", "unknown"),
            doc_title=doc.get("doc_title", "Untitled"),
            section=doc.get("section", ""),
            page_number=doc.get("page_number", 1),
            snippet=doc.get("content", ""),
            similarity_score=round(float(score), 4),
            combined_score=round(float(score), 4),
            metadata=doc.get("metadata", {})
        )

    def _build_atlas_search_filters(self, filters: Optional[SearchFilters]) -> List[Dict[str, Any]]:
        """Translate document filters to Atlas Search compound.filter clauses."""
        clauses: List[Dict[str, Any]] = []
        if not filters:
            return [{"equals": {"path": "metadata.owner_id", "value": config.owner_id}}]
        if filters.category:
            clauses.append({"equals": {"path": "metadata.category", "value": filters.category}})
        if filters.min_year or filters.max_year:
            year_range: Dict[str, Any] = {"path": "metadata.year"}
            if filters.min_year:
                year_range["gte"] = filters.min_year
            if filters.max_year:
                year_range["lte"] = filters.max_year
            clauses.append({"range": year_range})
        if filters.doc_ids:
            clauses.append({"in": {"path": "doc_id", "value": filters.doc_ids}})
        if filters.content_type:
            clauses.append({"equals": {"path": "metadata.content_type", "value": filters.content_type}})
        if filters.upload_after or filters.upload_before:
            uploaded_range: Dict[str, Any] = {"path": "metadata.uploaded_at"}
            if filters.upload_after:
                uploaded_range["gte"] = filters.upload_after
            if filters.upload_before:
                uploaded_range["lte"] = filters.upload_before
            clauses.append({"range": uploaded_range})
        clauses.append({"equals": {"path": "metadata.owner_id", "value": config.owner_id}})
        return clauses

    def _is_comparative_query(self, query: str) -> bool:
        return bool(re.search(
            r"\b(compare|compared|versus|vs\.?|between|difference|differences|discrepancy|"
            r"contradict|conflict|changed? from|updated from|higher than|lower than)\b",
            query,
            re.IGNORECASE
        ))

    def _diversify_results(self, results: List[Any], top_k: int, query: str) -> List[Any]:
        """Cap early results per document for comparisons, then backfill to top_k."""
        if len(results) <= top_k or not self._is_comparative_query(query):
            return results[:top_k]

        per_document_cap = max(1, math.ceil(top_k / 2))
        selected: List[Any] = []
        selected_ids = set()
        counts: Dict[str, int] = {}

        for item in results:
            doc_id = getattr(item, "doc_id", None)
            if counts.get(doc_id, 0) >= per_document_cap:
                continue
            selected.append(item)
            selected_ids.add(getattr(item, "id", id(item)))
            counts[doc_id] = counts.get(doc_id, 0) + 1
            if len(selected) >= top_k:
                return selected

        for item in results:
            item_id = getattr(item, "id", id(item))
            if item_id in selected_ids:
                continue
            selected.append(item)
            if len(selected) >= top_k:
                break
        return selected

    def _build_mongo_filter(self, filters: Optional[SearchFilters]) -> Dict[str, Any]:
        f = {"metadata.owner_id": config.owner_id}
        if not filters:
            return f
        if filters.category:
            f["metadata.category"] = filters.category
        if filters.min_year or filters.max_year:
            year_query = {}
            if filters.min_year:
                year_query["$gte"] = filters.min_year
            if filters.max_year:
                year_query["$lte"] = filters.max_year
            f["metadata.year"] = year_query
        if filters.doc_ids:
            f["doc_id"] = {"$in": filters.doc_ids}
        if filters.content_type:
            f["metadata.content_type"] = filters.content_type
        if filters.upload_after or filters.upload_before:
            uploaded = {}
            if filters.upload_after:
                uploaded["$gte"] = filters.upload_after
            if filters.upload_before:
                uploaded["$lte"] = filters.upload_before
            f["metadata.uploaded_at"] = uploaded
        return f

    def _matches_filter(self, chunk: DocumentChunk, filters: Optional[SearchFilters]) -> bool:
        meta = chunk.metadata or {}
        if meta.get("owner_id") != config.owner_id:
            return False
        if not filters:
            return True
        if filters.category and meta.get("category") != filters.category:
            return False
        if filters.min_year and (meta.get("year") or 0) < filters.min_year:
            return False
        if filters.max_year and (meta.get("year") or 9999) > filters.max_year:
            return False
        if filters.doc_ids and chunk.doc_id not in filters.doc_ids:
            return False
        if filters.content_type and meta.get("content_type") != filters.content_type:
            return False
        uploaded = meta.get("uploaded_at", 0)
        if filters.upload_after and uploaded < filters.upload_after:
            return False
        if filters.upload_before and uploaded > filters.upload_before:
            return False
        return True

    def _validate_embedding_space(
        self, query_embedding: List[float], filters: Optional[SearchFilters] = None
    ) -> None:
        """Refuse to mix vectors produced by incompatible models or dimensions."""
        expected_dim = len(query_embedding)
        expected_model = embedding_service.current_model_name

        if self.is_connected and self.collection is not None:
            readiness = self.atlas_index_readiness()
            if not readiness["ready"]:
                raise RuntimeError(f"Atlas search indexes are not ready: {readiness}")
            mongo_filter = self._build_mongo_filter(filters)
            models = self.collection.distinct("embedding_model", mongo_filter)
            dimensions = self.collection.distinct("embedding_dim", mongo_filter)
        else:
            candidates = [
                chunk for chunk in self._chunks.values()
                if self._matches_filter(chunk, filters) and chunk.embedding
            ]
            models = list({chunk.embedding_model for chunk in candidates})
            dimensions = list({chunk.embedding_dim or len(chunk.embedding or []) for chunk in candidates})

        if self.is_connected and self.collection is not None:
            indexed_count = self.collection.count_documents(mongo_filter)
            if indexed_count and (not models or not dimensions):
                raise RuntimeError(
                    "Indexed chunks do not record their embedding model/dimension. "
                    "Re-embed the full knowledge base before searching."
                )
        model_mismatch = [model for model in models if model != expected_model]
        dimension_mismatch = [dim for dim in dimensions if dim is None or int(dim) != expected_dim]
        if model_mismatch or dimension_mismatch:
            raise RuntimeError(
                "The indexed documents use a different embedding space from the active query model. "
                f"Active model/dimension: {expected_model}/{expected_dim}; "
                f"indexed models/dimensions: {models}/{dimensions}. "
                "Re-embed the full knowledge base before searching. No cross-model fallback was attempted."
            )

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2:
            return 0.0
        if len(v1) != len(v2):
            raise ValueError(
                f"Embedding dimension mismatch: query={len(v1)}, document={len(v2)}. "
                "Re-embed the knowledge base with one configured embedding model."
            )
        dot = sum(a * b for a, b in zip(v1, v2))
        return max(0.0, min(1.0, dot))

storage_service = StorageService()
if not storage_service._documents:
    try:
        from veritas_rag.samples import load_sample_datasets
        load_sample_datasets()
    except Exception as e:
        print(f"[StorageService] Auto-init error: {e}")
