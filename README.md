# NEXORA

NEXORA is a study assistant that helps students learn from their own files. Students can upload notes and readings, ask questions across selected sources, review cited passages, see a summary for each file, and check selected materials for possible conflicts.

## How it works

1. **Add study materials.** Upload PDF, DOCX, TXT, or Markdown files, paste text, or provide a public webpage URL.
2. **Extract and prepare the content.** The server extracts readable text, keeps page information where available, records document details, creates a short summary, and splits the content into searchable passages.
3. **Index the passages.** NEXORA creates embeddings and stores passages in MongoDB Atlas when configured, or in its local persistent store for development.
4. **Ask a question.** The server applies the selected document and metadata filters, searches passages using vector and lexical retrieval, and sends the most relevant evidence to the answer generator.
5. **Review the answer.** Answers include citations. Selecting a citation opens the original file or source view, while the cited passage stays available for verification.
6. **Study across files.** The Knowledge Base shows each file’s summary and a control to open the original. Conflict checks search selected materials and show retrieved evidence that may disagree.
7. **Keep conversations separate.** Students can start and switch between conversations. Conversation history is saved in the current browser.

## How it is made

- **Web app:** HTML, Tailwind CSS, and JavaScript in `static/`.
- **Application server:** Python and FastAPI in `main.py`.
- **Retrieval:** `veritas_rag/` extracts and chunks documents, builds embeddings, applies metadata and owner filters, and retrieves evidence using dense, lexical, or hybrid search.
- **Answer generation:** Gemini can write source-grounded answers and file summaries when `GEMINI_API_KEY` is configured. Without it, NEXORA uses a local extractive fallback and locally generated file overviews.
- **Storage:** MongoDB Atlas Vector Search is supported. A local persistent store is available for development without Atlas.

## Open NEXORA on your computer

Install Python 3.10 or newer, download or clone this repository, then open PowerShell in the project folder (the folder containing `run.bat`). Start the app:

```powershell
.\run.bat
```

The launcher creates the virtual environment and installs the project requirements the first time it runs. Keep that terminal open while using NEXORA. When the server reports that it is running, open **http://127.0.0.1:8000** in your browser. To stop the app, return to the terminal and press `Ctrl+C`.

If you prefer to start it manually:

```powershell
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

If the address does not open, check that the terminal still shows the server running and that port `8000` is available. The server listens only on this computer by default.

To enable Gemini answers and AI-written file summaries, set an API key before starting the app:

```powershell
$env:GEMINI_API_KEY = "your-gemini-api-key"
.\run.bat
```

For Atlas retrieval, configure `MONGODB_URI`, `MONGODB_DB`, `MONGODB_COLLECTION`, and `MONGODB_VECTOR_INDEX`. Use Gemini embeddings at 768 dimensions and configure both Atlas indexes before retrieval:

- `vector_index` for vector search and metadata filters.
- `chunk_text` for lexical search over chunk text.

Both indexes must be ready, and stored embeddings must match the configured Gemini model and dimensions. `GET /api/status` reports connection and index readiness. The local store is used when Atlas is not configured.

## Project workflow

```text
Student files
    ↓
Text extraction and page tracking
    ↓
Document summary + searchable chunks
    ↓
Embedding and local or Atlas storage
    ↓
Question + selected files and filters
    ↓
Vector / lexical retrieval
    ↓
Grounded answer with citations and original-source access
```

## Important behavior

- Search, summaries, source access, and deletion are scoped by the server-configured `NEXORA_OWNER_ID`.
- PDF citations preserve page references. Scanned PDFs without extractable text require OCR, which is not included.
- Local fallback answers quote relevant source sentences; Gemini is needed for fluent paraphrasing and generated summaries.
- Conflict checks highlight possible differences for review; they do not prove that sources contradict each other.
- Conversation history is browser-local and does not sync between devices.

## Tests

```powershell
python -m compileall -q main.py veritas_rag tests
python -m unittest discover -s tests -v
```
