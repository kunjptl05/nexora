import os
import time
import re
import hashlib
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from veritas_rag.config import config
from veritas_rag.models import (
    QueryRequest, QueryResponse, DocumentChunk, 
    SearchFilters, EvalSummary, ReportExportRequest,
    CustomEvalRequest
)
from veritas_rag.storage import storage_service
from veritas_rag.embeddings import embedding_service
from veritas_rag.chunker import chunker
from veritas_rag.conflict_radar import conflict_radar
from veritas_rag.generator import generator
from veritas_rag.evaluator import benchmark_evaluator
from veritas_rag.samples import load_sample_datasets

# Modern FastAPI Lifespan Handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure sample benchmark datasets are loaded idempotently
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
        "mongodb_headline": "MongoDB Atlas Vector Search: connected" if storage_service.is_connected else "Local Vector + BM25 (Persistent Local Store)",
        "storage_mode": storage_service.active_mode,
        "mongodb_connected": storage_service.is_connected,
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
    config.gemini_api_key = key
    embedding_service.configure_key(key)
    generator._api_key = key
    re_embedded = storage_service.re_embed_all_chunks()
    return {
        "success": True, 
        "configured": bool(key), 
        "embedding_dim": embedding_service.vector_dim,
        "re_embedded_chunks": re_embedded
    }

# 3. Document Knowledge Base
@app.get("/api/documents")
def list_documents():
    return storage_service.list_documents()

@app.post("/api/documents/upload")
def upload_document(
    title: str = Form(...),
    category: str = Form("General"),
    author: str = Form("Unknown"),
    year: Optional[int] = Form(None),
    text_content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None)
):
    content = ""
    pages_data = None
    file_bytes = b""

    if file and file.filename:
        file_bytes = file.file.read()
        if len(file_bytes) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File exceeds maximum allowed upload limit of 25MB.")
        filename_lower = file.filename.lower()
        if filename_lower.endswith(".pdf"):
            try:
                content, pages_data = chunker.extract_text_from_pdf(file_bytes)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to parse PDF: {str(e)}")
        else:
            try:
                content = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                content = file_bytes.decode("latin-1", errors="ignore")
    elif text_content:
        content = text_content
    else:
        raise HTTPException(status_code=400, detail="Must provide either a file upload or text content.")

    if not content.strip():
        raise HTTPException(status_code=400, detail="Document content cannot be empty.")

    # Deduplicate ingestion using deterministic content hash
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
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
        "file_size_bytes": len(file_bytes) if file_bytes else len(content.encode("utf-8"))
    }

    storage_service.add_document(doc_id, title, metadata, raw_text=content)
    chunks = chunker.chunk_document(doc_id, title, content, metadata, pages=pages_data)
    storage_service.add_chunks(chunks)

    return {
        "success": True,
        "doc_id": doc_id,
        "title": title,
        "chunks_created": len(chunks),
        "total_knowledge_chunks": storage_service.count_chunks()
    }

@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    success = storage_service.delete_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found.")
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
    storage_service.reset()
    load_sample_datasets(force_reload=True)
    return {
        "success": True, 
        "message": "Knowledge base reset to default benchmark datasets.",
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
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found.")
    return chunk.model_dump()

# 6. Core RAG Query Endpoint
@app.post("/api/query", response_model=QueryResponse)
def query_rag(req: QueryRequest):
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
        answer_mode=req.answer_mode
    )
    # Store in server-side query history for authentic report generation
    storage_service.store_query_result(response.query_id, response)
    return response

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
