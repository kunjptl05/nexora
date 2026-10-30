// Nexora Frontend Controller — Autonomous Document Intelligence & Evidence Verification

let appState = {
  activeTab: 'chat',
  status: null,
  documents: [],
  selectedScopeDocIds: new Set(),
  evalResults: null,
  currentCitations: {},
  latestQueryResult: null,
  kbCategoryFilter: 'all',
  activeCitationId: null
};

document.addEventListener('DOMContentLoaded', () => {
  initApp();
});

async function initApp() {
  await fetchStatus();
  await loadDocuments();
  initDefaultConflictDashboard();
  lucide.createIcons();
}

// ----------------- SYSTEM STATUS & HEALTH -----------------

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    appState.status = data;
    
    // Update sidebar indicator
    const sidebarStatus = document.getElementById('sidebarStatusText');
    const sidebarStats = document.getElementById('sidebarDocStats');
    const navDocCount = document.getElementById('navDocCountPill');
    const scopeDocBadge = document.getElementById('scopeDocBadge');

    if (data.mongodb_connected) {
      sidebarStatus.textContent = "Cloud Cluster Connected";
      sidebarStatus.className = "font-bold text-[11px] text-orange-700";
    } else {
      sidebarStatus.textContent = "Neural Engine Active";
      sidebarStatus.className = "font-bold text-[11px] text-stone-800";
    }

    if (sidebarStats) {
      sidebarStats.textContent = `${data.total_documents} docs · ${data.total_chunks} chunks`;
    }
    if (navDocCount) navDocCount.textContent = data.total_documents;
    if (scopeDocBadge) scopeDocBadge.textContent = data.total_documents;
  } catch (err) {
    console.error('Failed to fetch status:', err);
  }
}

// ----------------- SAAS NAVIGATION CONTROLLER -----------------

function switchTab(tabId) {
  appState.activeTab = tabId;
  const tabs = ['chat', 'docs', 'conflict', 'eval', 'arch'];
  
  const titles = {
    chat: {
      title: "Workspace · Cross-Document Intelligence",
      icon: "message-square",
      subtext: "3-Panel Synthesis, Verification & Conflict Radar"
    },
    docs: {
      title: "Knowledge Base · Document Repository",
      icon: "folder-kanban",
      subtext: "Indexed Sources, Chunk Boundaries & Vector Embeddings"
    },
    conflict: {
      title: "Conflict Radar · Claim Reconciliation",
      icon: "git-compare",
      subtext: "Autonomous Multi-Source Discrepancy & Version Delta Radar"
    },
    eval: {
      title: "Benchmark Suite · Retrieval & Fidelity",
      icon: "bar-chart-2",
      subtext: "Hit Rate@3, MRR, Precision, Conflict Accuracy & Zero-Hallucination"
    },
    arch: {
      title: "Engine & Specs · Architecture",
      icon: "sliders",
      subtext: "Cluster Connections, Schema Definition & Model Credentials"
    }
  };

  // Update Main View Title Header
  const viewTitle = document.getElementById('currentViewTitle');
  const viewSubtext = document.getElementById('currentViewSubtext');
  if (viewTitle && titles[tabId]) {
    viewTitle.innerHTML = `<i data-lucide="${titles[tabId].icon}" class="w-4 h-4 text-orange-500"></i><span>${titles[tabId].title}</span>`;
    viewSubtext.textContent = titles[tabId].subtext;
  }

  // Update Sidebar Active Styles
  tabs.forEach(t => {
    const section = document.getElementById(`tab-${t}`);
    const navBtn = document.getElementById(`navBtn-${t}`);
    if (!section || !navBtn) return;

    if (t === tabId) {
      section.classList.remove('hidden');
      navBtn.className = "w-full px-3.5 py-2.5 rounded-xl text-xs font-bold flex items-center justify-between transition-all bg-gradient-to-r from-orange-500 to-rose-500 text-white shadow-xs";
    } else {
      section.classList.add('hidden');
      navBtn.className = "w-full px-3.5 py-2.5 rounded-xl text-xs font-medium flex items-center justify-between transition-all text-stone-600 hover:text-stone-950 hover:bg-[#FAF7F2]";
    }
  });

  if (tabId === 'docs') loadDocuments();
  if (tabId === 'eval' && !appState.evalResults) runFullBenchmark();
  lucide.createIcons();
}

// ----------------- WORKSPACE PANEL A: DOCUMENT SCOPE -----------------

function renderScopeChecklist() {
  const container = document.getElementById('scopeDocsList');
  if (!container) return;

  if (appState.documents.length === 0) {
    container.innerHTML = `<div class="p-4 text-center text-stone-400 text-[11px]">No documents indexed.</div>`;
    return;
  }

  // If first run, select all by default
  if (appState.selectedScopeDocIds.size === 0) {
    appState.documents.forEach(d => appState.selectedScopeDocIds.add(d.id));
  }

  const query = (document.getElementById('scopeSearchInput')?.value || '').toLowerCase();
  const filtered = appState.documents.filter(d => 
    d.title.toLowerCase().includes(query) || (d.metadata.category || '').toLowerCase().includes(query)
  );

  container.innerHTML = filtered.map(d => {
    const isChecked = appState.selectedScopeDocIds.has(d.id);
    return `
      <label class="p-2 rounded-xl bg-white border border-[#E8DFCFC] hover:border-orange-300 flex items-start gap-2.5 cursor-pointer transition-all shadow-2xs group">
        <input type="checkbox" onchange="toggleDocScope('${d.id}')" ${isChecked ? 'checked' : ''} 
               class="mt-0.5 rounded border-stone-300 text-orange-500 focus:ring-0">
        <div class="flex-1 min-w-0">
          <div class="flex items-center justify-between gap-1 mb-0.5">
            <span class="font-bold text-[11px] text-stone-900 truncate group-hover:text-orange-600">${escapeHtml(d.title)}</span>
            <span class="text-[9px] font-bold px-1.5 py-0.2 rounded bg-stone-100 text-stone-600 border border-stone-200 shrink-0">${d.metadata.year || 2025}</span>
          </div>
          <div class="flex items-center justify-between text-[10px] text-stone-500 font-medium">
            <span class="truncate">${escapeHtml(d.metadata.category || 'General')}</span>
            <span class="font-mono text-stone-400">${d.chunk_count} chk</span>
          </div>
        </div>
      </label>
    `;
  }).join('');

  updateScopeCountDisplay();
  lucide.createIcons();
}

function toggleDocScope(docId) {
  if (appState.selectedScopeDocIds.has(docId)) {
    appState.selectedScopeDocIds.delete(docId);
  } else {
    appState.selectedScopeDocIds.add(docId);
  }
  updateScopeCountDisplay();
}

function toggleAllScope() {
  const btn = document.getElementById('btnSelectAllScope');
  if (appState.selectedScopeDocIds.size === appState.documents.length) {
    appState.selectedScopeDocIds.clear();
    if (btn) btn.textContent = "All";
  } else {
    appState.documents.forEach(d => appState.selectedScopeDocIds.add(d.id));
    if (btn) btn.textContent = "Clear";
  }
  renderScopeChecklist();
}

function updateScopeCountDisplay() {
  const text = document.getElementById('selectedScopeCountText');
  const btn = document.getElementById('btnSelectAllScope');
  const count = appState.selectedScopeDocIds.size;
  const total = appState.documents.length;

  if (text) text.textContent = `${count} of ${total} active`;
  if (btn) btn.textContent = count === total ? "Clear" : "All";
}

function filterScopeDocs() {
  renderScopeChecklist();
}

// ----------------- WORKSPACE PANEL B: CHAT & SYNTHESIS -----------------

function runSamplePrompt(promptText) {
  switchTab('chat');
  const input = document.getElementById('queryInput');
  input.value = promptText;
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

  // Filter doc_ids if some are selected
  let docIdsFilter = null;
  if (appState.selectedScopeDocIds.size > 0 && appState.selectedScopeDocIds.size < appState.documents.length) {
    docIdsFilter = Array.from(appState.selectedScopeDocIds);
  }

  // Append user message
  appendUserMessage(question);
  input.value = '';
  sendBtn.disabled = true;

  // Append loading indicator
  const loadingId = appendLoadingIndicator();

  try {
    const res = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: question,
        use_hybrid: useHybrid,
        top_k: topK,
        filters: docIdsFilter ? { doc_ids: docIdsFilter } : null
      })
    });
    const data = await res.json();
    appState.latestQueryResult = data;

    removeLoadingIndicator(loadingId);
    appendAssistantResponse(data);
    renderEvidenceInspector(data.citations);
    
    if (data.conflicts && data.conflicts.length > 0) {
      renderConflictDashboardCards(data.conflicts);
    }
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
    <div class="max-w-xl bg-white border border-[#E8DFCFC] rounded-2xl p-4 text-xs text-stone-900 shadow-2xs">
      <div class="flex items-center gap-1.5 mb-1 text-[11px] font-bold text-orange-600">
        <i data-lucide="user" class="w-3.5 h-3.5"></i> User Query
      </div>
      <p class="leading-relaxed font-semibold text-stone-900">${escapeHtml(text)}</p>
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
  div.className = "flex items-start gap-3 max-w-4xl mx-auto";
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
  div.className = "flex items-start gap-3 max-w-4xl mx-auto";

  // Store citations in memory
  if (data.citations) {
    data.citations.forEach(c => {
      appState.currentCitations[c.id] = c;
    });
  }

  // Format conflicts block
  let conflictsHtml = '';
  if (data.conflicts && data.conflicts.length > 0) {
    conflictsHtml = `
      <div class="mt-4 p-4 rounded-xl bg-orange-50/90 border border-orange-200 text-stone-900">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center gap-2 font-extrabold text-xs text-orange-800">
            <i data-lucide="alert-triangle" class="w-4 h-4 text-orange-600"></i>
            <span>Cross-Document Conflict Radar (${data.conflicts.length} Discrepancies Caught)</span>
          </div>
          <button onclick="switchTab('conflict')" class="text-[10px] font-bold text-orange-700 hover:text-orange-900 underline flex items-center gap-1">
            <span>Open in Conflict Dashboard</span>
            <i data-lucide="arrow-right" class="w-3 h-3"></i>
          </button>
        </div>
        <div class="space-y-2.5">
          ${data.conflicts.map(cf => `
            <div class="p-3.5 rounded-xl bg-white border border-orange-200 text-[11px] shadow-2xs">
              <div class="font-extrabold text-stone-900 mb-1.5 flex items-center justify-between">
                <span>${escapeHtml(cf.subject)}</span>
                <span class="px-2 py-0.5 bg-orange-100 text-orange-800 rounded text-[9px] uppercase font-extrabold border border-orange-200">${escapeHtml(cf.discrepancy_type)}</span>
              </div>
              
              <!-- Side-by-Side Comparison -->
              <div class="grid grid-cols-1 md:grid-cols-2 gap-2 my-2 text-stone-800">
                <div class="p-2.5 rounded-lg bg-[#FAF7F2] border border-stone-200">
                  <div class="flex items-center justify-between text-[10px] text-stone-500 font-bold mb-1">
                    <span>${escapeHtml(cf.source_a)}</span>
                    ${cf.value_a ? `<span class="px-1.5 py-0.2 rounded bg-stone-200 text-stone-800 font-mono font-bold">${escapeHtml(cf.value_a)}</span>` : ''}
                  </div>
                  <p class="font-semibold text-stone-900 text-[11px]">${escapeHtml(cf.claim_a)}</p>
                </div>

                <div class="p-2.5 rounded-lg bg-[#FAF7F2] border border-stone-200">
                  <div class="flex items-center justify-between text-[10px] text-stone-500 font-bold mb-1">
                    <span>${escapeHtml(cf.source_b)}</span>
                    ${cf.value_b ? `<span class="px-1.5 py-0.2 rounded bg-orange-100 text-orange-900 font-mono font-bold border border-orange-200">${escapeHtml(cf.value_b)}</span>` : ''}
                  </div>
                  <p class="font-semibold text-stone-900 text-[11px]">${escapeHtml(cf.claim_b)}</p>
                </div>
              </div>

              ${cf.delta ? `
                <div class="mb-2 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-orange-100 text-orange-900 font-bold text-[10px] border border-orange-200">
                  <i data-lucide="diff" class="w-3 h-3"></i>
                  <span>Calculated Delta: ${escapeHtml(cf.delta)}</span>
                </div>
              ` : ''}

              <p class="text-stone-600 leading-normal italic font-medium">${escapeHtml(cf.explanation)}</p>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  // Inline citations pills under synthesis
  let citationsPillsHtml = '';
  if (data.citations && data.citations.length > 0) {
    citationsPillsHtml = `
      <div class="mt-4 pt-3 border-t border-stone-100 flex flex-wrap items-center gap-2">
        <span class="text-[10px] font-bold text-stone-400 uppercase tracking-wider flex items-center gap-1">
          <i data-lucide="link" class="w-3 h-3 text-orange-500"></i> Citations:
        </span>
        ${data.citations.map((c, i) => `
          <button onclick="highlightCitationInPanel('${c.id}')" 
                  class="px-2.5 py-1 rounded-lg bg-[#FAF7F2] hover:bg-orange-50 border border-stone-200 hover:border-orange-300 text-[11px] font-bold text-stone-800 hover:text-orange-900 flex items-center gap-1.5 transition-all shadow-2xs">
            <span class="w-4 h-4 rounded-full bg-orange-100 text-orange-800 text-[9px] flex items-center justify-center font-bold">${i + 1}</span>
            <span class="truncate max-w-[140px]">${escapeHtml(c.doc_title)}</span>
            <span class="text-orange-700 font-mono text-[10px]">p.${c.page_number}</span>
          </button>
        `).join('')}
      </div>
    `;
  }

  // Grounded badge
  const groundedBadge = data.abstained 
    ? `<span class="px-2.5 py-0.5 rounded-full bg-rose-50 text-rose-800 border border-rose-200 text-[10px] font-bold flex items-center gap-1"><i data-lucide="shield-alert" class="w-3 h-3"></i> Safe Abstention</span>`
    : `<span class="px-2.5 py-0.5 rounded-full bg-orange-50 text-orange-800 border border-orange-200 text-[10px] font-bold flex items-center gap-1"><i data-lucide="shield-check" class="w-3 h-3 text-orange-600"></i> ${data.groundedness_score}% Grounded</span>`;

  div.innerHTML = `
    <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-orange-500 to-rose-500 flex items-center justify-center shrink-0 shadow-xs text-white">
      <i data-lucide="sparkles" class="w-4 h-4"></i>
    </div>
    <div class="flex-1 skin-surface rounded-2xl p-5 shadow-xs text-xs">
      <div class="flex items-center justify-between mb-3 border-b border-stone-100 pb-2.5">
        <div class="flex items-center gap-2">
          <span class="font-extrabold text-stone-950 text-sm">Nexora Synthesis</span>
          ${groundedBadge}
        </div>
        <div class="flex items-center gap-2">
          <button onclick="exportCurrentReport()" title="Export this verified synthesis as Markdown report" 
                  class="p-1.5 rounded-lg hover:bg-stone-100 text-stone-500 hover:text-stone-800 transition-colors">
            <i data-lucide="download" class="w-3.5 h-3.5"></i>
          </button>
          <span class="text-[10px] text-stone-400 font-mono font-semibold">${data.latency_ms} ms</span>
        </div>
      </div>

      <div class="text-stone-800 leading-relaxed space-y-2 whitespace-pre-wrap">${formatAnswerText(data.answer)}</div>

      ${conflictsHtml}
      ${citationsPillsHtml}
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
  div.className = "flex items-start gap-3 max-w-4xl mx-auto";
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

// ----------------- WORKSPACE PANEL C: EVIDENCE INSPECTOR -----------------

function renderEvidenceInspector(citations) {
  const container = document.getElementById('evidencePanelContent');
  const badge = document.getElementById('evidenceCountBadge');
  if (!container) return;

  if (!citations || citations.length === 0) {
    if (badge) badge.textContent = "0 Citations";
    container.innerHTML = `
      <div class="text-center py-16 px-4">
        <div class="w-12 h-12 rounded-2xl bg-stone-100 flex items-center justify-center mx-auto mb-3 text-stone-400">
          <i data-lucide="shield-check" class="w-6 h-6"></i>
        </div>
        <h4 class="font-bold text-stone-700 text-xs mb-1">Safe Abstention / Zero Match</h4>
        <p class="text-[11px] text-stone-500 leading-relaxed">
          No passages met the minimum relevance threshold for this query. Nexora safely refused to generate hallucinated claims.
        </p>
      </div>
    `;
    lucide.createIcons();
    return;
  }

  if (badge) badge.textContent = `${citations.length} Citations`;

  container.innerHTML = `
    <div class="space-y-3">
      <div class="text-[10px] font-bold text-stone-400 uppercase tracking-wider mb-1">Click passage to inspect exact text</div>
      ${citations.map((c, i) => {
        const isSelected = appState.activeCitationId === c.id;
        return `
          <div id="citation_card_${c.id}" onclick="selectCitation('${c.id}')" 
               class="p-3.5 rounded-xl bg-white border ${isSelected ? 'border-orange-500 ring-2 ring-orange-200' : 'border-stone-200 hover:border-orange-300'} cursor-pointer transition-all text-xs shadow-2xs group">
            <div class="flex items-center justify-between mb-1.5">
              <div class="flex items-center gap-1.5 truncate">
                <span class="w-4 h-4 rounded-full bg-orange-100 text-orange-800 text-[9px] flex items-center justify-center font-bold shrink-0">${i + 1}</span>
                <span class="font-extrabold text-stone-900 truncate group-hover:text-orange-600 text-[11px]">${escapeHtml(c.doc_title)}</span>
              </div>
              <span class="px-1.5 py-0.5 rounded bg-orange-50 text-[9px] text-orange-800 font-mono font-bold border border-orange-200 shrink-0">${(c.similarity_score * 100).toFixed(0)}% Match</span>
            </div>
            
            <p class="text-stone-600 line-clamp-3 leading-relaxed text-[11px]">${escapeHtml(c.snippet)}</p>

            <div class="flex items-center justify-between pt-2 mt-2 border-t border-stone-100 text-[10px] text-stone-400 font-semibold">
              <span class="truncate">§ ${escapeHtml(c.section || 'General')}</span>
              <span class="font-mono text-stone-600">Page ${c.page_number}</span>
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;

  lucide.createIcons();
}

function selectCitation(citationId) {
  appState.activeCitationId = citationId;
  openPassageModal(citationId);
}

function highlightCitationInPanel(citationId) {
  appState.activeCitationId = citationId;
  const card = document.getElementById(`citation_card_${citationId}`);
  if (card) {
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    card.classList.add('ring-2', 'ring-orange-400');
    setTimeout(() => card.classList.remove('ring-2', 'ring-orange-400'), 2000);
  }
  openPassageModal(citationId);
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
      Semantic Match: ${(cit.similarity_score * 100).toFixed(1)}%
    </span>
    <span class="px-2.5 py-0.5 rounded-full bg-stone-100 text-stone-800 border border-stone-200 font-mono text-[10px] font-bold">
      Keyword Overlap: ${(cit.keyword_score * 100).toFixed(1)}%
    </span>
    <span class="px-2.5 py-0.5 rounded-full bg-[#FAF7F2] text-stone-700 text-[10px] font-semibold border border-stone-200">
      Section: ${escapeHtml(cit.section || 'General')}
    </span>
    <span class="px-2.5 py-0.5 rounded-full bg-[#FAF7F2] text-stone-700 text-[10px] font-semibold border border-stone-200">
      Page ${cit.page_number}
    </span>
  `;

  modal.showModal();
}

// ----------------- CONFLICT INTELLIGENCE DASHBOARD (CENTERPIECE) -----------------

function initDefaultConflictDashboard() {
  // Pre-seed the Conflict Dashboard with the iconic Solar Policy 2023 vs 2025 quantitative deltas
  const defaultShowcaseConflicts = [
    {
      subject: "Minimum Solar Panel Efficiency Mandate",
      claim_a: "Section 4.1: all approved monocrystalline photovoltaic modules must achieve a minimum tested solar panel efficiency of 18.0%.",
      source_a: "Solar Policy Framework 2023 (p.1)",
      value_a: "18.0%",
      claim_b: "Section 3.2: raises the minimum required solar panel efficiency standard to 22.0%. Panels falling below this revised threshold are prohibited.",
      source_b: "CleanTech Modernization Act 2025 (p.1)",
      value_b: "22.0%",
      delta: "+4.0% Net Increase",
      unit: "%",
      discrepancy_type: "quantitative",
      severity: "high",
      explanation: "Statutory efficiency standard was amended upward from 18.0% in 2023 to 22.0% in the 2025 Modernization Act to promote tandem cells."
    },
    {
      subject: "Mandatory Manufacturer Warranty Period",
      claim_a: "Section 5: Installers must offer a minimum mandatory manufacturer warranty of 3 years covering inverters, racking systems, and panel output.",
      source_a: "Solar Policy Framework 2023 (p.1)",
      value_a: "3 years",
      claim_b: "Section 4: Recognising advancements, the mandatory equipment warranty period is extended to 5 years (superseding the former 3-year term).",
      source_b: "CleanTech Modernization Act 2025 (p.1)",
      value_b: "5 years",
      delta: "+2 Years Warranty",
      unit: "years",
      discrepancy_type: "policy_revision",
      severity: "high",
      explanation: "Manufacturer warranty obligations were extended from 3 years (2023 baseline) to 5 years (2025 Modernization Act), expanding to BMS controllers."
    },
    {
      subject: "Direct Residential Clean Energy Rebate Cap",
      claim_a: "Section 6.2: Qualifying households are eligible for a direct government subsidy rebate of $5,000 for installations exceeding 4.5 kW capacity.",
      source_a: "Solar Policy Framework 2023 (p.1)",
      value_a: "$5,000",
      claim_b: "Section 5: Direct residential subsidy rebate is now capped at $3,500 per installation (revised downward from $5,000 with automatic portal approval).",
      source_b: "CleanTech Modernization Act 2025 (p.1)",
      value_b: "$3,500",
      delta: "-$1,500 Budget Realignment",
      unit: "$",
      discrepancy_type: "quantitative",
      severity: "medium",
      explanation: "Subsidy funding per household was reduced by $1,500 in 2025 due to declining panel hardware costs, offset by instant automated portal approvals."
    }
  ];

  renderConflictDashboardCards(defaultShowcaseConflicts);
}

function renderConflictDashboardCards(conflicts) {
  const container = document.getElementById('conflictDashboardCards');
  if (!container || !conflicts) return;

  container.innerHTML = `
    <div class="space-y-4">
      <div class="flex items-center justify-between">
        <h3 class="text-xs font-extrabold text-stone-900 uppercase tracking-wider flex items-center gap-1.5">
          <i data-lucide="git-commit" class="w-4 h-4 text-orange-500"></i>
          <span>Reconciled Discrepancies & Version Deltas (${conflicts.length})</span>
        </h3>
        <span class="text-[10px] text-stone-500 font-semibold">Side-by-Side Source Citation Comparison</span>
      </div>

      ${conflicts.map(cf => `
        <div class="skin-surface p-6 rounded-2xl shadow-xs border border-[#E8DFCFC]">
          <!-- Card Header -->
          <div class="flex flex-col md:flex-row md:items-center justify-between gap-2 mb-4 pb-3 border-b border-stone-100">
            <div>
              <div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-orange-500"></span>
                <h4 class="font-extrabold text-stone-950 text-sm">${escapeHtml(cf.subject)}</h4>
              </div>
              <span class="text-[11px] text-stone-500 font-medium">Contrasting evidence detected across indexed documents</span>
            </div>

            <div class="flex items-center gap-2">
              <span class="px-2.5 py-0.5 rounded-full bg-orange-50 text-orange-800 text-[10px] uppercase font-extrabold border border-orange-200">
                ${escapeHtml(cf.discrepancy_type)}
              </span>
              ${cf.delta ? `
                <span class="px-3 py-0.5 rounded-full bg-orange-100 text-orange-950 text-[11px] font-extrabold border border-orange-300 font-mono shadow-2xs">
                  ${escapeHtml(cf.delta)}
                </span>
              ` : ''}
            </div>
          </div>

          <!-- Side-by-Side Comparison Columns -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <!-- Source A Card -->
            <div class="p-4 rounded-xl bg-[#FAF7F2] border border-[#E2D8C6] flex flex-col justify-between">
              <div>
                <div class="flex items-center justify-between text-[11px] font-bold text-stone-600 mb-2">
                  <span class="flex items-center gap-1 text-stone-500">
                    <i data-lucide="file-text" class="w-3.5 h-3.5 text-stone-400"></i>
                    <span>${escapeHtml(cf.source_a)}</span>
                  </span>
                  <span class="px-2 py-0.5 rounded bg-white text-stone-800 border border-stone-200 text-[10px] font-mono font-bold">Prior Baseline</span>
                </div>
                ${cf.value_a ? `
                  <div class="text-xl font-extrabold text-stone-900 font-mono mb-2">${escapeHtml(cf.value_a)}</div>
                ` : ''}
                <p class="text-xs text-stone-700 leading-relaxed font-medium bg-white p-3 rounded-lg border border-stone-200">${escapeHtml(cf.claim_a)}</p>
              </div>
            </div>

            <!-- Source B Card -->
            <div class="p-4 rounded-xl bg-orange-50/60 border border-orange-200 flex flex-col justify-between">
              <div>
                <div class="flex items-center justify-between text-[11px] font-bold text-orange-900 mb-2">
                  <span class="flex items-center gap-1 text-orange-800">
                    <i data-lucide="file-check" class="w-3.5 h-3.5 text-orange-600"></i>
                    <span>${escapeHtml(cf.source_b)}</span>
                  </span>
                  <span class="px-2 py-0.5 rounded bg-orange-100 text-orange-950 border border-orange-300 text-[10px] font-mono font-bold">Updated Amendment</span>
                </div>
                ${cf.value_b ? `
                  <div class="text-xl font-extrabold text-orange-900 font-mono mb-2">${escapeHtml(cf.value_b)}</div>
                ` : ''}
                <p class="text-xs text-stone-700 leading-relaxed font-medium bg-white p-3 rounded-lg border border-orange-200">${escapeHtml(cf.claim_b)}</p>
              </div>
            </div>
          </div>

          <!-- Bottom Reconciliation Analysis -->
          <div class="p-3.5 rounded-xl bg-white border border-stone-200 flex items-start gap-2.5 text-xs text-stone-700 shadow-2xs">
            <i data-lucide="info" class="w-4 h-4 text-orange-500 shrink-0 mt-0.5"></i>
            <div>
              <strong class="text-stone-900 font-bold">Reconciliation Analysis:</strong> ${escapeHtml(cf.explanation)}
            </div>
          </div>
        </div>
      `).join('')}
    </div>
  `;

  lucide.createIcons();
}

// ----------------- KNOWLEDGE BASE CONTROLLER -----------------

async function loadDocuments() {
  try {
    const res = await fetch('/api/documents');
    const docs = await res.json();
    appState.documents = docs;

    renderScopeChecklist();
    renderKnowledgeBaseDocs();
  } catch (err) {
    console.error('Failed to load documents:', err);
  }
}

function renderKnowledgeBaseDocs() {
  const container = document.getElementById('documentsListContainer');
  if (!container) return;

  const search = (document.getElementById('kbSearchInput')?.value || '').toLowerCase();
  const catFilter = appState.kbCategoryFilter;

  let filtered = appState.documents.filter(d => {
    const matchesSearch = d.title.toLowerCase().includes(search) || 
                          d.raw_text.toLowerCase().includes(search) ||
                          (d.metadata.author || '').toLowerCase().includes(search);
    const matchesCat = catFilter === 'all' || (d.metadata.category || '') === catFilter;
    return matchesSearch && matchesCat;
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="col-span-2 text-center py-16 bg-white rounded-2xl border border-stone-200 p-8">
        <i data-lucide="file-question" class="w-8 h-8 text-stone-400 mx-auto mb-2"></i>
        <h4 class="font-bold text-stone-800 text-xs mb-1">No documents match filter criteria</h4>
        <p class="text-stone-500 text-[11px] mb-4">Try clearing your search query or uploading a new file.</p>
        <button onclick="openUploadModal()" class="px-4 py-2 bg-gradient-to-r from-orange-500 to-rose-500 text-white font-bold rounded-xl text-xs shadow-xs">
          + Ingest New Document
        </button>
      </div>
    `;
    lucide.createIcons();
    return;
  }

  container.innerHTML = filtered.map(d => {
    const sizeKb = d.metadata.file_size_bytes 
      ? (d.metadata.file_size_bytes / 1024).toFixed(1) + " KB"
      : ((d.raw_text.length * 1.2) / 1024).toFixed(1) + " KB";

    return `
      <div class="skin-surface rounded-2xl p-5 shadow-xs flex flex-col justify-between">
        <div>
          <div class="flex items-start justify-between gap-2 mb-2">
            <div>
              <h3 class="font-extrabold text-stone-950 text-sm mb-0.5">${escapeHtml(d.title)}</h3>
              <span class="text-[11px] text-stone-500 font-medium">${escapeHtml(d.metadata.author || 'Unknown')} • ${d.metadata.year || 2025}</span>
            </div>
            <span class="px-2.5 py-0.5 rounded-full bg-orange-50 text-orange-800 border border-orange-200 text-[10px] font-bold shrink-0">
              ${d.chunk_count} Chunks
            </span>
          </div>

          <p class="text-xs text-stone-600 line-clamp-3 leading-relaxed mb-4 font-mono text-[11px] bg-[#FAF7F2] p-2.5 rounded-xl border border-stone-200">
            ${escapeHtml(d.raw_text.substring(0, 180))}...
          </p>
        </div>

        <div>
          <div class="flex items-center justify-between text-[11px] text-stone-500 mb-3 pt-2 border-t border-stone-100 font-medium">
            <span>Category: <strong class="text-stone-900">${escapeHtml(d.metadata.category || 'General')}</strong></span>
            <span>Size: <strong class="text-stone-800 font-mono">${sizeKb}</strong></span>
          </div>

          <div class="flex items-center justify-between pt-1">
            <span class="text-[10px] font-mono text-stone-400">ID: ${escapeHtml(d.id)}</span>
            <div class="flex items-center gap-2">
              <button onclick="deleteDocument('${d.id}', '${escapeHtml(d.title)}')" 
                      class="px-2.5 py-1 text-rose-700 hover:bg-rose-50 border border-rose-200 rounded-lg text-[11px] font-bold flex items-center gap-1 transition-colors">
                <i data-lucide="trash-2" class="w-3 h-3 text-rose-600"></i>
                <span>Delete</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  }).join('');

  lucide.createIcons();
}

function setKbCategoryFilter(category) {
  appState.kbCategoryFilter = category;
  
  // Update category button styles
  const buttons = document.querySelectorAll('.kb-cat-btn');
  buttons.forEach(btn => {
    if (btn.textContent.trim().toLowerCase() === category.toLowerCase() || (category === 'all' && btn.textContent.trim() === 'All')) {
      btn.className = "kb-cat-btn px-3 py-1 rounded-lg text-[11px] font-bold bg-orange-50 text-orange-800 border border-orange-200";
    } else {
      btn.className = "kb-cat-btn px-3 py-1 rounded-lg text-[11px] font-medium text-stone-600 hover:bg-stone-100";
    }
  });

  renderKnowledgeBaseDocs();
}

function filterKnowledgeBaseDocs() {
  renderKnowledgeBaseDocs();
}

async function deleteDocument(docId, title) {
  if (!confirm(`Are you sure you want to delete '${title}' and its associated vector chunks?`)) return;

  try {
    const res = await fetch(`/api/documents/${docId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
      appState.selectedScopeDocIds.delete(docId);
      await fetchStatus();
      await loadDocuments();
    } else {
      alert(`Deletion failed: ${data.detail || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Error deleting document: ${err.message}`);
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

  if (file && file.size > 25 * 1024 * 1024) {
    alert("File exceeds maximum allowed upload limit of 25MB.");
    return;
  }

  const formData = new FormData();
  formData.append('title', title);
  formData.append('category', category);
  formData.append('author', author);
  formData.append('year', year);
  if (file) formData.append('file', file);
  if (textContent) formData.append('text_content', textContent);

  const btn = document.getElementById('btnUploadSubmit');
  btn.disabled = true;
  btn.textContent = "Ingesting & Chunking...";

  try {
    const res = await fetch('/api/documents/upload', {
      method: 'POST',
      body: formData
    });
    const result = await res.json();
    if (result.success) {
      document.getElementById('uploadModal').close();
      document.getElementById('upTitle').value = '';
      document.getElementById('upText').value = '';
      document.getElementById('upFile').value = '';
      
      appState.selectedScopeDocIds.add(result.doc_id);
      await fetchStatus();
      await loadDocuments();
      alert(`Document '${title}' successfully ingested into ${result.chunks_created} vector chunks!`);
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
  if (!confirm("Reset knowledge base to standard benchmark datasets?")) return;
  try {
    const res = await fetch('/api/documents/reset', { method: 'POST' });
    await res.json();
    appState.selectedScopeDocIds.clear();
    await fetchStatus();
    await loadDocuments();
    initDefaultConflictDashboard();
    alert("Knowledge base successfully restored to default benchmark corpus.");
  } catch (err) {
    alert(`Reset error: ${err.message}`);
  }
}

// ----------------- REPORT EXPORT CONTROLLER -----------------

async function exportCurrentReport() {
  if (!appState.latestQueryResult) {
    alert("Please run a query first in the Workspace before exporting an intelligence report.");
    return;
  }

  try {
    const res = await fetch('/api/export/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: appState.latestQueryResult.question,
        answer: appState.latestQueryResult.answer,
        citations: appState.latestQueryResult.citations || [],
        conflicts: appState.latestQueryResult.conflicts || [],
        groundedness_score: appState.latestQueryResult.groundedness_score,
        format: "markdown"
      })
    });
    const data = await res.json();
    if (data.report) {
      // Trigger browser download
      const blob = new Blob([data.report], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Nexora-Intelligence-Report-${Date.now()}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
  } catch (err) {
    alert(`Failed to export report: ${err.message}`);
  }
}

// ----------------- BENCHMARK SUITE CONTROLLER -----------------

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

// ----------------- CONFIGURATION ENDPOINTS -----------------

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
    alert(`Model configuration updated! Active vector dimension: ${result.embedding_dim}`);
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