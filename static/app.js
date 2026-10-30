// Nexora Frontend Controller

let appState = {
  activeTab: 'chat',
  status: null,
  documents: [],
  evalResults: null,
  currentCitations: {}
};

document.addEventListener('DOMContentLoaded', () => {
  initApp();
});

async function initApp() {
  await fetchStatus();
  await loadDocuments();
  lucide.createIcons();
}

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    appState.status = data;
    
    // Update header badges
    const modeText = document.getElementById('statusModeText');
    const docCountBadge = document.getElementById('docCountBadge');
    
    if (data.mongodb_connected) {
      modeText.textContent = `Cloud Cluster Connected`;
      modeText.className = "text-orange-700 font-bold";
    } else {
      modeText.textContent = `Neural Engine Active`;
      modeText.className = "text-stone-800 font-semibold";
    }
    docCountBadge.textContent = `${data.total_documents} docs / ${data.total_chunks} chunks`;
  } catch (err) {
    console.error('Failed to fetch status:', err);
  }
}

function switchTab(tabId) {
  appState.activeTab = tabId;
  const tabs = ['chat', 'docs', 'conflict', 'eval', 'arch'];
  
  tabs.forEach(t => {
    const section = document.getElementById(`tab-${t}`);
    const btn = document.getElementById(`tabBtn-${t}`);
    if (t === tabId) {
      section.classList.remove('hidden');
      btn.className = "tab-btn px-3 py-1 rounded-xl text-[11px] font-bold flex items-center gap-1.5 transition-all bg-gradient-to-r from-orange-500 to-rose-500 text-white shadow-xs";
    } else {
      section.classList.add('hidden');
      btn.className = "tab-btn px-3 py-1 rounded-xl text-[11px] font-medium flex items-center gap-1.5 transition-all text-stone-600 hover:text-stone-900 hover:bg-white/80";
    }
  });

  if (tabId === 'docs') loadDocuments();
  if (tabId === 'eval' && !appState.evalResults) runFullBenchmark();
  lucide.createIcons();
}

// ----------------- CHAT & WORKSPACE -----------------

function runSamplePrompt(promptText) {
  switchTab('chat');
  document.getElementById('queryInput').value = promptText;
  handleQuerySubmit(new Event('submit'));
}

async function handleQuerySubmit(e) {
  if (e) e.preventDefault();
  const input = document.getElementById('queryInput');
  const question = input.value.trim();
  if (!question) return;

  const useHybrid = document.getElementById('useHybridToggle').checked;
  const topK = parseInt(document.getElementById('topKSelect').value);
  const sendBtn = document.getElementById('sendBtn');

  // Append user message
  appendUserMessage(question);
  input.value = '';
  sendBtn.disabled = true;

  // Append loading skeleton
  const loadingId = appendLoadingIndicator();

  try {
    const res = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: question,
        use_hybrid: useHybrid,
        top_k: topK
      })
    });
    const data = await res.json();
    removeLoadingIndicator(loadingId);
    appendAssistantResponse(data);
  } catch (err) {
    removeLoadingIndicator(loadingId);
    appendErrorMessage(err.message);
  } finally {
    sendBtn.disabled = false;
    lucide.createIcons();
  }
}

function appendUserMessage(text) {
  const stream = document.getElementById('chatStream');
  const div = document.createElement('div');
  div.className = "flex justify-end";
  div.innerHTML = `
    <div class="max-w-2xl bg-white border border-stone-200 rounded-2xl p-4 text-xs text-stone-900 shadow-2xs">
      <div class="flex items-center gap-2 mb-1 text-[11px] font-bold text-orange-600">
        <i data-lucide="user" class="w-3.5 h-3.5"></i> User Query
      </div>
      <p class="leading-relaxed font-semibold">${escapeHtml(text)}</p>
    </div>
  `;
  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;
  lucide.createIcons();
}

function appendLoadingIndicator() {
  const stream = document.getElementById('chatStream');
  const id = `loading_${Date.now()}`;
  const div = document.createElement('div');
  div.id = id;
  div.className = "flex items-start gap-3";
  div.innerHTML = `
    <div class="w-9 h-9 rounded-xl bg-orange-50 border border-orange-200 flex items-center justify-center shrink-0 shadow-2xs">
      <i data-lucide="sparkles" class="w-4 h-4 text-orange-600 animate-spin"></i>
    </div>
    <div class="skin-surface p-4 rounded-2xl text-xs text-stone-600 flex items-center gap-3 shadow-2xs">
      <span class="w-2.5 h-2.5 rounded-full bg-orange-500 animate-ping"></span>
      <span class="font-medium">Synthesizing multi-source evidence, checking conflict radar, verifying citations...</span>
    </div>
  `;
  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;
  lucide.createIcons();
  return id;
}

function removeLoadingIndicator(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function appendAssistantResponse(data) {
  const stream = document.getElementById('chatStream');
  const div = document.createElement('div');
  div.className = "flex items-start gap-3";

  // Store citations in memory for clicking
  if (data.citations) {
    data.citations.forEach(c => {
      appState.currentCitations[c.id] = c;
    });
  }

  // Format conflicts block
  let conflictsHtml = '';
  if (data.conflicts && data.conflicts.length > 0) {
    conflictsHtml = `
      <div class="mt-4 p-4 rounded-xl bg-orange-50/80 border border-orange-200 text-stone-900">
        <div class="flex items-center gap-2 font-bold text-xs text-orange-700 mb-2">
          <i data-lucide="alert-triangle" class="w-4 h-4"></i> Cross-Document Conflict Radar (${data.conflicts.length} Discrepancies Detected)
        </div>
        <div class="space-y-2">
          ${data.conflicts.map(cf => `
            <div class="p-3.5 rounded-lg bg-white border border-orange-200 text-[11px] shadow-2xs">
              <div class="font-bold text-stone-900 mb-1 flex items-center justify-between">
                <span>${escapeHtml(cf.subject)}</span>
                <span class="px-2 py-0.5 bg-orange-100 text-orange-800 rounded text-[9px] uppercase font-bold border border-orange-200">${escapeHtml(cf.discrepancy_type)}</span>
              </div>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-2 my-2 text-stone-800">
                <div class="p-2.5 rounded bg-[#FAF7F2] border border-stone-200">
                  <span class="text-stone-500 block text-[10px] font-bold">${escapeHtml(cf.source_a)}:</span>
                  <span class="font-semibold text-stone-900">${escapeHtml(cf.claim_a)}</span>
                </div>
                <div class="p-2.5 rounded bg-[#FAF7F2] border border-stone-200">
                  <span class="text-stone-500 block text-[10px] font-bold">${escapeHtml(cf.source_b)}:</span>
                  <span class="font-semibold text-stone-900">${escapeHtml(cf.claim_b)}</span>
                </div>
              </div>
              <p class="text-stone-600 leading-normal italic font-medium">${escapeHtml(cf.explanation)}</p>
            </div>
          `).join('')}
        </div>
      </div>
    `;

    // Also update Conflict Lab tab
    updateConflictLab(data.conflicts);
  }

  // Format citations list
  let citationsHtml = '';
  if (data.citations && data.citations.length > 0) {
    citationsHtml = `
      <div class="mt-4 pt-3 border-t border-stone-100">
        <div class="flex items-center justify-between mb-2">
          <span class="text-[11px] font-bold text-stone-800 flex items-center gap-1.5">
            <i data-lucide="quote" class="w-3.5 h-3.5 text-orange-500"></i> Verified Source Passages (${data.citations.length} cited)
          </span>
          <span class="text-[10px] text-stone-400 font-medium">Click to inspect exact passage</span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
          ${data.citations.map(c => `
            <div onclick="openPassageModal('${c.id}')" 
                 class="p-3 rounded-xl bg-white border border-stone-200 hover:border-orange-400 cursor-pointer transition-all text-[11px] group shadow-2xs">
              <div class="flex items-center justify-between mb-1">
                <span class="font-bold text-stone-900 truncate group-hover:text-orange-600">${escapeHtml(c.doc_title)}</span>
                <span class="px-1.5 py-0.5 rounded bg-orange-50 text-[9px] text-orange-800 font-bold border border-orange-200 font-mono">${(c.similarity_score * 100).toFixed(0)}% Match</span>
              </div>
              <p class="text-stone-600 line-clamp-2 leading-relaxed">${escapeHtml(c.snippet)}</p>
              <div class="flex items-center gap-2 mt-1.5 text-[10px] text-stone-400 font-semibold">
                <span>§ ${escapeHtml(c.section || 'General')}</span>
                <span>•</span>
                <span>p.${c.page_number}</span>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  // Format explain plan accordion
  let explainHtml = '';
  if (data.explain_search) {
    explainHtml = `
      <details class="mt-4 pt-2 border-t border-stone-100 text-[11px]">
        <summary class="cursor-pointer text-stone-400 hover:text-stone-700 font-mono flex items-center gap-1.5 select-none font-semibold">
          <i data-lucide="terminal" class="w-3.5 h-3.5 text-stone-400"></i>
          <span>Execution Details & Neural Query Pipeline</span>
        </summary>
        <div class="mt-2 p-3 rounded-xl bg-[#FAF7F2] border border-stone-200 font-mono text-[10px] text-stone-800 overflow-x-auto space-y-1">
          <div><span class="text-stone-600 font-bold">Execution Mode:</span> ${escapeHtml(data.explain_search.mode)}</div>
          <div><span class="text-stone-600 font-bold">Encoding Latency:</span> ${data.explain_search.embedding_time_ms} ms</div>
          <div><span class="text-stone-600 font-bold">Total Request Latency:</span> ${data.latency_ms} ms</div>
          <div class="pt-1 text-stone-500 font-bold">Neural Aggregation Pipeline:</div>
          <pre class="text-stone-900 bg-white p-2 rounded border border-stone-200 overflow-x-auto">${escapeHtml(JSON.stringify(data.explain_search.aggregation_pipeline, null, 2))}</pre>
        </div>
      </details>
    `;
  }

  const groundedBadge = data.abstained 
    ? `<span class="px-2.5 py-0.5 rounded-full bg-rose-50 text-rose-800 border border-rose-200 text-[10px] font-bold">Safe Abstention</span>`
    : `<span class="px-2.5 py-0.5 rounded-full bg-orange-50 text-orange-800 border border-orange-200 text-[10px] font-bold">${data.groundedness_score}% Grounded</span>`;

  div.innerHTML = `
    <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-orange-500 to-rose-500 flex items-center justify-center shrink-0 shadow-xs text-white">
      <i data-lucide="sparkles" class="w-4 h-4"></i>
    </div>
    <div class="flex-1 skin-surface rounded-2xl p-5 shadow-xs max-w-4xl text-xs">
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          <span class="font-extrabold text-stone-950 text-sm">Nexora Synthesis</span>
          ${groundedBadge}
        </div>
        <span class="text-[10px] text-stone-400 font-mono font-semibold">${data.latency_ms} ms</span>
      </div>

      <div class="text-stone-800 leading-relaxed space-y-2 whitespace-pre-wrap">${formatAnswerText(data.answer)}</div>

      ${conflictsHtml}
      ${citationsHtml}
      ${explainHtml}
    </div>
  `;

  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;
  lucide.createIcons();
}

function formatAnswerText(text) {
  let formatted = escapeHtml(text);
  formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong class="text-stone-950 font-bold">$1</strong>');
  formatted = formatted.replace(/`([^`]+)`/g, '<code class="px-1.5 py-0.5 rounded bg-stone-100 text-stone-900 font-mono text-[11px] font-bold border border-stone-200">$1</code>');
  return formatted;
}

function appendErrorMessage(msg) {
  const stream = document.getElementById('chatStream');
  const div = document.createElement('div');
  div.className = "flex items-start gap-3";
  div.innerHTML = `
    <div class="w-9 h-9 rounded-xl bg-rose-50 border border-rose-200 flex items-center justify-center shrink-0">
      <i data-lucide="alert-octagon" class="w-4 h-4 text-rose-600"></i>
    </div>
    <div class="skin-surface rounded-2xl p-4 border border-rose-200 text-xs text-rose-950">
      <div class="font-bold mb-1">Execution Error</div>
      <p>${escapeHtml(msg)}</p>
    </div>
  `;
  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;
  lucide.createIcons();
}

// ----------------- PASSAGE INSPECTOR MODAL -----------------

function openPassageModal(citationId) {
  const cit = appState.currentCitations[citationId];
  if (!cit) return;

  const modal = document.getElementById('passageModal');
  document.getElementById('modalTitle').textContent = cit.doc_title;
  document.getElementById('modalContent').textContent = cit.snippet;
  document.getElementById('modalDocId').textContent = `Doc ID: ${cit.doc_id}`;
  document.getElementById('modalChunkId').textContent = `Chunk ID: ${cit.id}`;

  const badges = document.getElementById('modalBadges');
  badges.innerHTML = `
    <span class="px-2.5 py-0.5 rounded-full bg-orange-50 text-orange-800 border border-orange-200 font-mono text-[10px] font-bold">
      Similarity: ${(cit.similarity_score * 100).toFixed(1)}%
    </span>
    <span class="px-2.5 py-0.5 rounded-full bg-stone-100 text-stone-800 border border-stone-200 font-mono text-[10px] font-bold">
      Keyword: ${(cit.keyword_score * 100).toFixed(1)}%
    </span>
    <span class="px-2.5 py-0.5 rounded-full bg-[#FAF7F2] text-stone-700 text-[10px] font-semibold border border-stone-200">
      Section: ${escapeHtml(cit.section || 'General')}
    </span>
    <span class="px-2.5 py-0.5 rounded-full bg-[#FAF7F2] text-stone-700 text-[10px] font-semibold border border-stone-200">
      Page: ${cit.page_number}
    </span>
  `;

  modal.showModal();
}

// ----------------- KNOWLEDGE BASE -----------------

async function loadDocuments() {
  try {
    const res = await fetch('/api/documents');
    const docs = await res.json();
    appState.documents = docs;

    const container = document.getElementById('documentsListContainer');
    if (!container) return;

    if (docs.length === 0) {
      container.innerHTML = `<div class="col-span-2 text-center py-12 text-stone-500 text-xs">No documents uploaded. Click "Ingest New Document" above.</div>`;
      return;
    }

    container.innerHTML = docs.map(d => `
      <div class="skin-surface rounded-2xl p-5 shadow-2xs">
        <div class="flex items-start justify-between mb-2">
          <div>
            <h3 class="font-extrabold text-stone-950 text-sm">${escapeHtml(d.title)}</h3>
            <span class="text-[11px] text-stone-500 font-medium">${escapeHtml(d.metadata.author || 'Unknown')} • ${d.metadata.year || 2025}</span>
          </div>
          <span class="px-2.5 py-0.5 rounded-full bg-orange-50 text-orange-800 border border-orange-200 text-[10px] font-bold">
            ${d.chunk_count} Chunks
          </span>
        </div>
        <p class="text-xs text-stone-600 line-clamp-3 leading-relaxed mb-3">${escapeHtml(d.raw_text.substring(0, 200))}...</p>
        <div class="flex items-center justify-between pt-3 border-t border-stone-100 text-[10px] text-stone-500">
          <span>Category: <strong class="text-stone-800">${escapeHtml(d.metadata.category || 'General')}</strong></span>
          <span class="font-mono">ID: ${escapeHtml(d.id)}</span>
        </div>
      </div>
    `).join('');

    lucide.createIcons();
  } catch (err) {
    console.error('Failed to load documents:', err);
  }
}

function openUploadModal() {
  document.getElementById('uploadModal').showModal();
}

async function handleUploadSubmit(e) {
  e.preventDefault();
  const title = document.getElementById('upTitle').value.trim();
  const category = document.getElementById('upCategory').value.trim();
  const author = document.getElementById('upAuthor').value.trim();
  const year = document.getElementById('upYear').value;
  const file = document.getElementById('upFile').files[0];
  const textContent = document.getElementById('upText').value.trim();

  const formData = new FormData();
  formData.append('title', title);
  formData.append('category', category);
  formData.append('author', author);
  formData.append('year', year);
  if (file) formData.append('file', file);
  if (textContent) formData.append('text_content', textContent);

  const btn = document.getElementById('btnUploadSubmit');
  btn.disabled = true;
  btn.textContent = "Ingesting & Indexing...";

  try {
    const res = await fetch('/api/documents/upload', {
      method: 'POST',
      body: formData
    });
    const result = await res.json();
    if (result.success) {
      document.getElementById('uploadModal').close();
      await fetchStatus();
      await loadDocuments();
      alert(`Successfully ingested '${title}' into ${result.chunks_created} indexed chunks!`);
    } else {
      alert(`Upload failed: ${result.detail || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Upload error: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Ingest & Index";
  }
}

async function resetKnowledgeBase() {
  if (!confirm("Reset knowledge base to the default clean benchmark datasets?")) return;
  try {
    const res = await fetch('/api/documents/reset', { method: 'POST' });
    const data = await res.json();
    await fetchStatus();
    await loadDocuments();
    alert("Knowledge base reset to standard benchmark corpus.");
  } catch (err) {
    alert(`Reset error: ${err.message}`);
  }
}

// ----------------- CONFLICT RADAR LAB -----------------

function updateConflictLab(conflicts) {
  const container = document.getElementById('conflictLabResults');
  if (!container || !conflicts || conflicts.length === 0) return;

  container.innerHTML = `
    <div class="space-y-4">
      <div class="text-xs font-bold text-stone-900 uppercase tracking-wider mb-2">Detected Discrepancies in Latest Query</div>
      ${conflicts.map(cf => `
        <div class="skin-surface p-5 rounded-2xl shadow-xs">
          <div class="flex items-center justify-between mb-3">
            <h4 class="font-extrabold text-stone-900 text-sm flex items-center gap-2">
              <i data-lucide="git-commit" class="w-4 h-4 text-orange-500"></i> ${escapeHtml(cf.subject)}
            </h4>
            <span class="px-2.5 py-0.5 rounded-full bg-orange-50 text-orange-800 font-bold text-[10px] uppercase border border-orange-200">
              ${escapeHtml(cf.discrepancy_type)}
            </span>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3 text-xs">
            <div class="p-3.5 rounded-xl bg-[#FAF7F2] border border-stone-200">
              <span class="text-stone-500 text-[10px] block mb-1 font-bold">Source 1: <strong class="text-stone-800">${escapeHtml(cf.source_a)}</strong></span>
              <p class="font-mono text-stone-900 font-semibold text-[11px]">${escapeHtml(cf.claim_a)}</p>
            </div>
            <div class="p-3.5 rounded-xl bg-[#FAF7F2] border border-stone-200">
              <span class="text-stone-500 text-[10px] block mb-1 font-bold">Source 2: <strong class="text-stone-800">${escapeHtml(cf.source_b)}</strong></span>
              <p class="font-mono text-stone-900 font-semibold text-[11px]">${escapeHtml(cf.claim_b)}</p>
            </div>
          </div>
          <div class="p-3.5 rounded-xl bg-white border border-stone-200 text-xs text-stone-700 leading-relaxed shadow-2xs">
            <strong class="text-stone-900 font-bold">Resolution Analysis:</strong> ${escapeHtml(cf.explanation)}
          </div>
        </div>
      `).join('')}
    </div>
  `;
  lucide.createIcons();
}

// ----------------- BENCHMARK SUITE -----------------

async function runFullBenchmark() {
  const btn = document.getElementById('btnRunBenchmark');
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader" class="w-4 h-4 animate-spin text-white"></i> Running Test Matrix...`;
  lucide.createIcons();

  try {
    const res = await fetch('/api/eval/run', { method: 'POST' });
    const summary = await res.json();
    appState.evalResults = summary;

    // Update KPI summary cards
    document.getElementById('evalHitRate').textContent = `${(summary.hit_rate * 100).toFixed(0)}%`;
    document.getElementById('evalMRR').textContent = summary.mrr.toFixed(2);
    document.getElementById('evalPrecision').textContent = summary.precision_at_3.toFixed(2);
    document.getElementById('evalConflictAcc').textContent = `${(summary.conflict_detection_accuracy * 100).toFixed(0)}%`;
    document.getElementById('evalAbstentionAcc').textContent = `${(summary.abstention_accuracy * 100).toFixed(0)}%`;
    document.getElementById('evalLatency').textContent = `${summary.avg_latency_ms.toFixed(0)} ms`;

    // Render table rows
    const tbody = document.getElementById('evalTableBody');
    tbody.innerHTML = summary.results.map(r => `
      <tr class="hover:bg-stone-50/80">
        <td class="px-4 py-3 font-bold text-stone-900">${escapeHtml(r.test_id)}</td>
        <td class="px-4 py-3 text-stone-800 font-sans max-w-xs truncate font-medium" title="${escapeHtml(r.query)}">${escapeHtml(r.query)}</td>
        <td class="px-4 py-3 text-stone-500 font-sans">${r.expected_titles.length ? escapeHtml(r.expected_titles.join(', ')) : '<span class="text-stone-400">[None / Abstain]</span>'}</td>
        <td class="px-4 py-3">
          ${r.hit 
            ? `<span class="px-2 py-0.5 rounded bg-orange-50 text-orange-800 border border-orange-200 font-bold text-[10px]">HIT (RR: ${r.reciprocal_rank})</span>` 
            : `<span class="px-2 py-0.5 rounded bg-stone-100 text-stone-700 font-bold text-[10px]">MISS</span>`}
        </td>
        <td class="px-4 py-3">${r.conflict_detected ? '<span class="text-orange-600 font-bold">YES</span>' : '<span class="text-stone-400">NO</span>'}</td>
        <td class="px-4 py-3">${r.abstained ? '<span class="text-stone-900 font-bold">ABSTAINED</span>' : '<span class="text-stone-400">ANSWERED</span>'}</td>
        <td class="px-4 py-3 text-stone-900 font-bold">${r.groundedness_score}%</td>
        <td class="px-4 py-3 text-stone-500 font-semibold">${r.latency_ms} ms</td>
      </tr>
    `).join('');
  } catch (err) {
    alert(`Benchmark execution failed: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="play-circle" class="w-4 h-4"></i> Run Full Benchmark Suite`;
    lucide.createIcons();
  }
}

// ----------------- CONFIG & INTEGRATION -----------------

async function handleMongoConfigSubmit(e) {
  e.preventDefault();
  const uri = document.getElementById('mongoUriInput').value.trim();
  const db = document.getElementById('mongoDbInput').value.trim();
  const coll = document.getElementById('mongoCollInput').value.trim();
  const idx = document.getElementById('mongoIndexInput').value.trim();

  try {
    const res = await fetch('/api/config/mongodb', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uri, database: db, collection: coll, index_name: idx })
    });
    const result = await res.json();
    alert(result.message);
    await fetchStatus();
  } catch (err) {
    alert(`Connection error: ${err.message}`);
  }
}

async function handleGeminiKeySubmit(e) {
  e.preventDefault();
  const key = document.getElementById('geminiKeyInput').value.trim();
  try {
    const res = await fetch('/api/config/gemini', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: key })
    });
    const result = await res.json();
    alert(`Credentials updated! Model vector dimension: ${result.embedding_dim}`);
    await fetchStatus();
  } catch (err) {
    alert(`Configuration error: ${err.message}`);
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
