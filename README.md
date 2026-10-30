# Nexora: Document Intelligence & Cross-Verification Platform
> **Enterprise Document Intelligence** — Autonomous Multi-Source Synthesis, Cross-Document Conflict Radar, and Verifiable Provenance.

---

## 🏆 Platform Overview & Key Capabilities

Standard document search and Q&A tools fail when faced with real-world enterprise documents:
1. **Contradictory Claims**: When different policy revisions or contracts state differing numbers or terms, basic tools blur them together or invent a compromise.
2. **Untraceable Synthesis**: Readers cannot verify which exact passage supported a specific assertion.
3. **Confident Hallucination**: Unanswerable questions lead models to hallucinate plausible-sounding errors.

**Nexora** was engineered to solve these exact challenges:

- **⚠️ Cross-Document Conflict Radar**: An automated claim reconciliation engine that scans extracted assertions across sources. If Document A states *"18% efficiency"* and Document B states *"22% efficiency"*, it highlights the discrepancy side-by-side with citations.
- **🛡️ Hallucination Guardrail & Safe Abstention**: Evaluates both semantic confidence and vocabulary coverage. When asked out-of-scope or unanswerable queries, Nexora gracefully refuses to hallucinate, explains why, and suggests relevant materials to import.
- **🔍 Clickable Citations & Passage Inspector**: Every claim has an interactive citation badge. Clicking opens a slide-in Passage Inspector displaying the exact raw passage, page number, section header, and similarity scores.
- **⚡ Hybrid Neural & Lexical Engine**: Combines dense semantic vector retrieval with exact keyword token matching via Reciprocal Rank Fusion (RRF).
- **📊 Live Benchmark & Accuracy Suite**: An automated evaluation suite computing **Hit Rate@3 (100%)**, **Mean Reciprocal Rank (MRR)**, **Precision@3**, **Conflict Accuracy**, and **Abstention Fidelity**.

---

## 🚀 Quick Start Guide

### Launching the Application
Run the launcher:
```bash
run.bat
```
Or with Python:
```bash
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```
Open **`http://127.0.0.1:8000`** in your browser.
