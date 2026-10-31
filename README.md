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

## Grounded answer modes

The Workspace offers two answer modes:

- **Grounded:** produces a concise answer from retrieved passages, attaches inline citation numbers, and includes the matching original sentences with document, section, and page references.
- **Exact source text:** returns relevant original sentences without paraphrasing.

For list and component questions, Nexora is instructed to enumerate only items explicitly present in retrieved evidence. It distinguishes battery chemistries from physical cell components. If a document names a chemistry but does not describe internal parts, Nexora says the component breakdown is not present instead of filling the gap with a generic list.

The local structured path handles battery component questions deterministically to avoid unsupported completion. For other questions, Gemini generation (when configured) receives strict source-only instructions; the local fallback extracts relevant source sentences. Retrieved source passages remain available in the Evidence Inspector.

## Structured form-field lookup

Before vector retrieval, Nexora detects common field-oriented questions (for example, "What is the name of the person in this document?") and searches values extracted from labelled form fields. It supports common labels such as candidate/applicant name, application ID, record ID, date of birth, email, phone, gender, category, university, institute, bank details, and family income.

This path is deterministic: it returns the value following the matching label and cites the source line, document, and page. It handles multiple `Label: value` fields on one extracted PDF line and common page markers. Field lookups respect the current document scope and category/year filters. When the label/value is not present, Nexora falls back to normal document retrieval rather than fabricating a field value.

The field extraction uses the text returned by PDF parsing. Scanned/image-only PDFs still require OCR before their text fields can be extracted; the current upload parser does not run OCR. Complex tables and visually aligned columns may also need a layout-aware parser.

## Retrieval architecture

Nexora supports three retrieval modes:

| Mode | Behaviour |
| --- | --- |
| Dense | Vector similarity over the selected embedding model's output |
| Lexical | BM25 lexical ranking in the local engine; Atlas Search's lexical text ranking when Atlas is enabled |
| Hybrid | Reciprocal Rank Fusion (RRF) over dense and lexical rankings |

The local lexical implementation uses BM25 term frequency, document frequency, and document-length normalization. Atlas retrieval modes are executed separately for the ablation comparison. If Atlas hybrid fusion is unavailable, the application falls back to the local hybrid engine rather than reporting a dense-only result as hybrid.

The default hosted embedding model is `gemini-embedding-001`, with separate document/query retrieval task types. The local embedding fallback is a deterministic hashed-feature encoder; it allows zero-configuration development but is not equivalent to a trained semantic embedding model. Nexora now fails visibly rather than silently switching from a hosted vector space to the local 128-dimensional space after a provider error.

**Embedding migration note:** the default hosted model change affects the vector space. Re-embed all existing chunks after changing the embedding model or dimensions. Do not mix embeddings from different models in one collection. Ensure the Atlas vector index dimension matches the configured embedding output (the default here is 768).

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
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, run the app using the venv interpreter directly:

```powershell
./.venv/Scripts/python.exe -m pip install -r requirements.txt
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

For Atlas lexical search, create a Search index named `chunk_text` on `content`, `doc_title`, and `section`. The query filter also uses `metadata.category`, `metadata.year`, and `doc_id`; map these fields as filterable fields in the Search index. Confirm the index is ready before using Atlas lexical or hybrid retrieval.

Nexora stores document-level raw text and extracted field values in the Atlas `documents` collection, and source lines generated by direct field lookup in `field_extractions`. Keep both collections access-controlled because they may contain personal information from uploaded forms. Resetting or deleting a document removes the corresponding field evidence records.

## Run locally

The Windows launcher creates the `.venv` environment when needed, checks/installs the requirements, and starts the local FastAPI server:

```powershell
.\run.bat
```

Or start Uvicorn directly:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Open:

- App: http://127.0.0.1:8000
- API documentation: http://127.0.0.1:8000/docs
- Health/status: http://127.0.0.1:8000/api/status

The server binds to loopback by default for local development. Do not expose it to a public network without adding authentication/authorization, rate limiting, secure secret management, and production-grade upload and storage controls.

## Local data

The local fallback persists its document metadata and chunk content in `data_store.json`. This file may contain private uploaded text. Keep it local and out of version control. It is not a substitute for a managed, access-controlled database or a backup strategy.

## Automated tests

Run the unit tests locally with:

```powershell
python -m compileall -q main.py veritas_rag tests
python -m unittest discover -s tests -v
```

The same checks run in GitHub Actions on pushes to `main` / `nexora/**` and pull requests into `main`.

## Evaluation

Use the **Benchmark & Ablation** screen or send:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/eval/run
```

The evaluation response reports the configured sample metrics and per-case results. Interpret the output in the context of the evaluation set; do not present these numbers as universal accuracy guarantees.

## Known limitations

- Conflict detection is heuristic and may produce false positives or miss paraphrased contradictions.
- The local feature-hash embedding fallback is not a learned semantic model.
- Abstention relies on query-term coverage rather than a trained reranker or calibrated relevance classifier; it does not guarantee that every unsupported answer will be rejected.
- Form-field extraction is label-based and only works when the PDF parser can extract readable text; scanned forms and complex layouts may require OCR or a layout-aware parser.
- Comparative retrieval currently balances the number of passages returned per document for obvious comparison queries; it is not a full Maximal Marginal Relevance (MMR) reranker.
- Atlas metadata and extracted-field records are loaded from the separate `documents` collection; older deployments may need to re-upload documents or migrate records if that collection was never populated.
- Query-result report exports are held in the running process's bounded in-memory cache. Re-run a query after restarting the server before exporting its report.
- Authentication and role-based access control are not yet implemented. Keep the server local and do not deploy it as a public multi-user service in its current form.

## Before production

1. Add authentication, role-based authorization, and tenant isolation.
2. Add upload content-type validation, malware scanning, size limits, and per-user quotas.
3. Persist query history and report metadata securely.
4. Add a layout-aware parser/OCR pipeline for scanned forms and complex PDF tables.
5. Add a trained reranker and calibrated abstention evaluation; current query-term coverage is a heuristic.
6. Expand labelled automated tests for retrieval mode parity, conflicts, abstention, report export, and embedding dimension changes.
7. Evaluate on a larger, independently labelled dataset and publish reproducible benchmark methodology.

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
    ├── field_extractor.py
    ├── generator.py
    ├── models.py
    ├── samples.py
    └── storage.py
```
