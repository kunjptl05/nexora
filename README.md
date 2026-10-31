# Nexora — Evidence-first Document Intelligence

Nexora helps users search across multiple documents, inspect source passages, and identify **potentially conflicting claims**. Answers include document references so users can verify the evidence themselves.

> Nexora is a document analysis assistant, not an authoritative legal, regulatory, financial, or medical source. Always check the original documents before acting on a finding.

## What it does

- **Document Q&A:** Ask questions over the indexed document collection.
- **Evidence inspection:** Review retrieved passages, document names, sections, and page references.
- **Conflict Radar:** Highlights possible differences in numerical claims, policy revisions, and selected rule wording across sources.
- **Evidence-aware abstention:** Uses retrieval signals and query-term coverage to flag questions that appear unsupported by the indexed corpus.
- **Retrieval trace:** Shows search mode, filters, candidate ranks, and timing information.
- **Evaluation suite:** Runs a small sample set for retrieval, conflict-detection, abstention, and latency measurements.
- **Report export:** Exports Markdown or JSON from a query result retained by the running server.

## Retrieval architecture

Nexora supports three retrieval modes:

| Mode | Behaviour |
| --- | --- |
| Dense | Vector similarity over the selected embedding model's output |
| Lexical | BM25 lexical ranking in the local engine; Atlas Search's lexical text ranking when Atlas is enabled |
| Hybrid | Reciprocal Rank Fusion (RRF) over dense and lexical rankings |

The local lexical implementation uses BM25 term frequency, document frequency, and document-length normalization. Atlas retrieval modes are executed separately for the ablation comparison. If Atlas hybrid fusion is unavailable, the application falls back to the local hybrid engine rather than reporting a dense-only result as hybrid.

The local embedding fallback is a deterministic hashed-feature encoder. It allows zero-configuration development but is not equivalent to a trained semantic embedding model. For stronger semantic retrieval, configure Gemini embeddings and ensure the Atlas vector index dimension matches the actual embedding output.

## Conflict Radar: interpretation and limitations

Conflict Radar uses rule-based extraction and matching to surface **candidate discrepancies**. It compares metric labels, topical domains, and normalized units before computing a numerical difference. Policy-revision signals are limited to explicit amendment/supersession language.

This is a heuristic review aid, not a semantic proof that two statements contradict. Different conditions, populations, jurisdictions, dates, or measurement methods may explain different values. Confirm each finding against the cited source passages before treating it as a real conflict.

## Demo data and benchmark honesty

The repository includes five **synthetic demonstration documents** and a five-case sample evaluation set. Names and institutional attributions in those examples are illustrative and should not be treated as real publications or official policy documents.

Benchmark figures are not hard-coded as product claims. Run the evaluation suite in your own environment and report the test-set size, dataset, retrieval backend, embedding model, and measured results alongside any metrics. A five-case sample is useful for a smoke test, not evidence of general accuracy.

## Requirements

- Python 3.10 or newer
- Optional: MongoDB Atlas with Vector Search and Search indexes configured
- Optional: Gemini API key for hosted embeddings and answer generation

Install the dependencies in a virtual environment:

### Windows PowerShell

```powershell
cd "C:\path\to\nexora"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, run the app using the venv interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Configuration (optional)

Set environment variables in the same PowerShell window before starting the server:

```powershell
$env:GEMINI_API_KEY = "your-gemini-api-key"
$env:MONGODB_URI = "mongodb+srv://..."
$env:MONGODB_DB = "nexora_db"
$env:MONGODB_COLLECTION = "knowledge_chunks"
$env:MONGODB_VECTOR_INDEX = "vector_index"
```

Do not commit API keys, database credentials, uploaded files, or private document content.

### MongoDB Atlas indexes

The vector index named `vector_index` must target the `embedding` field and use the same `numDimensions` as the active embedding model. The example below is for a 768-dimensional embedding output:

```json
{
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 768, "similarity": "cosine" },
    { "type": "filter", "path": "metadata.category" },
    { "type": "filter", "path": "metadata.year" },
    { "type": "filter", "path": "doc_id" }
  ]
}
```

For Atlas lexical search, create a Search index named `chunk_text` on `content`, `doc_title`, and `section`. Confirm the index is ready before using Atlas lexical or hybrid retrieval.

## Run locally

The repository includes a Windows launcher:

```powershell
.un.bat
```

Or start Uvicorn directly:

```powershell
..venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Open:

- App: http://127.0.0.1:8000
- API documentation: http://127.0.0.1:8000/docs
- Health/status: http://127.0.0.1:8000/api/status

The server binds to loopback by default for local development. Do not expose it to a public network without adding authentication/authorization, rate limiting, secure secret management, and production-grade upload and storage controls.

## Local data

The local fallback persists its document metadata and chunk content in `data_store.json`. This file may contain private uploaded text. Keep it local and out of version control. It is not a substitute for a managed, access-controlled database or a backup strategy.

## Evaluation

Use the **Benchmark & Ablation** screen or send:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/eval/run
```

The evaluation response reports the configured sample metrics and per-case results. Interpret the output in the context of the evaluation set; do not present these numbers as universal accuracy guarantees.

## Known limitations

- Conflict detection is heuristic and may produce false positives or miss paraphrased contradictions.
- The local feature-hash embedding fallback is not a learned semantic model.
- Abstention relies on configurable retrieval heuristics; it does not guarantee that every unsupported answer will be rejected.
- Query-result report exports are held in the running process's bounded in-memory cache. Re-run a query after restarting the server before exporting its report.
- Authentication and role-based access control are not yet implemented. Keep the server local and do not deploy it as a public multi-user service in its current form.

## Before production

1. Add authentication, role-based authorization, and tenant isolation.
2. Add upload content-type validation, malware scanning, size limits, and per-user quotas.
3. Persist query history and report metadata securely.
4. Add comprehensive automated tests for retrieval mode parity, conflicts, abstention, report export, and embedding dimension changes.
5. Evaluate on a larger, independently labelled dataset and publish reproducible benchmark methodology.

## Project layout

```text
.
├── main.py
├── run.bat
├── static/
│   ├── index.html
│   └── app.js
└── veritas_rag/
    ├── chunker.py
    ├── config.py
    ├── conflict_radar.py
    ├── embeddings.py
    ├── evaluator.py
    ├── generator.py
    ├── models.py
    ├── samples.py
    └── storage.py
```
