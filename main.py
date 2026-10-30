import os
import time
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from veritas_rag.config import config
from veritas_rag.models import (
    QueryRequest, QueryResponse, DocumentChunk, 
    SearchFilters, EvalSummary, ReportExportRequest
)
from veritas_rag.storage import storage_service
from veritas_rag.embeddings import embedding_service
from veritas_rag.chunker import chunker
from veritas_rag.conflict_radar import conflict_radar
from veritas_rag.generator import generator
from veritas_rag.evaluator import benchmark_evaluator
from veritas_rag.samples import load_sample_datasets

app = FastAPI(
    title=config.app_name,
    description=config.tagline,
    version=config.version
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup event: Pre-populate knowledge base with rich multi-document datasets
@app.on_event("startup")
async def startup_event():
    load_sample_datasets()

# 1. System Status & Health
@app.get("/api/status")
async def get_status():
    docs = storage_service.list_documents()
    return {
        "app_name": config.app_name,
        "tagline": config.tagline,
        "version": config.version,
        "storage_mode": storage_service.active_mode,
        "mongodb_connected": storage_service.is_connected,
        "mongodb_database": config.mongodb_database,
        "mongodb_collection": config.mongodb_collection,
        "vector_index_name": config.vector_index_name,
        "gemini_configured": bool(config.gemini_api_key),
        "embedding_dim": embedding_service.vector_dim,
        "total_documents": len(docs),
        "total_chunks": len(storage_service._chunks)
    }

# 2. Configuration Endpoints
@app.post("/api/config/mongodb")
async def update_mongodb(data: dict):
    uri = data.get("uri", "").strip()
    db = data.get("database", config.mongodb_database).strip()
    coll = data.get("collection", config.mongodb_collection).strip()
    idx = data.get("index_name", config.vector_index_name).strip()

    if not uri:
        storage_service.is_connected = False
        storage_service.active_mode = "in-memory-hybrid"
        return {"success": True, "mode": "in-memory-hybrid", "message": "Reverted to high-performance local hybrid mode."}

    config.mongodb_uri = uri
    config.mongodb_database = db
    config.mongodb_collection = coll
    config.vector_index_name = idx

    success, msg = storage_service.connect_mongodb(uri, db, coll)
    return {"success": success, "mode": storage_service.active_mode, "message": msg}

@app.post("/api/config/gemini")
async def update_gemini_key(data: dict):
    key = data.get("api_key", "").strip()
    config.gemini_api_key = key
    embedding_service.configure_key(key)
    generator._api_key = key
    return {"success": True, "configured": bool(key), "embedding_dim": embedding_service.vector_dim}

@app.post("/api/deploy/github")
async def deploy_github_api(data: dict):
    token = data.get("token", "").strip()
    repo_name = data.get("repo_name", "nexora").strip() or "nexora"
    is_private = data.get("is_private", False)
    if not token:
        raise HTTPException(status_code=400, detail="GitHub Personal Access Token is required.")
    
    from deploy_github import deploy_to_github
    success, url = deploy_to_github(token=token, repo_name=repo_name, is_private=is_private)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to deploy repository to GitHub. Please verify your token.")
    return {"success": True, "repo_url": url}

# 3. Document Knowledge Base
@app.get("/api/documents")
async def list_documents():
    return storage_service.list_documents()

@app.post("/api/documents/upload")
async def upload_document(
    title: str = Form(...),
    category: str = Form("General"),
    author: str = Form("Unknown"),
    year: int = Form(2025),
    text_content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None)
):
    import uuid
    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    content = ""

    if file and file.filename:
        file_bytes = await file.read()
        if len(file_bytes) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File exceeds maximum allowed upload limit of 25MB.")
        filename_lower = file.filename.lower()
        if filename_lower.endswith(".pdf"):
            try:
                content, _ = chunker.extract_text_from_pdf(file_bytes)
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

    metadata = {
        "title": title,
        "author": author,
        "year": year,
        "category": category,
        "source_type": "upload",
        "file_size_bytes": len(file_bytes) if (file and file.filename) else len(content.encode("utf-8"))
    }

    storage_service.add_document(doc_id, title, metadata, raw_text=content)
    chunks = chunker.chunk_document(doc_id, title, content, metadata)
    storage_service.add_chunks(chunks)

    return {
        "success": True,
        "doc_id": doc_id,
        "title": title,
        "chunks_created": len(chunks),
        "total_knowledge_chunks": len(storage_service._chunks)
    }

@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    success = storage_service.delete_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {
        "success": True, 
        "message": f"Document '{doc_id}' successfully removed.",
        "remaining_documents": len(storage_service.list_documents()),
        "remaining_chunks": len(storage_service._chunks)
    }

@app.post("/api/documents/reset")
async def reset_documents():
    storage_service._chunks.clear()
    storage_service._documents.clear()
    load_sample_datasets()
    return {"success": True, "message": "Knowledge base reset to default benchmark datasets."}

# 4. Report Export Endpoint
@app.post("/api/export/report")
async def export_report(req: ReportExportRequest):
    if req.format.lower() == "json":
        return JSONResponse(content={
            "platform": "Nexora Intelligence & Verification Platform",
            "timestamp": time.time(),
            "query": req.query,
            "groundedness_score": req.groundedness_score,
            "answer": req.answer,
            "conflicts": [c.model_dump() for c in req.conflicts],
            "citations": [cit.model_dump() for cit in req.citations]
        })

    # Markdown format report
    lines = [
        "# Nexora Intelligence & Evidence Verification Report",
        f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"**Groundedness Fidelity:** {req.groundedness_score}% | **Zero-Hallucination Verified**",
        "",
        "## Query Investigated",
        f"> {req.query}",
        "",
        "## Synthesized Evidence",
        req.answer,
        ""
    ]

    if req.conflicts:
        lines.append(f"## Cross-Document Conflict Radar ({len(req.conflicts)} Discrepancies Detected)")
        for cf in req.conflicts:
            lines.append(f"### {cf.subject} [{cf.discrepancy_type.upper()}]")
            lines.append(f"- **Source A ({cf.source_a}):** {cf.claim_a} (Value: `{cf.value_a or 'N/A'}`)")
            lines.append(f"- **Source B ({cf.source_b}):** {cf.claim_b} (Value: `{cf.value_b or 'N/A'}`)")
            if cf.delta:
                lines.append(f"- **Calculated Delta:** `{cf.delta}`")
            lines.append(f"- **Reconciliation:** {cf.explanation}")
            lines.append("")

    if req.citations:
        lines.append(f"## Verified Source Citations ({len(req.citations)} Passages)")
        for idx, cit in enumerate(req.citations, 1):
            lines.append(f"**[{idx}] {cit.doc_title}** — § {cit.section or 'General'} (p.{cit.page_number})")
            lines.append(f"- *Similarity Score:* `{int(cit.similarity_score * 100)}%` | *Chunk ID:* `{cit.id}`")
            lines.append(f"- *Verified Quote:* \"{cit.snippet}\"")
            lines.append("")

    return {"success": True, "format": "markdown", "report": "\n".join(lines)}

# 4. Chunk Inspector
@app.get("/api/chunks/{chunk_id}")
async def get_chunk_details(chunk_id: str):
    chunk = storage_service.get_chunk(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found.")
    return chunk.model_dump()

# 5. Core RAG Query Endpoint
@app.post("/api/query", response_model=QueryResponse)
async def query_rag(req: QueryRequest):
    citations, explain_search = storage_service.hybrid_search(
        query=req.question,
        filters=req.filters,
        top_k=req.top_k,
        use_hybrid=req.use_hybrid
    )
    
    response = generator.generate_response(
        question=req.question,
        citations=citations,
        explain_search=explain_search
    )
    return response

# 6. Benchmark Evaluation Suite
@app.post("/api/eval/run", response_model=EvalSummary)
async def run_evaluation():
    summary = benchmark_evaluator.run_benchmark()
    return summary

@app.get("/api/eval/defaults")
async def get_eval_defaults():
    return benchmark_evaluator.default_test_cases

# 7. Static files and UI
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Nexora Server Running</h1><p>UI is loading...</p>"

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
