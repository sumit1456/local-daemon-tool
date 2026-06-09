const BASE = 'http://localhost:8000';

async function api(path, opts = {}) {
  const r = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function loading(container) {
  container.innerHTML = `<div class="empty-state"><div class="spinner"></div><div class="empty-sub">Loading…</div></div>`;
}

function empty(container, icon, title, sub) {
  container.innerHTML = `<div class="empty-state">
    <div class="empty-icon">${icon}</div>
    <div class="empty-title">${title}</div>
    <div class="empty-sub">${sub}</div>
  </div>`;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function getRepo() {
  return document.getElementById('repo-path').value.trim() || '.';
}

/* ═══════════════════════════════════════════════════════════
   NAV / PAGE ROUTING
═══════════════════════════════════════════════════════════ */
function navigateToPage(pageName) {
  document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  
  const navItem = document.querySelector(`.nav-item[data-page="${pageName}"]`);
  if (navItem) navItem.classList.add('active');
  
  const pageId = 'page-' + pageName;
  document.getElementById(pageId)?.classList.add('active');
  closeCodePanel();
}

document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => {
    navigateToPage(item.dataset.page);
  });
});

/* ═══════════════════════════════════════════════════════════
   CODE PANEL (slide-in)
═══════════════════════════════════════════════════════════ */
const codePanel = document.getElementById('code-panel');
let _currentPanelSource = '';

const LANG_LABELS = {
  python:'Python', javascript:'JavaScript', typescript:'TypeScript',
  java:'Java', go:'Go', rust:'Rust',
  html:'HTML', css:'CSS', json:'JSON', markdown:'Markdown', plaintext:'Plain Text'
};

function openCodePanel(title, source, lang = 'plaintext') {
  _currentPanelSource = source;

  // Title
  document.getElementById('code-panel-title').textContent = title;

  // Toolbar — language badge
  const badge = document.getElementById('cp-lang-badge');
  badge.textContent = LANG_LABELS[lang] || lang;

  // Toolbar — line count
  const lineCount = (source.match(/\n/g) || []).length + 1;
  document.getElementById('cp-line-count').textContent = `${lineCount} line${lineCount !== 1 ? 's' : ''}`;

  // Highlight
  const el = document.getElementById('code-panel-content');
  el.className = `language-${lang}`;
  el.textContent = source;
  hljs.highlightElement(el);

  // Line numbers (plugin)
  if (typeof hljs.lineNumbersBlock === 'function') {
    hljs.lineNumbersBlock(el);
  }

  // Open panel
  codePanel.classList.add('open');
}

function closeCodePanel() {
  codePanel.classList.remove('open');
}

document.getElementById('code-panel-close').addEventListener('click', closeCodePanel);

// Copy button
document.getElementById('cp-copy-btn').addEventListener('click', () => {
  if (!_currentPanelSource) return;
  navigator.clipboard.writeText(_currentPanelSource).then(() => {
    const btn = document.getElementById('cp-copy-btn');
    btn.textContent = '✓ Copied';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = '⎘ Copy'; btn.classList.remove('copied'); }, 1800);
  }).catch(() => toast('Copy failed', 'error'));
});

function detectLang(filePath) {
  const ext = (filePath || '').split('.').pop().toLowerCase();
  const map = { py:'python', js:'javascript', ts:'typescript',
                java:'java', go:'go', rs:'rust',
                html:'html', css:'css', json:'json', md:'markdown' };
  return map[ext] || 'plaintext';
}

/* ═══════════════════════════════════════════════════════════
   CODE SEARCH
═══════════════════════════════════════════════════════════ */
const csResults = document.getElementById('cs-results');

document.getElementById('cs-search-btn').addEventListener('click', runCodeSearch);
document.getElementById('cs-query').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    runCodeSearch();
  }
});

async function runCodeSearch() {
  let q = document.getElementById('cs-query').value;
  // Trim only leading newlines and trailing whitespace to preserve indentation on the first line
  q = q.replace(/^[\r\n]+/, '').replace(/[\s\r\n]+$/, '');
  const lang  = document.getElementById('cs-lang').value;
  const limit = document.getElementById('cs-limit').value || 50;
  if (!q) { toast('Enter a search query', 'error'); return; }

  loading(csResults);
  try {
    const params = new URLSearchParams({ q, path: getRepo(), limit });
    if (lang) params.append('lang', lang);
    const data = await api(`/search/code?${params}`);

    if (!data.matches.length) {
      empty(csResults, '🔍', 'No matches found', `No results for "${escHtml(q)}" in this repo.`);
      return;
    }

    let html = `<div class="stats-bar"><span class="stats-badge">⚡ ${data.total} match${data.total!==1?'es':''}</span> for <code style="white-space: pre-wrap; font-family: var(--font-mono); background: var(--bg-elevated); padding: 2px 6px; border-radius: 4px;">"${escHtml(q)}"</code></div>`;
    data.matches.forEach(m => {
      const normalizedText = m.text.replace(/\r\n/g, '\n');
      const normalizedQ = q.replace(/\r\n/g, '\n');
      const highlighted = escHtml(normalizedText).replace(
        new RegExp(escHtml(normalizedQ).replace(/[.*+?^${}()|[\]\\]/g,'\\$&'), 'gi'),
        s => `<span class="match-highlight">${s}</span>`
      );
      html += `
        <div class="match-card" onclick="loadFunctionContext('${escHtml(m.file)}',${m.line})">
          <div class="match-header">
            <span class="file-icon">📄</span>
            <span class="file-path">${escHtml(m.file)}</span>
            <span class="line-badge">L${m.line}:${m.col}</span>
          </div>
          <div class="match-body">
            <div class="match-code">${highlighted}</div>
          </div>
        </div>`;
    });
    csResults.innerHTML = html;
  } catch(e) {
    empty(csResults, '⚠️', 'Search failed', e.message);
    toast('Search error: ' + e.message, 'error');
  }
}

async function loadFunctionContext(file, line) {
  try {
    const source = await fetchFileSnippet(file);
    openCodePanel(file, source, detectLang(file));
  } catch(e) {
    toast('Cannot preview: ' + e.message, 'error');
  }
}

async function fetchFileSnippet(file) {
  const data = await api(`/search/file-read?${new URLSearchParams({ file })}`);
  return data.content;
}

/* ═══════════════════════════════════════════════════════════
   SYMBOL SEARCH
═══════════════════════════════════════════════════════════ */
const ssResults = document.getElementById('ss-results');

document.getElementById('ss-search-btn').addEventListener('click', runSymbolSearch);
document.getElementById('ss-name').addEventListener('keydown', e => { if(e.key==='Enter') runSymbolSearch(); });

async function runSymbolSearch() {
  let name = document.getElementById('ss-name').value.trim();
  const kind = document.getElementById('ss-kind').value;
  if (!name) { toast('Enter a symbol name', 'error'); return; }

  // Strip: "def normalize_layout(items):" → "normalize_layout"
  name = name
    .replace(/^(async\s+def|def|class)\s+/, '')
    .replace(/\s*\(.*/, '')
    .replace(/:$/, '')
    .trim();

  loading(ssResults);
  try {
    const params = new URLSearchParams({ name });
    if (kind) params.append('kind', kind);
    const data = await api(`/search/symbol?${params}`);

    if (!data.length) {
      // Fallback: search using code search API
      const fallbackQuery = (kind === 'class') ? `class ${name}` : `def ${name}`;
      const codeParams = new URLSearchParams({ q: fallbackQuery, path: getRepo(), limit: 50 });
      const fallbackData = await api(`/search/code?${codeParams}`);
      
      if (!fallbackData.matches || !fallbackData.matches.length) {
        empty(ssResults, '🔣', 'No symbols found', `No symbols or code matches matching "${escHtml(name)}".`);
        return;
      }

      let html = `
        <div class="stats-bar" style="margin-bottom: 16px;">
          <span class="stats-badge" style="background: rgba(246,173,85,0.18); color: var(--warning); border-color: rgba(246,173,85,0.35);">⚠️ Fallback</span>
          <span>Symbols not yet indexed — showing code matches for <b>"${escHtml(fallbackQuery)}"</b></span>
        </div>`;
      fallbackData.matches.forEach(m => {
        html += `
          <div class="match-card" onclick="loadFunctionContext('${escHtml(m.file)}',${m.line})">
            <div class="match-header">
              <span class="file-icon">📄</span>
              <span class="file-path">${escHtml(m.file)}</span>
              <span class="line-badge">L${m.line}:${m.col}</span>
            </div>
            <div class="match-body">
              <div class="match-code">${escHtml(m.text)}</div>
            </div>
          </div>`;
      });
      ssResults.innerHTML = html;
      return;
    }

    let html = `<div class="stats-bar"><span class="stats-badge">🔣 ${data.length} symbol${data.length!==1?'s':''}</span></div>`;
    data.forEach(s => {
      const kindClass = { function:'kind-function', class:'kind-class', method:'kind-method', interface:'kind-interface' }[s.kind] || 'kind-default';
      html += `
        <div class="symbol-card" onclick="loadSymbolSource('${escHtml(s.file)}','${escHtml(s.name)}','${escHtml(s.kind)}')">
          <span class="symbol-kind ${kindClass}">${s.kind}</span>
          <span class="symbol-name">${escHtml(s.name)}</span>
          <span class="symbol-file">${escHtml(s.file)}</span>
          <span class="symbol-lines">L${s.line_start}–${s.line_end}</span>
        </div>`;
    });
    ssResults.innerHTML = html;
  } catch(e) {
    empty(ssResults, '⚠️', 'Search failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

async function loadSymbolSource(file, name, kind) {
  try {
    let data;
    if (kind === 'class') {
      data = await api(`/search/class?${new URLSearchParams({file,name})}`);
    } else {
      data = await api(`/search/function?${new URLSearchParams({file,name})}`);
    }
    
    // Autofill Code Editor fields
    const filePath = data.file || file;
    document.getElementById('edit-file').value = filePath;
    const ext = filePath.split('.').pop().toLowerCase();
    setEditorLang(ext);
    cmOld.setValue(data.source);
    cmNew.setValue(data.source);

    // Switch to Code Editor page
    navigateToPage('edit');
    // Refresh CM layout after becoming visible
    setTimeout(() => { cmOld.refresh(); cmNew.refresh(); }, 50);

    toast(`Loaded ${name} into Code Editor`, 'success');
  } catch(e) {
    toast('Cannot load source: ' + e.message, 'error');
  }
}

/* ═══════════════════════════════════════════════════════════
   FILE FINDER
═══════════════════════════════════════════════════════════ */
const ffResults = document.getElementById('ff-results');

document.getElementById('ff-search-btn').addEventListener('click', runFileFinder);
document.getElementById('ff-pattern').addEventListener('keydown', e => { if(e.key==='Enter') runFileFinder(); });

async function runFileFinder() {
  const pattern = document.getElementById('ff-pattern').value.trim();
  loading(ffResults);
  try {
    const params = new URLSearchParams({ pattern, root: getRepo() });
    const data   = await api(`/search/file?${params}`);

    if (!data.length) {
      empty(ffResults, '📂', 'No files found', `No files matching "${escHtml(pattern)}".`);
      return;
    }

    const ICONS = { py:'🐍', js:'🟨', ts:'🔷', java:'☕', go:'🐹', rs:'🦀', html:'🌐', css:'🎨', json:'📋', md:'📝' };
    let html = `<div class="stats-bar"><span class="stats-badge">📂 ${data.length} file${data.length!==1?'s':''}</span></div>`;
    data.forEach(f => {
      const ext  = f.split('.').pop().toLowerCase();
      const icon = ICONS[ext] || '📄';
      html += `<div class="file-item" onclick="loadFunctionContext('${escHtml(f)}', 1)">${icon} ${escHtml(f)}</div>`;
    });
    ffResults.innerHTML = html;
  } catch(e) {
    empty(ffResults, '⚠️', 'Search failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => toast('Copied: ' + text, 'info'));
}

/* ═══════════════════════════════════════════════════════════
   EDIT — CodeMirror editors
═══════════════════════════════════════════════════════════ */
let currentEditId = null;
let _lastDiffText = '';

const editStatus  = document.getElementById('edit-status');
const editApplyBtn = document.getElementById('edit-apply-btn');
const editDiff    = document.getElementById('edit-diff');

/* ── CM mode map ── */
const EXT_TO_CM_MODE = {
  py: 'python', js: 'javascript', ts: { name: 'javascript', typescript: true },
  java: 'text/x-java', go: 'go', rs: 'rust',
  html: 'htmlmixed', css: 'css', json: 'application/json'
};
const EXT_TO_LABEL = {
  py:'Python', js:'JavaScript', ts:'TypeScript',
  java:'Java', go:'Go', rs:'Rust',
  html:'HTML', css:'CSS', json:'JSON'
};

const CM_OPTS = {
  theme: 'dracula',
  lineNumbers: true,
  indentUnit: 4,
  tabSize: 4,
  indentWithTabs: false,
  lineWrapping: false,
  autofocus: false,
  extraKeys: { Tab: cm => cm.execCommand('insertSoftTab') },
  styleActiveLine: true,
};

/* Initialise both editors */
const cmOld = CodeMirror.fromTextArea(document.getElementById('edit-old'), { ...CM_OPTS, mode: 'plaintext' });
const cmNew = CodeMirror.fromTextArea(document.getElementById('edit-new'), { ...CM_OPTS, mode: 'plaintext' });

/* Make editors fill pane height */
cmOld.setSize('100%', '100%');
cmNew.setSize('100%', '100%');

function setEditorLang(ext) {
  const mode  = EXT_TO_CM_MODE[ext] || 'plaintext';
  const label = EXT_TO_LABEL[ext]   || 'Plain';
  cmOld.setOption('mode', mode);
  cmNew.setOption('mode', mode);
  document.getElementById('old-lang-badge').textContent = label;
  document.getElementById('new-lang-badge').textContent = label;
}

/* Watch file path input → update editor language */
document.getElementById('edit-file').addEventListener('input', () => {
  const file = document.getElementById('edit-file').value.trim();
  const ext  = file.split('.').pop().toLowerCase();
  setEditorLang(ext);
});

/* ── Copy buttons ── */
function makeCopyBtn(btnId, getContent) {
  document.getElementById(btnId).addEventListener('click', () => {
    const text = getContent();
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      const btn = document.getElementById(btnId);
      btn.textContent = '✓ Copied';
      btn.classList.add('copied');
      setTimeout(() => { btn.textContent = '⎘ Copy'; btn.classList.remove('copied'); }, 1800);
    }).catch(() => toast('Copy failed', 'error'));
  });
}
makeCopyBtn('old-copy-btn', () => cmOld.getValue());
makeCopyBtn('new-copy-btn', () => cmNew.getValue());
makeCopyBtn('diff-copy-btn', () => _lastDiffText);

/* ── Preview ── */
document.getElementById('edit-preview-btn').addEventListener('click', async () => {
  const file     = document.getElementById('edit-file').value.trim();
  const old_code = cmOld.getValue();
  const new_code = cmNew.getValue();
  if (!file || !old_code || !new_code) { toast('Fill in all three fields', 'error'); return; }

  editStatus.textContent = 'Generating preview…';
  editApplyBtn.disabled = true;
  currentEditId = null;

  try {
    const data = await api('/preview-edit', {
      method: 'POST',
      body: JSON.stringify({ file, old_code, new_code }),
    });
    currentEditId  = data.edit_id;
    _lastDiffText  = data.diff || '';

    // Render coloured diff with gutter line numbers
    const lines = _lastDiffText.split('\n');
    let addN = 0, delN = 0, ctxN = 0;
    editDiff.innerHTML = lines.map((l, i) => {
      const lineNum = i + 1;
      if (l.startsWith('+++') || l.startsWith('---') || l.startsWith('@@')) {
        return `<div class="diff-line diff-hdr"><span class="diff-gutter">${lineNum}</span><span class="diff-text">${escHtml(l)}</span></div>`;
      }
      if (l.startsWith('+')) {
        return `<div class="diff-line diff-add"><span class="diff-gutter">+${lineNum}</span><span class="diff-text">${escHtml(l.slice(1))}</span></div>`;
      }
      if (l.startsWith('-')) {
        return `<div class="diff-line diff-del"><span class="diff-gutter">-${lineNum}</span><span class="diff-text">${escHtml(l.slice(1))}</span></div>`;
      }
      return `<div class="diff-line diff-ctx"><span class="diff-gutter">${lineNum}</span><span class="diff-text">${escHtml(l)}</span></div>`;
    }).join('');

    editStatus.textContent = `edit_id: ${currentEditId} — ready to apply`;
    editApplyBtn.disabled = false;
    toast('Preview ready', 'success');
  } catch(e) {
    editDiff.innerHTML = `<div class="diff-line diff-del"><span class="diff-gutter">!</span><span class="diff-text">${escHtml(e.message)}</span></div>`;
    editStatus.textContent = 'Preview failed';
    toast('Preview error: ' + e.message, 'error');
  }
});

/* ── Apply ── */
editApplyBtn.addEventListener('click', async () => {
  if (!currentEditId) return;
  editStatus.textContent = 'Applying edit…';
  editApplyBtn.disabled = true;
  try {
    const data = await api('/apply-edit', {
      method: 'POST',
      body: JSON.stringify({ edit_id: currentEditId }),
    });
    editStatus.textContent = `Applied — commit: ${data.commit_sha || 'ok'}`;
    currentEditId = null;
    toast('Edit applied and committed ✅', 'success');
  } catch(e) {
    editStatus.textContent = 'Apply failed: ' + e.message;
    toast('Apply error: ' + e.message, 'error');
  }
});

/* ── Undo ── */
document.getElementById('edit-undo-btn').addEventListener('click', async () => {
  editStatus.textContent = 'Reverting last edit…';
  try {
    const data = await api('/undo', { method: 'POST' });
    editStatus.textContent = `Reverted — commit: ${data.revert_sha || 'ok'}`;
    toast('Last edit reverted ↩', 'info');
  } catch(e) {
    editStatus.textContent = 'Undo failed: ' + e.message;
    toast('Undo error: ' + e.message, 'error');
  }
});

/* ── Auto-detect file path on paste into Old Code ── */
cmOld.on('change', (cm, change) => {
  if (change.origin !== 'paste') return;
  setTimeout(async () => {
    const code = cm.getValue().replace(/^[\r\n]+/, '').replace(/[\s\r\n]+$/, '');
    if (!code) return;
    try {
      const params = new URLSearchParams({ q: code, path: getRepo(), limit: 1 });
      const data = await api(`/search/code?${params}`);
      if (data.matches && data.matches.length > 0) {
        const file = data.matches[0].file;
        document.getElementById('edit-file').value = file;
        setEditorLang(file.split('.').pop().toLowerCase());
        toast(`Auto-filled file path: ${file}`, 'success');
      }
    } catch (err) { /* silent */ }
  }, 50);
});

/* ── Auto-detect file and old code on paste into New Code ── */
cmNew.on('change', (cm, change) => {
  if (change.origin !== 'paste') return;
  setTimeout(async () => {
    const code = cm.getValue();
    if (!code || code.trim().length < 10) return;
    
    const hintFile = document.getElementById('edit-file').value.trim();
    
    try {
      const data = await api('/search/detect-original', {
        method: 'POST',
        body: JSON.stringify({
          code: code,
          file_path_hint: hintFile || null
        })
      });
      
      if (data.found) {
        document.getElementById('edit-file').value = data.file;
        const ext = data.file.split('.').pop().toLowerCase();
        setEditorLang(ext);
        cmOld.setValue(data.source);
        toast(`Auto-detected original function in ${data.file} and populated Old Code!`, 'success');
      } else {
        // Fallback: If AST symbol mapping fails, check exact match via code search
        const cleanCode = code.replace(/^[\r\n]+/, '').replace(/[\s\r\n]+$/, '');
        const params = new URLSearchParams({ q: cleanCode, path: getRepo(), limit: 1 });
        const codeSearchRes = await api(`/search/code?${params}`);
        if (codeSearchRes.matches && codeSearchRes.matches.length > 0) {
          const file = codeSearchRes.matches[0].file;
          document.getElementById('edit-file').value = file;
          setEditorLang(file.split('.').pop().toLowerCase());
          
          const fullFileObj = await api(`/search/file-read?${new URLSearchParams({ file })}`);
          cmOld.setValue(fullFileObj.content);
          toast(`Matched exact file code in ${file} and populated Old Code!`, 'success');
        }
      }
    } catch (err) {
      console.warn("Auto-detect failed:", err);
    }
  }, 50);
});


/* ═══════════════════════════════════════════════════════════
   MULTI-BLOCK EDITOR
═══════════════════════════════════════════════════════════ */

/* State */
let _mbBlocks = [];   // Array of {kind, name, source, cmOld, cmNew, editId, applied}
let _mbLang   = null; // detected language string

/* Mode toggle */
const modeBtns = document.querySelectorAll('.mode-btn');
const singleWrap = document.getElementById('single-edit-wrap');
const multiWrap  = document.getElementById('multi-block-area');

modeBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    modeBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const mode = btn.dataset.mode;
    if (mode === 'single') {
      singleWrap.style.display = 'flex';
      multiWrap.style.display  = 'none';
    } else {
      singleWrap.style.display = 'none';
      multiWrap.style.display  = 'flex';
      // Focus paste area
      setTimeout(() => document.getElementById('mb-paste-input').focus(), 60);
    }
  });
});

/* Kind → CSS class helper */
function kindCls(kind) {
  return 'kind-' + (['function','class','import','constant'].includes(kind) ? kind : 'other');
}
/* Kind → emoji */
function kindIcon(kind) {
  return {function:'ƒ',class:'◆',import:'↓',constant:'K',other:'…'}[kind] || '·';
}

/* Render diff lines inside a .mb-diff-row div */
function renderMbDiff(container, diffText) {
  const lines = diffText.split('\n');
  container.innerHTML = lines.map((l, i) => {
    const n = i + 1;
    if (l.startsWith('+++') || l.startsWith('---') || l.startsWith('@@'))
      return `<div class="diff-line diff-hdr"><span class="diff-gutter">${n}</span><span class="diff-text">${escHtml(l)}</span></div>`;
    if (l.startsWith('+'))
      return `<div class="diff-line diff-add"><span class="diff-gutter">+</span><span class="diff-text">${escHtml(l.slice(1))}</span></div>`;
    if (l.startsWith('-'))
      return `<div class="diff-line diff-del"><span class="diff-gutter">-</span><span class="diff-text">${escHtml(l.slice(1))}</span></div>`;
    return `<div class="diff-line diff-ctx"><span class="diff-gutter"></span><span class="diff-text">${escHtml(l)}</span></div>`;
  }).join('');
}

/* Create one block row DOM element */
function createBlockRow(block, index) {
  const row = document.createElement('div');
  row.className = 'mb-block-row';
  row.id = `mb-row-${index}`;

  const displayName = block.name || `(${block.kind} #${index + 1})`;

  row.innerHTML = `
    <div class="mb-block-header" data-idx="${index}">
      <span class="mb-block-kind ${kindCls(block.kind)}">${kindIcon(block.kind)} ${block.kind}</span>
      <span class="mb-block-name" title="${escHtml(displayName)}">${escHtml(displayName)}</span>
      <span class="mb-block-chevron">▾</span>
      <button class="mb-block-dismiss" title="Dismiss this block" data-idx="${index}">✕</button>
    </div>
    <div class="mb-block-body">
      <div class="mb-editor-row">
        <div class="mb-pane" id="mb-pane-old-${index}">
          <div class="mb-pane-label">
            <span>OLD  <span style="color:var(--text-muted);font-weight:400">(original)</span></span>
            <span class="mb-pane-status" id="mb-old-status-${index}"></span>
          </div>
          <textarea id="mb-ta-old-${index}"></textarea>
        </div>
        <div class="mb-pane" id="mb-pane-new-${index}">
          <div class="mb-pane-label">
            <span>NEW  <span style="color:var(--text-muted);font-weight:400">(your changes)</span></span>
            <span class="mb-pane-status" id="mb-new-status-${index}"></span>
          </div>
          <textarea id="mb-ta-new-${index}"></textarea>
        </div>
      </div>
      <div class="mb-diff-row" id="mb-diff-${index}" style="display:none"></div>
      <div class="mb-block-actions">
        <span class="mb-block-status" id="mb-bstatus-${index}">Ready</span>
        <button class="mb-copy-btn" data-copy-idx="${index}">⎘ Copy New</button>
        <button class="mb-preview-btn" data-preview-idx="${index}">👁 Preview</button>
        <button class="mb-apply-btn" data-apply-idx="${index}" disabled>✅ Apply</button>
      </div>
    </div>`;
  return row;
}

/* Parse button — main entry point */
document.getElementById('mb-parse-btn').addEventListener('click', async () => {
  const pasted = document.getElementById('mb-paste-input').value;
  if (!pasted.trim()) { toast('Paste some code first', 'error'); return; }

  const hintFile = document.getElementById('edit-file').value.trim() || null;

  try {
    const data = await api('/parse-blocks', {
      method: 'POST',
      body: JSON.stringify({ code: pasted, file_path_hint: hintFile })
    });

    _mbBlocks = data.blocks.map(b => ({ ...b, cmOld: null, cmNew: null, editId: null, applied: false }));
    _mbLang   = data.lang || null;
    const cmMode = EXT_TO_CM_MODE[_mbLang] || 'plaintext';

    // Update count
    const stack = document.getElementById('mb-blocks-stack');
    stack.innerHTML = '';
    document.getElementById('mb-block-count').textContent = _mbBlocks.length;
    document.getElementById('mb-status-bar').style.display = 'flex';
    document.getElementById('mb-status-msg').textContent = `language: ${_mbLang || 'auto'}`;
    document.getElementById('mb-apply-all-btn').disabled = true;

    // Create rows
    _mbBlocks.forEach((block, idx) => {
      const row = createBlockRow(block, idx);
      stack.appendChild(row);

      // Init CodeMirror for OLD pane
      const taOld = document.getElementById(`mb-ta-old-${idx}`);
      const cmOldI = CodeMirror.fromTextArea(taOld, { ...CM_OPTS, mode: cmMode, readOnly: false });
      cmOldI.setSize('100%', '100%');
      block.cmOld = cmOldI;

      // Init CodeMirror for NEW pane
      const taNew = document.getElementById(`mb-ta-new-${idx}`);
      const cmNewI = CodeMirror.fromTextArea(taNew, { ...CM_OPTS, mode: cmMode });
      cmNewI.setSize('100%', '100%');
      cmNewI.setValue(block.source);
      block.cmNew = cmNewI;

      // Auto-detect original source for named blocks
      if (block.name && (block.kind === 'function' || block.kind === 'class')) {
        setTimeout(async () => {
          try {
            const det = await api('/search/detect-original', {
              method: 'POST',
              body: JSON.stringify({ code: block.source, file_path_hint: hintFile })
            });
            if (det.found) {
              cmOldI.setValue(det.source);
              document.getElementById(`mb-old-status-${idx}`).textContent = '✓ auto-filled';
              document.getElementById(`mb-old-status-${idx}`).style.color = 'var(--success)';
              // Also auto-fill file input if empty
              if (!hintFile) {
                document.getElementById('edit-file').value = det.file;
              }
            } else {
              document.getElementById(`mb-old-status-${idx}`).textContent = 'not found';
            }
          } catch(e) {
            document.getElementById(`mb-old-status-${idx}`).textContent = 'lookup failed';
          }
        }, 80 + idx * 30); // stagger requests
      }
    });

    toast(`Parsed ${_mbBlocks.length} block${_mbBlocks.length !== 1 ? 's' : ''}`, 'success');
  } catch(e) {
    toast('Parse error: ' + e.message, 'error');
  }
});

/* Collapse/expand block header click */
document.getElementById('mb-blocks-stack').addEventListener('click', async (e) => {
  // Header toggle
  const hdr = e.target.closest('.mb-block-header');
  if (hdr && !e.target.closest('.mb-block-dismiss')) {
    const row = hdr.closest('.mb-block-row');
    row.classList.toggle('collapsed');
    // Refresh CMs after expand
    if (!row.classList.contains('collapsed')) {
      const idx = parseInt(hdr.dataset.idx);
      setTimeout(() => {
        _mbBlocks[idx]?.cmOld?.refresh();
        _mbBlocks[idx]?.cmNew?.refresh();
      }, 30);
    }
    return;
  }

  // Dismiss button
  const dismissBtn = e.target.closest('.mb-block-dismiss');
  if (dismissBtn) {
    const idx = parseInt(dismissBtn.dataset.idx);
    dismissBtn.closest('.mb-block-row').remove();
    _mbBlocks[idx] = null; // mark as removed
    return;
  }

  // Copy new code button
  const copyBtn = e.target.closest('[data-copy-idx]');
  if (copyBtn && !copyBtn.dataset.previewIdx && !copyBtn.dataset.applyIdx) {
    const idx = parseInt(copyBtn.dataset.copyIdx);
    const val = _mbBlocks[idx]?.cmNew?.getValue();
    if (val) navigator.clipboard.writeText(val).then(() => {
      copyBtn.textContent = '✓ Copied';
      setTimeout(() => { copyBtn.textContent = '⎘ Copy New'; }, 1600);
    });
    return;
  }

  // Preview button
  const previewBtn = e.target.closest('[data-preview-idx]');
  if (previewBtn) {
    const idx = parseInt(previewBtn.dataset.previewIdx);
    const block = _mbBlocks[idx];
    if (!block) return;
    const file = document.getElementById('edit-file').value.trim();
    const old_code = block.cmOld.getValue();
    const new_code = block.cmNew.getValue();
    if (!file)     { toast('Set the file path first', 'error'); return; }
    if (!old_code) { toast('Old code is empty — auto-fill failed or paste manually', 'error'); return; }
    if (!new_code) { toast('New code is empty', 'error'); return; }

    document.getElementById(`mb-bstatus-${idx}`).textContent = 'Generating preview…';
    const applyBtn = document.querySelector(`[data-apply-idx="${idx}"]`);
    applyBtn.disabled = true;
    block.editId = null;

    try {
      const data = await api('/preview-edit', {
        method: 'POST',
        body: JSON.stringify({ file, old_code, new_code })
      });
      block.editId = data.edit_id;
      // Show diff
      const diffDiv = document.getElementById(`mb-diff-${idx}`);
      diffDiv.style.display = 'block';
      renderMbDiff(diffDiv, data.diff || '');
      document.getElementById(`mb-bstatus-${idx}`).textContent = `edit_id: ${data.edit_id}`;
      applyBtn.disabled = false;
      toast(`Block "${block.name || block.kind}" preview ready`, 'success');
    } catch(e) {
      document.getElementById(`mb-bstatus-${idx}`).textContent = 'Preview failed: ' + e.message;
      toast('Preview error: ' + e.message, 'error');
    }
    return;
  }

  // Apply button
  const applyBtn = e.target.closest('[data-apply-idx]');
  if (applyBtn) {
    const idx = parseInt(applyBtn.dataset.applyIdx);
    const block = _mbBlocks[idx];
    if (!block?.editId) return;
    applyBtn.disabled = true;
    document.getElementById(`mb-bstatus-${idx}`).textContent = 'Applying…';
    try {
      await api('/apply-edit', {
        method: 'POST',
        body: JSON.stringify({ edit_id: block.editId })
      });
      block.applied = true;
      document.getElementById(`mb-row-${idx}`).classList.add('applied');
      document.getElementById(`mb-bstatus-${idx}`).textContent = '✅ Applied';
      toast(`Block "${block.name || block.kind}" applied`, 'success');
      // Check if all (non-null, non-import) have been applied
      const pending = _mbBlocks.filter(b => b && !b.applied && b.kind !== 'import');
      if (pending.length === 0) {
        document.getElementById('mb-apply-all-btn').textContent = '✅ All Applied';
      }
    } catch(e) {
      document.getElementById(`mb-row-${idx}`).classList.add('failed');
      document.getElementById(`mb-bstatus-${idx}`).textContent = 'Apply failed: ' + e.message;
      applyBtn.disabled = false;
      toast('Apply error: ' + e.message, 'error');
    }
    return;
  }
});

/* Apply All — previews then applies in sequence */
document.getElementById('mb-apply-all-btn').addEventListener('click', async () => {
  const file = document.getElementById('edit-file').value.trim();
  if (!file) { toast('Set the file path first', 'error'); return; }

  const allBtn = document.getElementById('mb-apply-all-btn');
  allBtn.disabled = true;
  allBtn.textContent = '⏳ Working…';

  let applied = 0, failed = 0;
  for (let idx = 0; idx < _mbBlocks.length; idx++) {
    const block = _mbBlocks[idx];
    if (!block || block.applied) continue;
    const old_code = block.cmOld.getValue();
    const new_code = block.cmNew.getValue();
    if (!old_code || !new_code) { failed++; continue; }

    try {
      document.getElementById(`mb-bstatus-${idx}`).textContent = 'Previewing…';
      const prev = await api('/preview-edit', {
        method: 'POST',
        body: JSON.stringify({ file, old_code, new_code })
      });
      document.getElementById(`mb-bstatus-${idx}`).textContent = 'Applying…';
      await api('/apply-edit', {
        method: 'POST',
        body: JSON.stringify({ edit_id: prev.edit_id })
      });
      block.applied = true;
      block.editId  = prev.edit_id;
      document.getElementById(`mb-row-${idx}`).classList.add('applied');
      document.getElementById(`mb-bstatus-${idx}`).textContent = '✅ Applied';
      document.querySelector(`[data-apply-idx="${idx}"]`).disabled = true;
      applied++;
    } catch(e) {
      failed++;
      document.getElementById(`mb-row-${idx}`).classList.add('failed');
      document.getElementById(`mb-bstatus-${idx}`).textContent = 'Failed: ' + e.message;
    }
  }

  allBtn.textContent = failed ? `⚠ ${applied} applied, ${failed} failed` : `✅ All Applied (${applied})`;
  toast(failed ? `Applied ${applied}, failed ${failed}` : `All ${applied} blocks applied ✅`, failed ? 'error' : 'success');
});

/* ═══════════════════════════════════════════════════════════
   BUILD / TEST / LINT
═══════════════════════════════════════════════════════════ */
const buildOutput = document.getElementById('build-output');

function setBuildOutput(label, data) {
  const ok    = data.exit_code === 0;
  const color = ok ? 'out-ok' : 'out-err';
  buildOutput.innerHTML =
    `<span class="out-label">▶ ${label}</span>\n` +
    `<span class="${color}">Exit code: ${data.exit_code}</span>\n\n` +
    (data.stdout ? escHtml(data.stdout) + '\n' : '') +
    (data.stderr ? `<span class="out-err">${escHtml(data.stderr)}</span>\n` : '');
  if (ok) toast(`${label} succeeded ✅`, 'success');
  else     toast(`${label} finished with errors`, 'error');
}

async function runWorker(action, langId) {
  const lang      = document.getElementById(langId).value;
  const repo_path = getRepo();
  buildOutput.innerHTML = `<span class="out-label">▶ Running ${action}…</span>\n`;
  try {
    const data = await api(`/${action}`, {
      method: 'POST',
      body: JSON.stringify({ lang, repo_path }),
    });
    setBuildOutput(action, data);
  } catch(e) {
    buildOutput.innerHTML += `<span class="out-err">Error: ${escHtml(e.message)}</span>`;
    toast(`${action} error: ` + e.message, 'error');
  }
}

document.getElementById('build-run-btn').addEventListener('click', () => runWorker('build', 'build-lang-build'));
document.getElementById('test-run-btn').addEventListener('click', () => runWorker('test',  'build-lang-test'));
document.getElementById('lint-run-btn').addEventListener('click', () => runWorker('lint',  'build-lang-lint'));

/* ═══════════════════════════════════════════════════════════
   INDEX PAGE
═══════════════════════════════════════════════════════════ */
const idxResults = document.getElementById('idx-results');

document.getElementById('idx-load-btn').addEventListener('click', loadIndex);
document.getElementById('idx-files').addEventListener('keydown', e => { if(e.key==='Enter') loadIndex(); });

async function loadIndex() {
  const filesInput = document.getElementById('idx-files').value.trim();
  const files = filesInput ? filesInput.split(',').map(f => f.trim()) : null;
  
  loading(idxResults);
  try {
    const params = new URLSearchParams();
    if (files && files.length > 0) {
      files.forEach(f => params.append('files', f));
    }
    const data = await api(`/search/index?${params}`);
    
    if (!data || data.length === 0) {
      empty(idxResults, '📋', 'No index data', 'Repository has not been indexed yet.');
      return;
    }

    let html = `<div class="stats-bar"><span class="stats-badge">📋 ${data.length} file${data.length!==1?'s':''}</span></div>`;
    data.forEach(item => {
      const symbols = item.symbols || [];
      const symbolHtml = symbols.map(s => {
        const kindClass = { function:'kind-function', class:'kind-class', method:'kind-method', interface:'kind-interface' }[s.kind] || 'kind-default';
        return `<span class="symbol-kind ${kindClass}" style="font-size:10px;padding:2px 6px;margin-right:4px;">${s.kind}</span><span style="font-family:var(--font-mono);font-size:12px;color:var(--text-secondary);">${escHtml(s.name)}</span>`;
      }).join(' ');
      
      html += `
        <div class="match-card">
          <div class="match-header">
            <span class="file-icon">📄</span>
            <span class="file-path">${escHtml(item.file)}</span>
          </div>
          <div class="match-body" style="padding:8px 14px;">
            <div style="display:flex;flex-wrap:wrap;gap:4px;">${symbolHtml || '<span style="color:var(--text-muted);font-size:12px;">No symbols</span>'}</div>
          </div>
        </div>`;
    });
    idxResults.innerHTML = html;
  } catch(e) {
    empty(idxResults, '⚠️', 'Index load failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

/* ═══════════════════════════════════════════════════════════
   OVERVIEW PAGE
═══════════════════════════════════════════════════════════ */
const ovResults = document.getElementById('ov-results');

document.getElementById('ov-load-btn').addEventListener('click', loadOverview);
document.getElementById('ov-files').addEventListener('keydown', e => { if(e.key==='Enter') loadOverview(); });

async function loadOverview() {
  const filesInput = document.getElementById('ov-files').value.trim();
  const files = filesInput ? filesInput.split(',').map(f => f.trim()) : null;
  
  loading(ovResults);
  try {
    const params = new URLSearchParams();
    if (files && files.length > 0) {
      files.forEach(f => params.append('files', f));
    }
    const data = await api(`/search/overview?${params}`);
    
    if (!data) {
      empty(ovResults, '🗺', 'No overview data', 'Repository has not been indexed yet.');
      return;
    }

    const fileCount = (data.files || []).length;
    const edgeCount = (data.edges || []).length;
    const calleeCount = Object.keys(data.callees || {}).length;
    const callerCount = Object.keys(data.callers || {}).length;

    let html = `<div class="stats-bar">
      <span class="stats-badge">📄 ${fileCount} files</span>
      <span class="stats-badge">🔗 ${edgeCount} edges</span>
      <span class="stats-badge">🔣 ${calleeCount} callees</span>
      <span class="stats-badge">🔣 ${callerCount} callers</span>
    </div>`;

    // Show call edges
    if (data.edges && data.edges.length > 0) {
      html += `<div style="margin-bottom:16px;"><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">Call Edges</h3>`;
      data.edges.forEach(edge => {
        html += `
          <div class="symbol-card">
            <span class="symbol-name" style="font-size:12px;">${escHtml(edge.caller_name || 'unknown')} → ${escHtml(edge.callee_name || 'unknown')}</span>
            <span class="symbol-file" style="font-size:11px;">${escHtml(edge.caller_file || '')}</span>
          </div>`;
      });
      html += `</div>`;
    }

    // Show files
    if (data.files && data.files.length > 0) {
      html += `<div><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">Files</h3>`;
      data.files.forEach(file => {
        const symbols = (file.symbols || []).map(s => s.name).join(', ');
        html += `
          <div class="match-card">
            <div class="match-header">
              <span class="file-icon">📄</span>
              <span class="file-path">${escHtml(file.file)}</span>
            </div>
            <div class="match-body" style="padding:8px 14px;font-size:12px;color:var(--text-muted);">
              ${symbols ? 'Symbols: ' + escHtml(symbols) : 'No symbols'}
            </div>
          </div>`;
      });
      html += `</div>`;
    }

    ovResults.innerHTML = html;
  } catch(e) {
    empty(ovResults, '⚠️', 'Overview load failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

/* ═══════════════════════════════════════════════════════════
   CALL GRAPH PAGE
═══════════════════════════════════════════════════════════ */
const cgResults = document.getElementById('cg-results');

document.getElementById('cg-callers-btn').addEventListener('click', () => loadCallGraph('callers'));
document.getElementById('cg-callees-btn').addEventListener('click', () => loadCallGraph('callees'));
document.getElementById('cg-symbol').addEventListener('keydown', e => { if(e.key==='Enter') loadCallGraph('callers'); });

async function loadCallGraph(type) {
  const symbol = document.getElementById('cg-symbol').value.trim();
  if (!symbol) { toast('Enter a symbol name', 'error'); return; }
  
  loading(cgResults);
  try {
    const endpoint = type === 'callers' ? '/search/callers' : '/search/callees';
    const data = await api(`${endpoint}?${new URLSearchParams({ symbol_name: symbol })}`);
    
    if (!data || data.length === 0) {
      empty(cgResults, '🔗', 'No results', `No ${type} found for symbol "${escHtml(symbol)}".`);
      return;
    }

    let html = `<div class="stats-bar"><span class="stats-badge">🔗 ${data.length} ${type}</span> for <code style="font-family:var(--font-mono);background:var(--bg-elevated);padding:2px 6px;border-radius:4px;">${escHtml(symbol)}</code></div>`;
    data.forEach(item => {
      if (type === 'callers') {
        html += `
          <div class="symbol-card">
            <span class="symbol-kind kind-function">caller</span>
            <span class="symbol-name">${escHtml(item.caller_name || 'unknown')}</span>
            <span class="symbol-file">${escHtml(item.caller_file || '')}</span>
          </div>`;
      } else {
        html += `
          <div class="symbol-card">
            <span class="symbol-kind kind-function">callee</span>
            <span class="symbol-name">${escHtml(item.callee_name || 'unknown')}</span>
            <span class="symbol-file">${escHtml(item.callee_file || '')}</span>
          </div>`;
      }
    });
    cgResults.innerHTML = html;
  } catch(e) {
    empty(cgResults, '⚠️', 'Search failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

/* ═══════════════════════════════════════════════════════════
   FUNCTION EXTRACT PAGE
═══════════════════════════════════════════════════════════ */
const feResults = document.getElementById('fe-results');

document.getElementById('fe-signature-btn').addEventListener('click', () => loadFunctionExtract('signature'));
document.getElementById('fe-body-btn').addEventListener('click', () => loadFunctionExtract('body'));

/* ── Auto-fill file path + default range on typing ── */
{
  let _feDebounce = null;
  const feFile     = document.getElementById('fe-file');
  const feLineStart = document.getElementById('fe-line-start');
  const feLineEnd   = document.getElementById('fe-line-end');

  feFile.addEventListener('input', () => {
    clearTimeout(_feDebounce);
    const val = feFile.value.trim();
    if (!val || val.length < 2) return;

    _feDebounce = setTimeout(async () => {
      try {
        const data = await api(`/search/file?${new URLSearchParams({ pattern: val, root: getRepo() })}`);
        if (!data || data.length === 0) return;

        // Pick best match: exact filename match first, then first result
        const lower = val.toLowerCase();
        const exact = data.find(f => f.toLowerCase().endsWith(lower));
        const match = exact || data[0];

        feFile.value = match;
        if (!feLineStart.value) feLineStart.value = '1';
        if (!feLineEnd.value)   feLineEnd.value   = '100';

        toast(`Found: ${match}`, 'success');
      } catch (_) {}
    }, 400);
  });
}

async function loadFunctionExtract(type) {
  const file = document.getElementById('fe-file').value.trim();
  const lineStart = document.getElementById('fe-line-start').value;
  const lineEnd = document.getElementById('fe-line-end').value;
  
  if (!file || !lineStart || !lineEnd) { toast('Fill in file path and line range', 'error'); return; }
  
  loading(feResults);
  try {
    const endpoint = type === 'signature' ? '/search/function-signature' : '/search/function-body';
    const data = await api(`${endpoint}?${new URLSearchParams({ file, line_start: lineStart, line_end: lineEnd })}`);
    
    if (!data) {
      empty(feResults, '⚠️', 'Extraction failed', 'Could not extract function data.');
      return;
    }

    const content = type === 'signature' ? (data.signature || 'No signature found') : (data.body || 'No body found');
    const lang = detectLang(file);
    
    let html = `<div class="stats-bar"><span class="stats-badge">⚡ ${type}</span> for lines ${lineStart}-${lineEnd}</div>`;
    html += `
      <div class="match-card">
        <div class="match-header">
          <span class="file-icon">📄</span>
          <span class="file-path">${escHtml(file)}</span>
        </div>
        <div class="match-body">
          <pre class="match-code" style="white-space:pre-wrap;font-family:var(--font-mono);font-size:12.5px;">${escHtml(content)}</pre>
        </div>
      </div>`;
    feResults.innerHTML = html;
  } catch(e) {
    empty(feResults, '⚠️', 'Extraction failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

/* ═══════════════════════════════════════════════════════════
   FOLDER PICKER
═══════════════════════════════════════════════════════════ */
document.getElementById('browse-btn').addEventListener('click', async () => {
  const current = document.getElementById('repo-path').value.trim();

  if (window.pywebview) {
    // Running inside pywebview native window — use native OS folder dialog
    const chosen = await window.pywebview.api.pick_folder(current);
    if (chosen) {
      document.getElementById('repo-path').value = chosen;
      toast('Repo set: ' + chosen, 'success');
      await triggerReindex(chosen);
    }
  } else {
    // Fallback for plain browser: simple prompt
    const input = prompt('Enter repository path:', current || '.');
    if (input !== null && input.trim()) {
      const chosen = input.trim();
      document.getElementById('repo-path').value = chosen;
      toast('Repo set: ' + chosen, 'success');
      await triggerReindex(chosen);
    }
  }
});

/* ═══════════════════════════════════════════════════════════
   INDEXING PROGRESS PANEL
════════════════════════════════════════════════════════════ */
const terminalContainer   = document.getElementById('terminal-container');
const indexLogEl          = document.getElementById('index-log');
const idxStatsText        = document.getElementById('idx-stats-text');
const idxProgressBar      = document.getElementById('index-progress-bar');
const fastapiLogEl        = document.getElementById('fastapi-log');
const fastapiStatsText    = document.getElementById('fastapi-stats-text');
const termDivider         = document.getElementById('term-divider');
const indexPanel          = document.getElementById('index-panel');
const fastapiPanel        = document.getElementById('fastapi-panel');

function tsLog() {
  return new Date().toLocaleTimeString('en-GB', { hour12: false });
}

function appendLogLine(text, cls) {
  const div = document.createElement('div');
  div.className = 'log-line ' + (cls || '');
  div.innerHTML = `<span class="log-time">[${tsLog()}]</span>${escHtml(text)}`;
  indexLogEl.appendChild(div);
  indexLogEl.scrollTop = indexLogEl.scrollHeight;
}

function setProgress(pct) {
  idxProgressBar.style.width = Math.min(100, pct) + '%';
}

/* ═══════════════════════════════════════════════════════════
   TERMINAL VIEW TOGGLES
════════════════════════════════════════════════════════════ */
const termToggles = document.querySelectorAll('.term-toggle');

function setTermView(mode) {
  termToggles.forEach(b => b.classList.remove('active'));
  document.querySelector(`.term-toggle[data-target="${mode}"]`)?.classList.add('active');

  const showIndex   = (mode === 'index' || mode === 'both');
  const showFastapi = (mode === 'fastapi' || mode === 'both');

  indexPanel.style.display   = showIndex   ? 'flex' : 'none';
  fastapiPanel.style.display = showFastapi ? 'flex' : 'none';
  termDivider.style.display  = (showIndex && showFastapi) ? 'flex' : 'none';

  if (mode === 'index')   { indexPanel.style.flex = '1'; indexPanel.style.height = ''; }
  if (mode === 'fastapi') { fastapiPanel.style.flex = '1'; fastapiPanel.style.height = ''; }
  if (mode === 'both') {
    indexPanel.style.flex = '1'; indexPanel.style.height = '';
    fastapiPanel.style.flex = '1'; fastapiPanel.style.height = '';
  }
}

termToggles.forEach(btn => {
  btn.addEventListener('click', () => setTermView(btn.dataset.target));
});

document.getElementById('term-close-all').addEventListener('click', () => {
  terminalContainer.classList.remove('open');
  stopFastApiLog();
});

/* ═══════════════════════════════════════════════════════════
   SERVER STATUS PING
════════════════════════════════════════════════════════════ */
let isIndexing = false;
const statusDot = document.getElementById('status-dot');

async function triggerReindex(path) {
  if (isIndexing) return;
  isIndexing = true;
  statusDot.className = 'indexing';
  statusDot.title = 'Indexing...';

  // Open progress panel
  terminalContainer.classList.add('open');
  setTermView('index');
  indexLogEl.innerHTML = '';
  fastapiLogEl.innerHTML = '';
  setProgress(0);
  idxStatsText.textContent = 'Connecting…';
  startFastApiLog();

  appendLogLine(`Starting indexing of ${path}`, 'log-start');

  try {
    const resp = await fetch(BASE + '/reindex/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_path: path })
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Process complete SSE messages
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line in buffer

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6).trim();
        if (payload === '[DONE]') {
          appendLogLine('Indexing finished', 'log-done');
          idxStatsText.textContent = 'Complete';
          setProgress(100);
          statusDot.className = '';
          statusDot.title = 'Server ready';
          continue;
        }
        try {
          const evt = JSON.parse(payload);
          switch (evt.type) {
            case 'start':
              idxStatsText.textContent = `Scanning ${evt.total || '…'} files`;
              appendLogLine(`Found ${evt.total || '?'} candidate files`, 'log-start');
              break;
            case 'clear':
              appendLogLine('Cleared old index data', 'log-start');
              break;
            case 'file_indexed': {
              const pct = evt.total ? (evt.index / evt.total * 100) : 0;
              setProgress(pct);
              idxStatsText.textContent = `[${evt.index}/${evt.total}] ${evt.file}`;
              const syms = evt.symbols ? ` (${evt.symbols} symbols, ${evt.calls} calls)` : '';
              appendLogLine(`INDEXED  ${evt.file}  [${evt.lang || '?'}]${syms}`, 'log-indexed');
              break;
            }
            case 'file_skipped': {
              const pct = evt.total ? (evt.index / evt.total * 100) : 0;
              setProgress(pct);
              idxStatsText.textContent = `[${evt.index}/${evt.total}] ${evt.file}`;
              appendLogLine(`SKIPPED  ${evt.file}  (unchanged)`, 'log-skipped');
              break;
            }
            case 'error':
              appendLogLine(`ERROR  ${evt.file}: ${evt.message}`, 'log-error');
              break;
            case 'watcher':
              appendLogLine('File watcher started', 'log-start');
              break;
            case 'done':
              appendLogLine(
                `Done — ${evt.indexed} indexed, ${evt.skipped} skipped, ${evt.errors} errors (of ${evt.total} files)`,
                'log-done'
              );
              idxStatsText.textContent = `${evt.indexed} indexed · ${evt.skipped} skipped · ${evt.errors} errors`;
              setProgress(100);
              statusDot.className = '';
              statusDot.title = 'Server ready';
              toast(`Indexed ${evt.indexed} files ✅`, 'success');
              break;
          }
        } catch (_) { /* ignore malformed lines */ }
      }
    }
  } catch (e) {
    appendLogLine('Reindex failed: ' + e.message, 'log-error');
    statusDot.className = 'error';
    toast('Reindex failed: ' + e.message, 'error');
  } finally {
    isIndexing = false;
  }
}

document.getElementById('repo-path').addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    triggerReindex(getRepo());
  }
});

async function checkServer() {
  if (isIndexing) return;
  try {
    await fetch(BASE + '/docs');
    statusDot.className = '';
    statusDot.title = 'Server ready';
  } catch {
    statusDot.className = 'error';
    statusDot.title = 'Server unreachable';
  }
}
checkServer();
setInterval(checkServer, 10_000);

/* ═══════════════════════════════════════════════════════════
   FASTAPI LOG STREAMING
════════════════════════════════════════════════════════════ */
let _fastapiSSE = null;

function startFastApiLog() {
  if (_fastapiSSE) return;
  fastapiStatsText.textContent = 'Connecting…';
  try {
    _fastapiSSE = new EventSource(BASE + '/logs/stream');
    _fastapiSSE.onmessage = (e) => {
      try {
        const entry = JSON.parse(e.data);
        appendFastapiLine(entry);
        fastapiStatsText.textContent = `Last: ${entry.time}`;
      } catch (_) {}
    };
    _fastapiSSE.onerror = () => {
      fastapiStatsText.textContent = 'Disconnected — retrying…';
    };
    _fastapiSSE.onopen = () => {
      fastapiStatsText.textContent = 'Streaming…';
      appendFastapiLine({ time: tsLog(), level: 'INFO', name: 'server', msg: '─── FastAPI log stream connected ───' }, 'log-start');
    };
  } catch (_) {
    fastapiStatsText.textContent = 'Failed to connect';
  }
}

function stopFastApiLog() {
  if (_fastapiSSE) { _fastapiSSE.close(); _fastapiSSE = null; }
}

function appendFastapiLine(entry, cls) {
  const div = document.createElement('div');
  const levelCls = 'log-level-' + (entry.level || '');
  div.className = 'log-line ' + (cls || levelCls);
  div.innerHTML = `<span class="log-time">[${entry.time || tsLog()}]</span><span style="color:var(--text-muted);margin-right:4px;">[${entry.level || 'INFO'}]</span>${escHtml(entry.msg || '')}`;
  fastapiLogEl.appendChild(div);
  fastapiLogEl.scrollTop = fastapiLogEl.scrollHeight;
}

/* ═══════════════════════════════════════════════════════════
   RESIZABLE TERMINAL DIVIDER (drag to resize panels)
════════════════════════════════════════════════════════════ */
{
  let dragging = false;
  let startY = 0;
  let startTopH = 0;
  let startBotH = 0;

  termDivider.addEventListener('mousedown', (e) => {
    e.preventDefault();
    dragging = true;
    startY = e.clientY;
    startTopH = indexPanel.getBoundingClientRect().height;
    startBotH = fastapiPanel.getBoundingClientRect().height;
    termDivider.classList.add('dragging');
    document.body.style.cursor = 'ns-resize';
    document.body.style.userSelect = 'none';
  });

  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const delta = startY - e.clientY;
    const total = startTopH + startBotH;
    const minH = 80;
    let newTop = Math.max(minH, Math.min(total - minH, startTopH + delta));
    let newBot = total - newTop;
    indexPanel.style.flex = 'none';
    indexPanel.style.height = newTop + 'px';
    fastapiPanel.style.flex = 'none';
    fastapiPanel.style.height = newBot + 'px';
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    termDivider.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });

  // Double-click divider to reset to 50/50
  termDivider.addEventListener('dblclick', () => {
    indexPanel.style.flex = '1';
    indexPanel.style.height = '';
    fastapiPanel.style.flex = '1';
    fastapiPanel.style.height = '';
  });
}
