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

class StorageService:
    def __init__(self):
        self.client = None
        self.db = None
        self.collection = None
        self.is_connected = False
        self.active_mode = "Local In-Memory Vector & BM25 Fallback (Zero-Config Active)"
        self._data_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store.json")
        
        # In-memory storage for zero-config fallback & benchmarking
        self._chunks: Dict[str, DocumentChunk] = {}
        self._documents: Dict[str, Dict[str, Any]] = {}
        self._query_history: Dict[str, QueryResponse] = {}
        
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
                    chunks_raw = data.get("chunks", {})
                    for cid, cdata in chunks_raw.items():
                        self._chunks[cid] = DocumentChunk(**cdata)
                print(f"[StorageService] Restored {len(self._documents)} documents and {len(self._chunks)} chunks from disk.")
            except Exception as e:
                print(f"[StorageService] Error loading from disk: {e}")

    def connect_mongodb(self, uri: str, db_name: str, coll_name: str) -> Tuple[bool, str]:
        """Attempts connection to MongoDB Atlas Vector Search."""
        if not uri:
            self.is_connected = False
            self.active_mode = "Local In-Memory Vector & BM25 Fallback (Zero-Config Active)"
            return False, "No MongoDB URI provided. Running on Local Fallback Engine."

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

            # Ensure unique index on chunk id to prevent duplicate inserts
            try:
                self.collection.create_index("id", unique=True, background=True)
            except Exception:
                pass  # Index may already exist

            # Sync local chunks into Atlas collection if collection is empty
            if self.collection.count_documents({}) == 0 and self._chunks:
                docs_to_insert = [c.model_dump() for c in self._chunks.values()]
                self.collection.insert_many(docs_to_insert)

            return True, "Successfully connected to MongoDB Atlas Vector Search!"
        except Exception as e:
            self.is_connected = False
            self.active_mode = "Local In-Memory Vector & BM25 Fallback (Zero-Config Active)"
            return False, f"Could not connect to MongoDB Atlas ({str(e)}). Active in Local In-Memory Fallback Mode."

    def count_chunks(self) -> int:
        """Returns total chunk count across active storage backend."""
        if self.is_connected and self.collection is not None:
            try:
                return self.collection.count_documents({})
            except Exception:
                pass
        return len(self._chunks)

    def count_documents(self) -> int:
        """Returns total document count."""
        return len(self._documents)

    def reset(self):
        """Cleanses knowledge base in both MongoDB Atlas (if connected) and local cache."""
        if self.is_connected and self.collection is not None:
            try:
                self.collection.delete_many({})
            except Exception as e:
                print(f"[StorageService] Failed to clear Atlas collection: {e}")
        self._chunks.clear()
        self._documents.clear()
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
        if not self._chunks:
            return 0
        chunk_list = list(self._chunks.values())
        texts = [c.content for c in chunk_list]
        new_embeddings = embedding_service.get_embeddings_batch(texts)
        active_dim = embedding_service.vector_dim
        active_model = getattr(embedding_service, 'current_model_name', 'dense-embedding')

        for idx, c in enumerate(chunk_list):
            c.embedding = new_embeddings[idx]
            c.embedding_dim = active_dim
            c.embedding_model = active_model
            self._chunks[c.id] = c

        self._save_to_disk()

        # If connected to MongoDB Atlas, update remote documents
        if self.is_connected and self.collection is not None:
            try:
                for c in chunk_list:
                    self.collection.update_one(
                        {"id": c.id},
                        {"$set": {"embedding": c.embedding, "embedding_dim": active_dim, "embedding_model": active_model}},
                        upsert=True
                    )
            except Exception as e:
                print(f"[StorageService] Failed to update Atlas embeddings: {e}")

        return len(chunk_list)

    def add_document(self, doc_id: str, title: str, metadata: Dict[str, Any], raw_text: str = ""):
        doc_record = {
            "id": doc_id,
            "title": title,
            "metadata": metadata,
            "raw_text": raw_text,
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
        # Calculate embeddings for any chunks missing them
        texts_to_embed = [c.content for c in chunks if not c.embedding]
        active_dim = embedding_service.vector_dim
        active_model = getattr(embedding_service, 'current_model_name', 'dense-embedding')

        if texts_to_embed:
            new_embeddings = embedding_service.get_embeddings_batch(texts_to_embed)
            embed_idx = 0
            for c in chunks:
                if not c.embedding:
                    c.embedding = new_embeddings[embed_idx]
                    c.embedding_dim = active_dim
                    c.embedding_model = active_model
                    embed_idx += 1

        for c in chunks:
            c.embedding_dim = active_dim
            c.embedding_model = active_model
            self._chunks[c.id] = c
            if c.doc_id in self._documents:
                self._documents[c.doc_id]["chunk_count"] += 1

        self._save_to_disk()

        # Insert into MongoDB Atlas if live
        if self.is_connected and self.collection is not None:
            try:
                docs = [c.model_dump() for c in chunks]
                self.collection.insert_many(docs)
            except Exception as e:
                print(f"[StorageService] Failed to insert chunks into Atlas: {e}")

    def delete_document(self, doc_id: str) -> bool:
        if doc_id in self._documents:
            del self._documents[doc_id]
            # Delete corresponding chunks
            self._chunks = {cid: c for cid, c in self._chunks.items() if c.doc_id != doc_id}
            self._save_to_disk()
            if self.is_connected and self.collection is not None:
                try:
                    self.collection.delete_many({"doc_id": doc_id})
                except Exception as e:
                    print(f"[StorageService] Failed to delete document from Atlas: {e}")
            return True
        return False

    def list_documents(self) -> List[Dict[str, Any]]:
        return list(self._documents.values())

    def get_chunk(self, chunk_id: str) -> Optional[DocumentChunk]:
        return self._chunks.get(chunk_id)

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
        query_embedding = embedding_service.get_embedding(query)
        embed_time = (time.perf_counter() - start_time) * 1000

        # Build sample / actual MongoDB $vectorSearch aggregation pipeline
        mongo_filter = self._build_mongo_filter(filters)
        atlas_pipeline = [
            {
                "$vectorSearch": {
                    "index": config.vector_index_name,
                    "path": "embedding",
                    "queryVector": "[float_array_dim_" + str(len(query_embedding)) + "]",
                    "numCandidates": top_k * 10,
                    "limit": top_k,
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
            "headline": "MongoDB Atlas Vector Search: connected" if self.is_connected else "Local In-Memory Vector & BM25 Fallback (Zero-Config Active)",
            "mode": self.active_mode,
            "search_mode": search_mode,
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
                explain_plan["latency_breakdown"] = {
                    "embedding_time_ms": round(embed_time, 2),
                    "retrieval_time_ms": round(search_time, 2),
                    "total_search_time_ms": round(total_time, 2)
                }
                return citations, explain_plan
            except Exception as e:
                explain_plan["atlas_error"] = str(e)
                print(f"[StorageService] Atlas search error, using local fallback: {e}")

        # 2. Local In-Memory Hybrid Search
        citations, trace_details = self._search_local_hybrid_traced(
            query, query_embedding, filters, top_k, use_hybrid, search_mode
        )
        search_time = (time.perf_counter() - search_start) * 1000
        total_time = (time.perf_counter() - start_time) * 1000

        explain_plan["candidates_pre_rrf"] = trace_details.get("pre_rrf", [])
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
        results = []
        post_rrf_trace = []

        for rank_idx, c in enumerate(sorted_chunks[:top_k]):
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
                    "limit": top_k,
                    **({"filter": mongo_filter} if mongo_filter else {})
                }},
                {"$project": {
                    "id": 1, "doc_id": 1, "doc_title": 1, "section": 1,
                    "page_number": 1, "content": 1, "metadata": 1,
                    "score": {"$meta": "vectorSearchScore"}
                }}
            ]
            cursor = self.collection.aggregate(pipeline)
            return [self._atlas_citation(doc, doc.get("score", 0.0)) for doc in cursor], pipeline

        if search_mode == "lexical":
            pipeline = [{
                "$search": {
                    "index": "chunk_text",
                    "text": {"query": query, "path": ["content", "doc_title", "section"]}
                }
            }]
            if mongo_filter:
                pipeline.append({"$match": mongo_filter})
            pipeline.extend([
                {"$limit": top_k},
                {"$project": {
                    "id": 1, "doc_id": 1, "doc_title": 1, "section": 1,
                    "page_number": 1, "content": 1, "metadata": 1,
                    "score": {"$meta": "searchScore"}
                }}
            ])
            cursor = self.collection.aggregate(pipeline)
            return [self._atlas_citation(doc, doc.get("score", 0.0)) for doc in cursor], pipeline

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

            keyword_sub = [
                {
                    "$search": {
                        "index": "chunk_text",
                        "text": {
                            "query": query,
                            "path": ["content", "doc_title", "section"]
                        }
                    }
                },
                {"$limit": top_k * 4}
            ]
            if mongo_filter:
                keyword_sub[0]["$search"]["filter"] = mongo_filter  # type: ignore[index]

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
                {"$limit": top_k},
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

            return results, pipeline

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

    def _build_mongo_filter(self, filters: Optional[SearchFilters]) -> Dict[str, Any]:
        if not filters:
            return {}
        f = {}
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
        return f

    def _matches_filter(self, chunk: DocumentChunk, filters: Optional[SearchFilters]) -> bool:
        if not filters:
            return True
        meta = chunk.metadata or {}
        if filters.category and meta.get("category") != filters.category:
            return False
        if filters.min_year and (meta.get("year") or 0) < filters.min_year:
            return False
        if filters.max_year and (meta.get("year") or 9999) > filters.max_year:
            return False
        if filters.doc_ids and chunk.doc_id not in filters.doc_ids:
            return False
        return True

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        return max(0.0, min(1.0, dot))

storage_service = StorageService()
if not storage_service._documents:
    try:
        from veritas_rag.samples import load_sample_datasets
        load_sample_datasets()
    except Exception as e:
        print(f"[StorageService] Auto-init error: {e}")
