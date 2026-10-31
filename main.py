import os
import time
import re
import hashlib
import ipaddress
import socket
import io
import html
import copy
from pathlib import Path
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from veritas_rag.config import config
from veritas_rag.models import (
    QueryRequest, QueryResponse, DocumentChunk, 
    SearchFilters, EvalSummary, ReportExportRequest,
    CustomEvalRequest, StudyKitRequest
)
from veritas_rag.storage import storage_service
from veritas_rag.embeddings import embedding_service
from veritas_rag.chunker import chunker
from veritas_rag.conflict_radar import conflict_radar
from veritas_rag.generator import generator
from veritas_rag.evaluator import benchmark_evaluator
from veritas_rag.samples import load_sample_datasets
from veritas_rag.field_extractor import detect_field_intent

# Modern FastAPI Lifespan Handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: remove the old showcase and seed DSA study notes idempotently
    load_sample_datasets()
    yield
    # Shutdown logic if any

app = FastAPI(
    title=config.app_name,
    description=config.tagline,
    version=config.version,
    lifespan=lifespan
)

# Restrict CORS to authorized local development origins
cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000")
allowed_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# 1. System Status & Health
@app.get("/api/status")
def get_status():
    return {
        "app_name": config.app_name,
        "tagline": config.tagline,
        "version": config.version,
        "mongodb_headline": "MongoDB Atlas Vector Search: ready" if storage_service.atlas_index_readiness()["ready"] else ("MongoDB Atlas connected; search indexes not ready" if storage_service.is_connected else "Local Vector + BM25 (Persistent Local Store)"),
        "storage_mode": storage_service.active_mode,
        "mongodb_connected": storage_service.is_connected,
        "atlas_indexes": storage_service.atlas_index_readiness(),
        "mongodb_database": config.mongodb_database,
        "mongodb_collection": config.mongodb_collection,
        "vector_index_name": config.vector_index_name,
        "gemini_configured": bool(config.gemini_api_key),
        "embedding_dim": embedding_service.vector_dim,
        "embedding_model": getattr(embedding_service, 'current_model_name', 'dense-embedding'),
        "total_documents": storage_service.count_documents(),
        "total_chunks": storage_service.count_chunks()
    }

# 2. Configuration Endpoints
@app.post("/api/config/mongodb")
def update_mongodb(data: dict):
    uri = data.get("uri", "").strip()
    db = data.get("database", config.mongodb_database).strip()
    coll = data.get("collection", config.mongodb_collection).strip()
    idx = data.get("index_name", config.vector_index_name).strip()

    if not uri:
        storage_service.is_connected = False
        storage_service.active_mode = "Local Vector + BM25 (Persistent Local Store)"
        return {"success": True, "mode": storage_service.active_mode, "message": "Reverted to Local In-Memory Fallback Mode."}

    config.mongodb_uri = uri
    config.mongodb_database = db
    config.mongodb_collection = coll
    config.vector_index_name = idx

    success, msg = storage_service.connect_mongodb(uri, db, coll)
    return {"success": success, "mode": storage_service.active_mode, "message": msg}

@app.post("/api/config/gemini")
def update_gemini_key(data: dict):
    key = data.get("api_key", "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="A Gemini API key is required for Gemini embeddings.")
    config.gemini_api_key = key
    embedding_service.configure_key(key)
    generator._api_key = key
    try:
        re_embedded = storage_service.re_embed_all_chunks()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini key saved but re-embedding did not complete: {exc}")
    return {
        "success": True, 
        "configured": bool(key), 
        "embedding_dim": embedding_service.vector_dim,
        "re_embedded_chunks": re_embedded
    }

# 3. Document Knowledge Base
@app.get("/api/documents")
def list_documents():
    docs = [copy.deepcopy(d) for d in storage_service.list_documents() if (d.get("metadata") or {}).get("owner_id") == config.owner_id]
    for doc in docs:
        doc.get("metadata", {}).pop("source_file", None)
    return docs

def remove_source_file(record: dict) -> None:
    source = (record.get("metadata") or {}).get("source_file")
    if not source:
        return
    source_root = (Path(__file__).parent / "data" / "sources").resolve()
    source_path = Path(source).resolve()
    if source_path.is_relative_to(source_root) and source_path.is_file():
        source_path.unlink()

@app.post("/api/documents/upload")
def upload_document(
    title: str = Form(""),
    category: str = Form("General"),
    author: str = Form("Unknown"),
    year: Optional[int] = Form(None),
    text_content: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None)
):
    content = ""
    pages_data = None
    file_bytes = b""

    source_path = None
    content_type = "text/plain"
    source_url = None
    if file and file.filename:
        file_bytes = file.file.read()
        if len(file_bytes) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File exceeds maximum allowed upload limit of 25MB.")
        filename_lower = file.filename.lower()
        content_type = "application/pdf" if filename_lower.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if filename_lower.endswith(".docx") else "text/plain"
        if filename_lower.endswith(".pdf"):
            try:
                content, pages_data = chunker.extract_text_from_pdf(file_bytes)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to parse PDF: {str(e)}")
        elif filename_lower.endswith(".docx"):
            try:
                from docx import Document
                document = Document(io.BytesIO(file_bytes))
                content = "\n\n".join(p.text for p in document.paragraphs if p.text.strip())
                content += "\n\n" + "\n".join(" | ".join(cell.text for cell in row.cells) for table in document.tables for row in table.rows)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to parse DOCX: {str(e)}")
        elif filename_lower.endswith((".txt", ".md", ".markdown")):
            try:
                content = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                content = file_bytes.decode("latin-1", errors="ignore")
        else:
            raise HTTPException(status_code=400, detail="Supported file types are PDF, DOCX, TXT, and Markdown.")
    elif url:
        from urllib.parse import urlparse
        import urllib.request
        import html
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise HTTPException(status_code=400, detail="Provide a valid HTTP or HTTPS webpage URL.")
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            if any(ipaddress.ip_address(item[4][0]).is_private or ipaddress.ip_address(item[4][0]).is_loopback or ipaddress.ip_address(item[4][0]).is_link_local for item in addresses):
                raise HTTPException(status_code=400, detail="Private and local webpage addresses are not allowed.")
            class RejectRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            opener = urllib.request.build_opener(RejectRedirect)
            request = urllib.request.Request(url, headers={"User-Agent": "NexoraStudyBuddy/1.0"})
            with opener.open(request, timeout=8) as response:
                body = response.read(5 * 1024 * 1024 + 1)
                if len(body) > 5 * 1024 * 1024:
                    raise HTTPException(status_code=400, detail="Webpage exceeds the 5MB ingestion limit.")
                source_url = response.geturl()
                if urlparse(source_url).hostname != parsed.hostname:
                    raise HTTPException(status_code=400, detail="Cross-host webpage redirects are not allowed.")
                page_html = body.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            from html.parser import HTMLParser
            class TextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__(); self.parts = []; self.hidden = 0
                def handle_starttag(self, tag, attrs):
                    if tag in {"script", "style", "noscript", "svg"}: self.hidden += 1
                    elif tag in {"p", "div", "br", "li", "h1", "h2", "h3", "section"}: self.parts.append("\n")
                def handle_endtag(self, tag):
                    if tag in {"script", "style", "noscript", "svg"}: self.hidden = max(0, self.hidden - 1)
                def handle_data(self, data):
                    if not self.hidden and data.strip(): self.parts.append(data.strip())
            extractor = TextExtractor(); extractor.feed(page_html)
            content = "\n".join(extractor.parts)
            title = title or parsed.hostname
            content_type = "text/html"
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not fetch webpage: {str(e)}")
    elif text_content:
        content = text_content
    else:
        raise HTTPException(status_code=400, detail="Must provide either a file upload or text content.")

    if not content.strip():
        raise HTTPException(status_code=400, detail="Document content cannot be empty.")
    if not title.strip():
        title = Path(file.filename).stem if file and file.filename else "Study notes"

    # Deduplicate ingestion using deterministic content hash
    content_hash = hashlib.sha256((config.owner_id + content).encode("utf-8")).hexdigest()[:12]
    doc_id = f"doc_{content_hash}"

    # Auto-extract year if not explicitly provided
    if year is None:
        year_match = re.search(r'\b(20[12][0-9])\b', content)
        if year_match:
            try:
                year = int(year_match.group(1))
            except ValueError:
                year = None

    metadata = {
        "title": title,
        "author": author,
        "year": year,
        "category": category,
        "source_type": "upload",
        "content_hash": content_hash,
        "file_size_bytes": len(file_bytes) if file_bytes else len(content.encode("utf-8")),
        "owner_id": config.owner_id, "content_type": content_type, "uploaded_at": time.time(), "source_url": source_url
    }

    if file_bytes:
        source_dir = Path(__file__).parent / "data" / "sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        extension = Path(file.filename).suffix.lower()
        source_path = source_dir / f"{doc_id}{extension}"
        source_path.write_bytes(file_bytes)
        metadata["source_file"] = str(source_path)

    storage_service.add_document(doc_id, title, metadata, raw_text=content)
    chunk_metadata = {key: value for key, value in metadata.items() if key != "source_file"}
    chunks = chunker.chunk_document(doc_id, title, content, chunk_metadata, pages=pages_data)
    storage_service.add_chunks(chunks)

    return {
        "success": True,
        "doc_id": doc_id,
        "title": title,
        "chunks_created": len(chunks),
        "total_knowledge_chunks": storage_service.count_chunks()
    }

@app.get("/api/documents/{doc_id}/source")
def open_source(doc_id: str, page: int = Query(1, ge=1)):
    record = next((d for d in storage_service.list_documents() if d.get("id") == doc_id), None)
    if not record or (record.get("metadata") or {}).get("owner_id") != config.owner_id:
        raise HTTPException(status_code=404, detail="Source document not found.")
    source = (record.get("metadata") or {}).get("source_file")
    if source and Path(source).is_file():
        return FileResponse(source, media_type=(record.get("metadata") or {}).get("content_type", "application/octet-stream"), filename=Path(source).name, content_disposition_type="inline")
    text = record.get("raw_text", "")
    page_text = "\n".join(line for line in text.splitlines() if not line.strip().lower().startswith("[page "))
    safe_title = html.escape(str(record.get("title", "Source")))
    return HTMLResponse(f"<meta charset='utf-8'><title>{safe_title}</title><main style='max-width:800px;margin:3rem auto;font:18px/1.7 system-ui'><h1>{safe_title}</h1><p>Page {page}</p><pre style='white-space:pre-wrap'>{html.escape(page_text)}</pre></main>")

@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    record = next((d for d in storage_service.list_documents() if d.get("id") == doc_id), None)
    if not record or (record.get("metadata") or {}).get("owner_id") != config.owner_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    success = storage_service.delete_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found.")
    remove_source_file(record)
    return {
        "success": True, 
        "message": f"Document '{doc_id}' successfully removed.",
        "remaining_documents": storage_service.count_documents(),
        "remaining_chunks": storage_service.count_chunks()
    }

@app.post("/api/documents/reset")
def reset_documents(confirm: bool = Form(False)):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required to reset knowledge base. Pass confirm=true.")
    owned_docs = [d for d in storage_service.list_documents() if (d.get("metadata") or {}).get("owner_id") == config.owner_id]
    storage_service.reset(owner_id=config.owner_id)
    for record in owned_docs:
        remove_source_file(record)
    load_sample_datasets(force_reload=True)
    return {
        "success": True, 
        "message": "Your study library was reset to the DSA practice notes.",
        "total_documents": storage_service.count_documents(),
        "total_chunks": storage_service.count_chunks()
    }

# 4. Report Export Endpoint (Server-Side Verified)
@app.post("/api/export/report")
def export_report(req: ReportExportRequest):
    if req.format.lower() not in {"markdown", "json"}:
        raise HTTPException(status_code=400, detail="Supported report formats are markdown and json.")

    cached = storage_service.get_query_result(req.query_id)
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail="Query result not found or expired. Run the query again before exporting its report."
        )

    # Rebuild report content from server-held query results only.
    # Client-provided answer/citation fields are intentionally ignored.
    query_text = cached.question
    answer_text = cached.answer
    grounded_score = cached.groundedness_score
    abstained = cached.abstained
    conflicts_list = cached.conflicts
    citations_list = cached.citations

    # Conditional honesty grading - strictly no blanket overclaiming
    if abstained:
        grounded_verdict = "Safe Abstention - Insufficient Evidence in Indexed Corpus"
    elif grounded_score >= 80:
        grounded_verdict = f"High Groundedness ({grounded_score}%) - Corroborated by Retrieved Passages"
    elif grounded_score >= 50:
        grounded_verdict = f"Moderate Groundedness ({grounded_score}%) - Partial Source Alignment"
    else:
        grounded_verdict = f"Low Groundedness ({grounded_score}%) - Caution: Unverified Claims"

    if req.format.lower() == "json":
        return JSONResponse(content={
            "platform": "Nexora Intelligence & Verification Platform",
            "query_id": req.query_id,
            "timestamp": time.time(),
            "query": query_text,
            "groundedness_score": grounded_score,
            "grounded_verdict": grounded_verdict,
            "answer": answer_text,
            "conflicts": [c.model_dump() for c in conflicts_list],
            "citations": [cit.model_dump() for cit in citations_list]
        })

    # Markdown format report
    lines = [
        "# Nexora Intelligence & Evidence Verification Report",
        f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"**Verification Status:** {grounded_verdict}",
        f"**Query ID:** `{req.query_id}`",
        "",
        "## Query Investigated",
        f"> {query_text}",
        "",
        "## Synthesized Evidence",
        answer_text,
        ""
    ]

    if conflicts_list:
        lines.append(f"## Cross-Document Conflict Radar ({len(conflicts_list)} Discrepancies Detected)")
        for cf in conflicts_list:
            lines.append(f"### {cf.subject} [{cf.discrepancy_type.upper()}]")
            lines.append(f"- **Source A ({cf.source_a}):** {cf.claim_a} (Value: `{cf.value_a or 'N/A'}`)")
            lines.append(f"- **Source B ({cf.source_b}):** {cf.claim_b} (Value: `{cf.value_b or 'N/A'}`)")
            if cf.delta:
                lines.append(f"- **Calculated Delta:** `{cf.delta}`")
            lines.append(f"- **Reconciliation:** {cf.explanation}")
            lines.append("")

    if citations_list:
        lines.append(f"## Verified Source Citations ({len(citations_list)} Passages)")
        for idx, cit in enumerate(citations_list, 1):
            lines.append(f"**[{idx}] {cit.doc_title}** — § {cit.section or 'General'} (p.{cit.page_number})")
            lines.append(f"- *Similarity Score:* `{int(cit.similarity_score * 100)}%` | *Chunk ID:* `{cit.id}`")
            lines.append(f"- *Verified Excerpt:* \"{cit.snippet}\"")
            lines.append("")

    return {"success": True, "format": "markdown", "report": "\n".join(lines)}

# 5. Chunk Inspector
@app.get("/api/chunks/{chunk_id}")
def get_chunk_details(chunk_id: str):
    chunk = storage_service.get_chunk(chunk_id)
    if not chunk or (chunk.metadata or {}).get("owner_id") != config.owner_id:
        raise HTTPException(status_code=404, detail="Chunk not found.")
    return chunk.model_dump()

# 6. Core RAG Query Endpoint
@app.post("/api/query", response_model=QueryResponse)
def query_rag(req: QueryRequest):
    if req.filters is not None:
        # Owner identity comes from server deployment configuration, never request JSON.
        req.filters.owner_id = config.owner_id
    # Direct field lookup is more reliable than semantic retrieval for form questions
    # such as "What is the name of the person in this document?".
    field_intent = detect_field_intent(req.question)
    if field_intent:
        field_matches = storage_service.search_labelled_fields(field_intent, req.filters)
        if field_matches:
            response = generator.generate_field_response(
                question=req.question,
                field_matches=field_matches,
                explain_search={
                    "retrieval_mode": "structured_field_lookup",
                    "field_key": field_intent,
                    "field_matches": len(field_matches),
                    "filters_applied": req.filters.model_dump() if req.filters else None,
                },
                answer_mode=req.answer_mode,
            )
            storage_service.store_query_result(response.query_id, response)
            return response

    citations, explain_search = storage_service.hybrid_search(
        query=req.question,
        filters=req.filters,
        top_k=req.top_k,
        use_hybrid=req.use_hybrid
    )

    response = generator.generate_response(
        question=req.question,
        citations=citations,
        explain_search=explain_search,
        answer_mode=req.answer_mode,
        temperature=req.temperature
    )
    # Store in server-side query history for authentic report generation
    storage_service.store_query_result(response.query_id, response)
    return response

@app.post("/api/study/kit")
def create_study_kit(req: StudyKitRequest):
    if req.filters is None:
        req.filters = SearchFilters()
    req.filters.owner_id = config.owner_id
    topic = req.topic.strip() or "data structures and algorithms fundamentals"
    citations, trace = storage_service.hybrid_search(
        query=f"Key concepts and important facts about {topic}", filters=req.filters,
        top_k=min(50, req.count * 2), use_hybrid=True,
    )
    if not citations:
        return {"kind": req.kind, "topic": topic, "cards": [], "message": "No passages matched those filters. Clear the date or content-type filters, select another source, or add study notes."}
    cards = []
    seen = set()
    for citation in citations:
        source_text = citation.snippet.strip()
        sentences = re.split(r"(?<=[.!?])\s+", source_text)
        usable_sentences = [sentence.strip() for sentence in sentences if len(sentence.strip()) >= 30]
        # Some valid chunks contain headings, short bullets, or one compact fact.
        # Keep those useful passages available to quiz and flashcard generation.
        if not usable_sentences and source_text:
            usable_sentences = [source_text]
        for sentence in usable_sentences:
            sentence = sentence.strip()
            if sentence.lower() in seen:
                continue
            seen.add(sentence.lower())
            section = citation.section or "Key idea"
            front = (f"What does {section} say about {topic}?" if req.kind == "quiz" else section)
            cards.append({"front": front, "back": sentence, "citation": citation.model_dump()})
            if len(cards) >= req.count:
                break
        if len(cards) >= req.count:
            break
    if req.kind == "revision":
        cards = cards[:req.count]
        for index, card in enumerate(cards, 1):
            card["front"] = f"Revision step {index}: {card['front']}"
    return {"kind": req.kind, "topic": topic, "cards": cards, "retrieval_backend": trace.get("retrieval_backend"), "message": "Study prompts are based on the cited passages below."}

# 7. Benchmark Evaluation Suite with Ablation & Custom Test Cases
@app.post("/api/eval/run", response_model=EvalSummary)
def run_evaluation(req: Optional[CustomEvalRequest] = None):
    custom_tests = req.test_cases if req and req.test_cases else None
    summary = benchmark_evaluator.run_benchmark(custom_tests)
    return summary

@app.get("/api/eval/defaults")
def get_eval_defaults():
    return benchmark_evaluator.default_test_cases

# 8. Static files and UI
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Nexora Server Running</h1><p>UI is loading...</p>"

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
