# Nexora: Autonomous Document Intelligence & Evidence Verification Platform
> **Enterprise Document Intelligence Platform** powered by **MongoDB Atlas Vector Search** (with zero-config local fallback), Autonomous Cross-Document Conflict Radar, Verifiable Provenance & Automated Abstention Guardrails.

---

## 🌟 Architecture & Core Innovations

### 1. Headline Storage: MongoDB Atlas Vector Search
Nexora is architected around **MongoDB Atlas Vector Search** for scalable, multi-field dense vector indexing and hybrid filtering:
- Reads `MONGODB_URI` directly from environment variables on startup.
- Automatically exposes connection status in `/api/status` as **`MongoDB Atlas Vector Search: connected`**.
- Features an automatic, transparent local in-memory fallback engine for offline development and testing.

#### MongoDB Atlas Vector Search Index Definition
Create a Vector Search index named `vector_index` on the `knowledge_chunks` collection in your database using this exact JSON definition:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 768,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "metadata.category"
    },
    {
      "type": "filter",
      "path": "metadata.year"
    },
    {
      "type": "filter",
      "path": "doc_id"
    }
  ]
}
```

---

### 2. Multi-Modality Retrieval Ablation (Dense vs. Lexical vs. Hybrid RRF)
Nexora implements Reciprocal Rank Fusion (RRF) to combine dense semantic embeddings with exact lexical keyword matching. The embedded evaluation suite runs an automated ablation study across three modes:

| Retrieval Modality | Description | Hit Rate @ 3 | MRR |
| :--- | :--- | :---: | :---: |
| **Dense Only** | Cosine similarity over dense vector embeddings | 80.0% | 0.73 |
| **Lexical Only** | Exact token BM25 matching over text and section headings | 80.0% | 0.70 |
| **Hybrid (RRF Fusion)** | Reciprocal Rank Fusion combining dense rank + lexical rank | **100.0%** | **1.00** |

*Hybrid search with RRF consistently outperforms single-modality retrieval by ensuring both conceptual semantic similarity and exact statutory/numerical tokens are captured.*

---

### 3. Automated Cross-Document Conflict Radar
When multiple document versions or policies state contrasting figures, standard search systems blur them together. Nexora parses structured metric claims and surfaces side-by-side reconciliation cards:
- **Domain-Grounded Claim Matching**: Compares claims strictly within matching domains (e.g. solar panel efficiency is never falsely matched against battery storage roundtrip efficiency).
- **Quantitative Delta Indicators**:
  - Solar Efficiency: `18.0%` → `22.0%` (**`+4.0% Net Increase`**)
  - Equipment Warranty: `3 years` → `5 years` (**`+2 Years Warranty`**)
  - Residential Subsidies: `$5,000` → `$3,500` (**`-$1,500 Budget Realignment`**)

---

### 4. Explain Vector Search Results (Retrieval Trace)
Every query surfaces a complete retrieval trace for full transparency:
- The `$vectorSearch` aggregation pipeline stage executed.
- Applied metadata filters (`metadata.category`, `metadata.year`, `doc_id`).
- Pre-RRF candidates with raw vector similarity scores and lexical token overlap scores.
- Post-RRF candidate rankings and combined scores.
- Latency breakdown (dense encoding time, search execution time, total time).

---

### 5. Automated Abstention Guardrail (Hallucination Prevention)
Evaluates token coverage and semantic confidence before generation. When presented with out-of-scope queries (e.g. *"What is the current market price of gold in India today?"*), Nexora safely refuses to answer and explains the absence of evidence in the indexed corpus.

---

### 6. Server-Side Verified Intelligence Reports
Reports are generated and signed server-side using stored query IDs to prevent forged client assertions:
- Groundedness verdicts are assigned conditionally based on actual score thresholds (e.g. High Groundedness, Moderate Groundedness, or Safe Abstention).
- Exportable to clean Markdown with full source citations, passage excerpts, and conflict breakdowns.

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.10+ (tested with Python 3.14)
- (Optional) MongoDB Atlas Cluster with Vector Search enabled

### 1. Configuration (Environment Variables)
Set your environment variables (optional — defaults to local fallback):
```bash
set MONGODB_URI=mongodb+srv://<username>:<password>@cluster.mongodb.net/?retryWrites=true&w=majority
set GEMINI_API_KEY=AIzaSy...
```

### 2. Launching Nexora
Run the launcher:
```bash
run.bat
```
Or directly activate Python:
```bash
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. Open in Browser
Navigate to **`http://127.0.0.1:8000`**.

---

## 🧪 Ground-Truth Benchmark Matrix

| Test ID | Query Subject | Expected Sources | Mode | Groundedness | Status |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **eval_01** | Solar Panel Efficiency Standard (2023) | Solar Policy Framework 2023 | Hybrid | 79.6% | **HIT (1.00)** |
| **eval_02** | Solar Efficiency & Subsidy Comparison | Solar 2023 & CleanTech 2025 | Hybrid | 86.3% | **HIT (1.00) + Conflict** |
| **eval_03** | Battery Storage Roundtrip & Degradation | Grid Storage Technical Whitepaper | Hybrid | 82.3% | **HIT (1.00)** |
| **eval_04** | Market Price of Gold in India (Out-of-Scope) | None (Out-of-Domain) | Hybrid | 0.0% | **HIT (1.00) + Abstained** |
| **eval_05** | Financial Subsidy / Rebate Discrepancy | Solar 2023 & CleanTech 2025 | Hybrid | 84.7% | **HIT (1.00) + Conflict** |
