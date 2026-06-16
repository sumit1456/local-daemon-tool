const BASE = 'http://localhost:8000';

async function api(path, opts = {}) {
  const r = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    const msg = Array.isArray(err.detail)
      ? err.detail.map(d => d.msg || JSON.stringify(d)).join('; ')
      : (typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail));
    throw new Error(msg || r.statusText);
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
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function getRepo() {
  let v = document.getElementById('repo-path').value.trim();
  if (v.startsWith('"') && v.endsWith('"')) v = v.slice(1, -1);
  return v || '.';
}

/* ═══════════════════════════════════════════════════════════
   SMART AUTOCOMPLETE ENGINE
   Supports: file paths, symbol names, directories, packages
═══════════════════════════════════════════════════════════ */

// Cache to avoid duplicate API calls
const _acCache = {};

// Active dropdown tracker (close others when one opens)
let _acActive = null;

function _acDebounce(fn, delay = 220) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), delay); };
}

function _highlightMatch(text, query) {
  if (!query) return escHtml(text);
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return escHtml(text).replace(new RegExp(`(${escaped})`, 'gi'), '<em>$1</em>');
}

function _acFileIcon(path) {
  const ext = (path || '').split('.').pop().toLowerCase();
  const map = { py:'🐍', js:'🟨', ts:'🔷', java:'☕', go:'🐹', rs:'🦀',
                html:'🌐', css:'🎨', json:'📋', md:'📝', txt:'📄',
                yaml:'⚙️', yml:'⚙️', toml:'⚙️', sh:'💻' };
  return map[ext] || '📄';
}

function _acKindIcon(kind) {
  return { function:'ƒ', class:'◆', method:'⬡', interface:'⬢' }[kind] || '•';
}

/**
 * Create a smart autocomplete on an <input> element.
 *
 * @param {HTMLInputElement} input   - The input to attach to
 * @param {Object}           opts
 *   opts.type     - 'file' | 'symbol' | 'dir' | 'package'
 *   opts.onSelect - callback(value, item) when user picks an item
 *   opts.delay    - debounce ms (default 220)
 */
function attachAutocomplete(input, opts = {}) {
  const { type = 'file', onSelect = null, delay = 220, multi = false } = opts;

  function getCurrentQuery() {
    const val = input.value;
    if (multi) {
      const parts = val.split(',');
      return parts[parts.length - 1].trim();
    }
    return val.trim();
  }

  // Create dropdown element inside the parent .search-input-wrap
  const wrap = input.closest('.search-input-wrap');
  if (!wrap) return;

  const dropdown = document.createElement('div');
  dropdown.className = 'ac-dropdown';
  dropdown.setAttribute('role', 'listbox');
  wrap.appendChild(dropdown);

  let _items = [];
  let _selIdx = -1;
  let _open = false;
  let _lastQ = '';

  function openDropdown() {
    if (_acActive && _acActive !== dropdown) {
      _acActive.classList.remove('open');
    }
    dropdown.classList.add('open');
    _acActive = dropdown;
    _open = true;
  }

  function closeDropdown() {
    dropdown.classList.remove('open');
    _open = false;
    _selIdx = -1;
    if (_acActive === dropdown) _acActive = null;
  }

  function selectIdx(idx) {
    const rows = dropdown.querySelectorAll('.ac-item');
    rows.forEach(r => r.classList.remove('ac-selected'));
    if (idx >= 0 && idx < rows.length) {
      rows[idx].classList.add('ac-selected');
      rows[idx].scrollIntoView({ block: 'nearest' });
      _selIdx = idx;
    }
  }

  function renderItems(items, query) {
    _items = items;
    _selIdx = -1;
    if (!items.length) {
      dropdown.innerHTML = `<div class="ac-empty">No results for "${escHtml(query)}"</div>`;
      openDropdown();
      return;
    }

    dropdown.innerHTML = items.map((item, i) => {
      let icon = '', kindBadge = '', mainText = '', subText = '';

      if (type === 'file') {
        const basename = item.value.split(/[/\\]/).pop();
        const dirPart  = item.value.replace(/[/\\][^/\\]+$/, '');
        icon      = `<span class="ac-item-icon">${_acFileIcon(item.value)}</span>`;
        kindBadge = `<span class="ac-item-kind ac-kind-file">FILE</span>`;
        mainText  = _highlightMatch(basename, query);
        subText   = dirPart !== item.value ? escHtml(dirPart) : '';
      } else if (type === 'symbol') {
        const kindMap = { function:'ac-kind-function', class:'ac-kind-class',
                          method:'ac-kind-method', interface:'ac-kind-method' };
        icon      = `<span class="ac-item-icon">${_acKindIcon(item.kind)}</span>`;
        kindBadge = `<span class="ac-item-kind ${kindMap[item.kind] || 'ac-kind-file'}">${item.kind}</span>`;
        mainText  = _highlightMatch(item.value, query);
        subText   = item.file ? escHtml(item.file.split(/[/\\]/).pop()) : '';
      } else if (type === 'dir') {
        icon      = `<span class="ac-item-icon">📁</span>`;
        kindBadge = `<span class="ac-item-kind ac-kind-dir">DIR</span>`;
        mainText  = _highlightMatch(item.value, query);
        subText   = '';
      } else if (type === 'package') {
        icon      = `<span class="ac-item-icon">📦</span>`;
        kindBadge = `<span class="ac-item-kind ac-kind-pkg">PKG</span>`;
        mainText  = _highlightMatch(item.value, query);
        subText   = '';
      }

      return `<div class="ac-item" role="option" data-idx="${i}">
        ${icon}
        <div class="ac-item-main">
          <span class="ac-item-name">${mainText}</span>
          ${subText ? `<span class="ac-item-sub">${subText}</span>` : ''}
        </div>
        ${kindBadge}
      </div>`;
    }).join('');

    // Click handler
    dropdown.querySelectorAll('.ac-item').forEach(el => {
      el.addEventListener('mousedown', e => {
        e.preventDefault(); // don't blur input
        const idx = parseInt(el.dataset.idx);
        pickItem(idx);
      });
    });

    openDropdown();
  }

  function pickItem(idx) {
    const item = _items[idx];
    if (!item) return;
    if (multi) {
      const parts = input.value.split(',');
      parts[parts.length - 1] = (parts.length > 1 ? ' ' : '') + item.value;
      input.value = parts.join(',') + ', ';
    } else {
      input.value = item.value;
    }
    closeDropdown();
    if (onSelect) onSelect(item.value, item);
    input.dispatchEvent(new Event('input'));
  }

  // ── Fetch logic per type ──
  async function fetchSuggestions(query) {
    const cacheKey = `${type}:${query}`;
    if (_acCache[cacheKey]) return _acCache[cacheKey];

    let items = [];
    try {
      if (type === 'file') {
        const q = query || '*';
        const params = new URLSearchParams({ pattern: q, root: getRepo() });
        const data = await fetch(`${BASE}/search/file?${params}`).then(r => r.json());
        items = (Array.isArray(data) ? data : []).map(f => ({ value: f }));
      } else if (type === 'symbol') {
        if (query.length < 2) return [];
        const params = new URLSearchParams({ name: query });
        const data = await fetch(`${BASE}/search/symbol?${params}`).then(r => r.json());
        items = (Array.isArray(data) ? data : []).map(s => ({
          value: s.name, kind: s.kind, file: s.file,
          line_start: s.line_start, line_end: s.line_end
        }));
      } else if (type === 'dir' || type === 'package') {
        // Derive dirs/packages from all files in the repo (cache the file list to avoid redundant requests)
        const repo = getRepo();
        const cacheFileKey = `all-files:${repo}`;
        let files = _acCache[cacheFileKey];
        if (!files) {
          const params = new URLSearchParams({ pattern: '*', root: repo });
          files = await fetch(`${BASE}/search/file?${params}`)
            .then(r => r.json())
            .catch(() => []);
          _acCache[cacheFileKey] = files;
        }
        const seen = new Set();
        if (Array.isArray(files)) {
          if (type === 'dir') {
            files.forEach(f => {
              const parts = f.replace(/\\/g, '/').split('/');
              // collect all parent directories
              for (let i = 1; i < parts.length; i++) {
                const d = parts.slice(0, i).join('/');
                if (d && !seen.has(d)) { seen.add(d); items.push({ value: d }); }
              }
            });
          } else {
            // packages: dot-notation of directory paths containing __init__.py
            files.forEach(f => {
              const norm = f.replace(/\\/g, '/');
              if (norm.endsWith('__init__.py')) {
                const pkg = norm.replace('/__init__.py', '').replace(/\//g, '.');
                if (!seen.has(pkg)) { seen.add(pkg); items.push({ value: pkg }); }
              }
            });
          }
        }
        if (query) {
          items = items.filter(it => it.value.toLowerCase().includes(query.toLowerCase()));
        }
      }
    } catch (_) {}

    _acCache[cacheKey] = items;
    return items;
  }

  const debouncedFetch = _acDebounce(async (query) => {
    if (!query && type !== 'file') { closeDropdown(); return; }
    dropdown.innerHTML = `<div class="ac-loading">Searching…</div>`;
    openDropdown();
    const items = await fetchSuggestions(query);
    // Only render if still the same query
    if (getCurrentQuery() === _lastQ) renderItems(items, query);
  }, delay);

  // ── Event listeners ──
  input.addEventListener('input', () => {
    _lastQ = getCurrentQuery();
    if (!_lastQ && type !== 'file') { closeDropdown(); return; }
    debouncedFetch(_lastQ);
  });

  input.addEventListener('focus', () => {
    _lastQ = getCurrentQuery();
    if (_lastQ || type === 'file') debouncedFetch(_lastQ);
  });

  input.addEventListener('keydown', e => {
    if (!_open) return;
    const rows = dropdown.querySelectorAll('.ac-item');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectIdx(Math.min(_selIdx + 1, rows.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectIdx(Math.max(_selIdx - 1, 0));
    } else if (e.key === 'Enter') {
      if (_selIdx >= 0) { e.preventDefault(); pickItem(_selIdx); }
      else closeDropdown();
    } else if (e.key === 'Escape') {
      closeDropdown();
    } else if (e.key === 'Tab') {
      if (_selIdx >= 0) { e.preventDefault(); pickItem(_selIdx); }
      else closeDropdown();
    }
  });

  input.addEventListener('blur', () => {
    // Delay so mousedown can fire first
    setTimeout(closeDropdown, 160);
  });
}

/* ── Attach autocomplete to all relevant inputs ── */
function initAllAutocompletes() {
  const FILE_INPUTS = [
    { id: 'edit-file',  type: 'file' },
    { id: 'fe-file',    type: 'file' },
    { id: 'ig-file',    type: 'file' },
    { id: 'ff-pattern', type: 'file' },
    { id: 'idx-files',  type: 'file', multi: true },
    { id: 'ov-files',   type: 'file', multi: true },
  ];
  const SYMBOL_INPUTS = [
    { id: 'ss-name',    type: 'symbol' },
    { id: 'cg-symbol',  type: 'symbol' },
    { id: 'ia-symbol',  type: 'symbol' },
    { id: 'te-symbol',  type: 'symbol' },
    { id: 'fh-symbol',  type: 'symbol' },
    { id: 'sf-symbol',  type: 'symbol' },
    { id: 'ref-symbol', type: 'symbol' },
  ];
  const DIR_INPUTS = [
    { id: 'idx-dir',    type: 'dir' },
    { id: 'ov-dir',     type: 'dir' },
    { id: 'cg-dir',     type: 'dir' },
  ];
  const PKG_INPUTS = [
    { id: 'idx-package', type: 'package' },
    { id: 'ov-package',  type: 'package' },
    { id: 'cg-package',  type: 'package' },
  ];

  [...FILE_INPUTS, ...SYMBOL_INPUTS, ...DIR_INPUTS, ...PKG_INPUTS].forEach(cfg => {
    const el = document.getElementById(cfg.id);
    if (!el) return;
    attachAutocomplete(el, {
      type: cfg.type,
      multi: cfg.multi || false,
      onSelect: (val, item) => {
        // Extra side effects per input
        if (cfg.id === 'edit-file') {
          const ext = val.split('.').pop().toLowerCase();
          setEditorLang(ext);
        }
        if (cfg.id === 'fe-file') {
          const feLineStart = document.getElementById('fe-line-start');
          const feLineEnd   = document.getElementById('fe-line-end');
          if (feLineStart && !feLineStart.value) feLineStart.value = '1';
          if (feLineEnd && !feLineEnd.value)   feLineEnd.value   = '100';
        }
      }
    });
  });

  // Multi-value file input: idx-files (comma separated) — simple datalist-style
  // (not attaching full AC since it's comma-separated, but could be extended)
}

// Also attach autocomplete for ig-module (module name — package style)
function initModuleAutocomplete() {
  const el = document.getElementById('ig-module');
  if (!el) return;
  attachAutocomplete(el, { type: 'package' });
}

// Close any open dropdown when clicking outside
document.addEventListener('mousedown', e => {
  if (_acActive && !_acActive.contains(e.target)) {
    const wrap = _acActive.closest('.search-input-wrap');
    if (!wrap || !wrap.contains(e.target)) _acActive.classList.remove('open');
  }
});

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

  // Auto-load data for pages that benefit from it
  if (pageName === 'index') loadIndex();
  if (pageName === 'overview') loadOverview();
  if (pageName === 'call-graph') loadCallGraphSymbols();
  if (pageName === 'function-extract') loadFunctionExtractFiles();
  if (pageName === 'import-graph') loadImportGraphFiles();
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
            <span class="file-path" onclick="event.stopPropagation(); fillExtract('${escHtml(m.file)}',${m.line},${m.line + 10})">${escHtml(m.file)}</span>
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
              <span class="file-path" onclick="event.stopPropagation(); fillExtract('${escHtml(m.file)}',${m.line},${m.line + 10})">${escHtml(m.file)}</span>
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
        <div class="symbol-card" onclick="fillExtract('${escHtml(s.file)}',${s.line_start},${s.line_end})">
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
      html += `<div class="file-item" onclick="fillExtract('${escHtml(f)}', 1, 50)">${icon} ${escHtml(f)}</div>`;
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
   SYMBOL CHIPS — populate clickable symbol suggestions
═══════════════════════════════════════════════════════════ */
let _cgSymbolsLoaded = false;

async function loadCallGraphSymbols() {
  if (_cgSymbolsLoaded) return;
  const chipsContainer = document.getElementById('cg-symbol-chips');
  if (!chipsContainer) return;

  try {
    const data = await api('/search/index?limit=250&q=.');
    const files = data.files || [];
    if (!files || files.length === 0) return;

    // Collect all symbols, sort by kind importance
    const allSymbols = [];
    files.forEach(item => {
      (item.symbols || []).forEach(s => {
        if (s.kind === 'function' || s.kind === 'class') {
          allSymbols.push(s);
        }
      });
    });

    // Sort: classes first, then functions, limit to 30
    allSymbols.sort((a, b) => {
      if (a.kind === 'class' && b.kind !== 'class') return -1;
      if (b.kind === 'class' && a.kind !== 'class') return 1;
      return a.name.localeCompare(b.name);
    });

    const top = allSymbols.slice(0, 30);
    chipsContainer.innerHTML = top.map(s => {
      const kindLabel = s.kind === 'class' ? 'class' : 'fn';
      return `<span class="symbol-chip" onclick="document.getElementById('cg-symbol').value='${escHtml(s.name)}'"><span class="chip-kind">${kindLabel}</span>${escHtml(s.name)}</span>`;
    }).join('');

    _cgSymbolsLoaded = true;
  } catch (_) {}
}

/* ═══════════════════════════════════════════════════════════
   FILL FUNCTION EXTRACT from index/symbol clicks
═══════════════════════════════════════════════════════════ */
function fillExtract(file, lineStart, lineEnd) {
  document.getElementById('fe-file').value = file;
  document.getElementById('fe-line-start').value = lineStart;
  document.getElementById('fe-line-end').value = lineEnd;
  navigateToPage('function-extract');
  toast(`Loaded ${file}:${lineStart}-${lineEnd}`, 'success');
}

/* ═══════════════════════════════════════════════════════════
   POPULATE FILE DATALIST for Function Extract
═══════════════════════════════════════════════════════════ */
let _feFilesLoaded = false;

async function loadFunctionExtractFiles() {
  if (_feFilesLoaded) return;
  const datalist = document.getElementById('fe-file-list');
  if (!datalist) return;

  try {
    const data = await api('/search/index?');
    const files = data.files || [];
    if (!files || files.length === 0) return;

    datalist.innerHTML = files.map(item => 
      `<option value="${escHtml(item.file)}">`
    ).join('');

    _feFilesLoaded = true;
  } catch (_) {}
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
   BUILD / TEST / LINT (Sandbox)
═══════════════════════════════════════════════════════════ */
const buildOutput    = document.getElementById('build-output');
const sandboxStatus  = document.getElementById('sandbox-status-text');

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

async function loadSandboxStatus() {
  try {
    const d = await api('/sandbox/status');
    const stack = d.detected_stack || 'unknown';
    sandboxStatus.textContent = `Stack: ${stack}  |  Repo: ${d.repo || '?'}`;
  } catch(e) {
    sandboxStatus.textContent = 'Stack: unreachable';
  }
}

async function setupSandbox() {
  buildOutput.innerHTML = `<span class="out-label">▶ Setting up sandbox…</span>\n`;
  try {
    const d = await api('/sandbox/setup', { method: 'POST' });
    setBuildOutput('setup_sandbox', d);
    loadSandboxStatus();
  } catch(e) {
    buildOutput.innerHTML += `<span class="out-err">Error: ${escHtml(e.message)}</span>`;
    toast('setup_sandbox error: ' + e.message, 'error');
  }
}

async function runCompile() {
  buildOutput.innerHTML = `<span class="out-label">▶ Compiling project…</span>\n`;
  try {
    const d = await api('/sandbox/compile', { method: 'POST' });
    setBuildOutput('compile_project', d);
  } catch(e) {
    buildOutput.innerHTML += `<span class="out-err">Error: ${escHtml(e.message)}</span>`;
    toast('compile_project error: ' + e.message, 'error');
  }
}

async function runTests() {
  const path = document.getElementById('test-path').value.trim();
  buildOutput.innerHTML = `<span class="out-label">▶ Running tests…</span>\n`;
  try {
    const params = new URLSearchParams();
    if (path) params.append('path', path);
    const d = await api(`/sandbox/test?${params}`, {
      method: 'POST',
    });
    setBuildOutput('run_tests', d);
  } catch(e) {
    buildOutput.innerHTML += `<span class="out-err">Error: ${escHtml(e.message)}</span>`;
    toast('run_tests error: ' + e.message, 'error');
  }
}

async function runLint() {
  const file = document.getElementById('lint-file').value.trim();
  if (!file) { toast('Enter a file path to lint', 'error'); return; }
  buildOutput.innerHTML = `<span class="out-label">▶ Linting file…</span>\n`;
  try {
    const d = await api(`/sandbox/lint?file=${encodeURIComponent(file)}`);
    setBuildOutput('check_syntax', d);
  } catch(e) {
    buildOutput.innerHTML += `<span class="out-err">Error: ${escHtml(e.message)}</span>`;
    toast('check_syntax error: ' + e.message, 'error');
  }
}

async function installDeps() {
  buildOutput.innerHTML = `<span class="out-label">▶ Installing dependencies…</span>\n`;
  try {
    const d = await api('/sandbox/install-deps', { method: 'POST' });
    setBuildOutput('install_deps', d);
    loadSandboxStatus();
  } catch(e) {
    buildOutput.innerHTML += `<span class="out-err">Error: ${escHtml(e.message)}</span>`;
    toast('install_deps error: ' + e.message, 'error');
  }
}

document.getElementById('sandbox-status-btn')?.addEventListener('click', loadSandboxStatus);
document.getElementById('sandbox-setup-btn')?.addEventListener('click', setupSandbox);
document.getElementById('sandbox-deps-btn')?.addEventListener('click', installDeps);
document.getElementById('compile-run-btn')?.addEventListener('click', runCompile);
document.getElementById('test-run-btn')?.addEventListener('click', runTests);
document.getElementById('lint-run-btn')?.addEventListener('click', runLint);

/* ═══════════════════════════════════════════════════════════
   INDEX PAGE
═══════════════════════════════════════════════════════════ */
const idxResults = document.getElementById('idx-results');

document.getElementById('idx-load-btn')?.addEventListener('click', loadIndex);
document.getElementById('idx-files')?.addEventListener('keydown', e => { if(e.key==='Enter') loadIndex(); });
document.getElementById('idx-dir')?.addEventListener('keydown', e => { if(e.key==='Enter') loadIndex(); });
document.getElementById('idx-package')?.addEventListener('keydown', e => { if(e.key==='Enter') loadIndex(); });

async function loadIndex() {
  const filesInput = document.getElementById('idx-files').value.trim();
  const files = filesInput ? filesInput.split(',').map(f => f.trim()) : null;
  const dirVal = document.getElementById('idx-dir')?.value.trim() || null;
  const pkgVal = document.getElementById('idx-package')?.value.trim() || null;
  
  loading(idxResults);
  try {
    const params = new URLSearchParams();
    if (files && files.length > 0) {
      files.forEach(f => params.append('files', f));
    }
    if (dirVal) params.append('dir', dirVal);
    if (pkgVal) params.append('package', pkgVal);
    const data = await api(`/search/index?${params}`);

    if (data.mode === 'summary') {
      let html = `
        <div class="summary-stats">
          <div class="summary-stat">
            <span class="stat-icon">📄</span>
            <div><div class="stat-value">${data.total_files}</div><div class="stat-label">Files</div></div>
          </div>
          <div class="summary-stat">
            <span class="stat-icon">🔣</span>
            <div><div class="stat-value">${data.total_symbols}</div><div class="stat-label">Symbols</div></div>
          </div>
          ${Object.entries(data.symbol_kinds || {}).slice(0, 4).map(([kind, count]) => `
            <div class="summary-stat">
              <span class="stat-icon">${{function:'ƒ',class:'◆',method:'→',interface:'◇'}[kind] || '·'}</span>
              <div><div class="stat-value">${count}</div><div class="stat-label">${kind}s</div></div>
            </div>
          `).join('')}
        </div>`;

      if (data.languages && Object.keys(data.languages).length) {
        html += `<div style="margin-bottom:16px;"><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">Languages</h3>
          <div style="display:flex;flex-wrap:wrap;gap:6px;">
            ${Object.entries(data.languages).map(([lang, count]) => `<span style="background:var(--bg-tertiary);padding:4px 10px;border-radius:12px;font-size:12px;color:var(--text-secondary);">${escHtml(lang)}: ${count}</span>`).join('')}
          </div></div>`;
      }

      if (data.top_dirs && data.top_dirs.length) {
        html += `<div style="margin-bottom:16px;"><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">Directories</h3>`;
        data.top_dirs.forEach(d => {
          html += `<div class="match-card" style="cursor:pointer;" onclick="document.getElementById('idx-dir').value='${escHtml(d.path)}'; loadIndex();">
            <div class="match-header"><span class="file-icon">📁</span><span class="file-path">${escHtml(d.path)}</span></div>
            <div class="match-body" style="padding:6px 14px;font-size:12px;color:var(--text-muted);">${d.files} files, ${d.symbols} symbols</div>
          </div>`;
        });
        html += `</div>`;
      }

      if (data.top_files && data.top_files.length) {
        html += `<div><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">Top Files</h3>`;
        data.top_files.forEach(f => {
          html += `<div class="match-card">
            <div class="match-header"><span class="file-icon">📄</span><span class="file-path">${escHtml(f.file)}</span></div>
            <div class="match-body" style="padding:6px 14px;font-size:12px;color:var(--text-muted);">${f.symbols} symbols</div>
          </div>`;
        });
        html += `</div>`;
      }

      idxResults.innerHTML = html;
      return;
    }

    // Detailed mode
    const detailedFiles = data.files || [];
    if (!detailedFiles || detailedFiles.length === 0) {
      empty(idxResults, '📋', 'No index data', 'No indexed files found for the current filters.');
      return;
    }

    const totalFiles = data.total || detailedFiles.length;
    const totalSymbols = detailedFiles.reduce((sum, item) => sum + (item.symbols?.length || 0), 0);
    const kindCounts = {};
    detailedFiles.forEach(item => {
      (item.symbols || []).forEach(s => {
        kindCounts[s.kind] = (kindCounts[s.kind] || 0) + 1;
      });
    });

    let html = `
      <div class="summary-stats">
        <div class="summary-stat">
          <span class="stat-icon">📄</span>
          <div><div class="stat-value">${totalFiles}</div><div class="stat-label">Files</div></div>
        </div>
        <div class="summary-stat">
          <span class="stat-icon">🔣</span>
          <div><div class="stat-value">${totalSymbols}</div><div class="stat-label">Symbols</div></div>
        </div>
        ${Object.entries(kindCounts).slice(0, 4).map(([kind, count]) => `
          <div class="summary-stat">
            <span class="stat-icon">${{function:'ƒ',class:'◆',method:'→',interface:'◇'}[kind] || '·'}</span>
            <div><div class="stat-value">${count}</div><div class="stat-label">${kind}s</div></div>
          </div>
        `).join('')}
      </div>`;

    detailedFiles.forEach(item => {
      const symbols = item.symbols || [];
      const symbolHtml = symbols.map(s => {
        const kindClass = { function:'kind-function', class:'kind-class', method:'kind-method', interface:'kind-interface' }[s.kind] || 'kind-default';
        return `<span class="symbol-kind ${kindClass}" style="font-size:10px;padding:2px 6px;margin-right:4px;cursor:pointer;" onclick="fillExtract('${escHtml(item.file)}',${s.line_start},${s.line_end})">${s.kind}</span><span style="font-family:var(--font-mono);font-size:12px;color:var(--text-secondary);cursor:pointer;" onclick="fillExtract('${escHtml(item.file)}',${s.line_start},${s.line_end})">${escHtml(s.name)}</span>`;
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
document.getElementById('ov-dir').addEventListener('keydown', e => { if(e.key==='Enter') loadOverview(); });
document.getElementById('ov-package').addEventListener('keydown', e => { if(e.key==='Enter') loadOverview(); });

async function loadOverview() {
  const filesInput = document.getElementById('ov-files').value.trim();
  const files = filesInput ? filesInput.split(',').map(f => f.trim()) : null;
  const dirVal = document.getElementById('ov-dir')?.value.trim() || null;
  const pkgVal = document.getElementById('ov-package')?.value.trim() || null;
  
  loading(ovResults);
  try {
    const params = new URLSearchParams();
    if (files && files.length > 0) {
      files.forEach(f => params.append('files', f));
    }
    if (dirVal) params.append('dir', dirVal);
    if (pkgVal) params.append('package', pkgVal);
    const data = await api(`/search/overview?${params}`);
    
    if (!data) {
      empty(ovResults, '🗺', 'No overview data', 'No indexed data found for the current filters.');
      return;
    }

    if (data.mode === 'summary') {
      let html = `
        <div class="summary-stats">
          <div class="summary-stat">
            <span class="stat-icon">📄</span>
            <div><div class="stat-value">${data.total_files}</div><div class="stat-label">Files</div></div>
          </div>
          <div class="summary-stat">
            <span class="stat-icon">🔣</span>
            <div><div class="stat-value">${data.total_symbols}</div><div class="stat-label">Symbols</div></div>
          </div>
          <div class="summary-stat">
            <span class="stat-icon">🔗</span>
            <div><div class="stat-value">${data.call_graph?.total_edges || 0}</div><div class="stat-label">Call Edges</div></div>
          </div>
          <div class="summary-stat">
            <span class="stat-icon">📞</span>
            <div><div class="stat-value">${data.call_graph?.unique_callers || 0}</div><div class="stat-label">Callers</div></div>
          </div>
          <div class="summary-stat">
            <span class="stat-icon">📥</span>
            <div><div class="stat-value">${data.call_graph?.unique_callees || 0}</div><div class="stat-label">Callees</div></div>
          </div>
        </div>`;

      if (data.languages && Object.keys(data.languages).length) {
        html += `<div style="margin-bottom:16px;"><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">Languages</h3>
          <div style="display:flex;flex-wrap:wrap;gap:6px;">
            ${Object.entries(data.languages).map(([lang, count]) => `<span style="background:var(--bg-tertiary);padding:4px 10px;border-radius:12px;font-size:12px;color:var(--text-secondary);">${escHtml(lang)}: ${count}</span>`).join('')}
          </div></div>`;
      }

      if (data.top_dirs && data.top_dirs.length) {
        html += `<div style="margin-bottom:16px;"><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">Directories</h3>`;
        data.top_dirs.forEach(d => {
          html += `<div class="match-card">
            <div class="match-header"><span class="file-icon">📁</span><span class="file-path">${escHtml(d.path)}</span></div>
            <div class="match-body" style="padding:6px 14px;font-size:12px;color:var(--text-muted);">${d.files} files, ${d.symbols} symbols</div>
          </div>`;
        });
        html += `</div>`;
      }

      const cg = data.call_graph || {};
      if (cg.top_connected_files && cg.top_connected_files.length) {
        html += `<div style="margin-bottom:16px;"><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">Most Connected Files</h3>`;
        cg.top_connected_files.forEach(f => {
          html += `<div class="match-card">
            <div class="match-header"><span class="file-icon">📄</span><span class="file-path">${escHtml(f.file)}</span></div>
            <div class="match-body" style="padding:6px 14px;font-size:12px;color:var(--text-muted);">${f.outgoing_calls} outgoing calls</div>
          </div>`;
        });
        html += `</div>`;
      }

      if (cg.top_callers && cg.top_callers.length) {
        html += `<div style="margin-bottom:16px;"><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">Top Callers</h3>`;
        cg.top_callers.forEach(c => {
          html += `<div class="symbol-card">
            <span class="symbol-name" style="font-size:12px;">${escHtml(c.symbol)}</span>
            <span class="symbol-file" style="font-size:11px;">${c.calls} calls</span>
          </div>`;
        });
        html += `</div>`;
      }

      if (cg.top_callees && cg.top_callees.length) {
        html += `<div><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">Most Called</h3>`;
        cg.top_callees.forEach(c => {
          html += `<div class="symbol-card">
            <span class="symbol-name" style="font-size:12px;">${escHtml(c.symbol)}</span>
            <span class="symbol-file" style="font-size:11px;">called by ${c.called_by}</span>
          </div>`;
        });
        html += `</div>`;
      }

      ovResults.innerHTML = html;
      return;
    }

    // Detailed mode
    const fileCount = (data.files || []).length;
    const edgeCount = (data.edges || []).length;
    const calleeCount = Object.keys(data.callees || {}).length;
    const callerCount = Object.keys(data.callers || {}).length;

    let html = `
      <div class="summary-stats">
        <div class="summary-stat">
          <span class="stat-icon">📄</span>
          <div><div class="stat-value">${fileCount}</div><div class="stat-label">Files</div></div>
        </div>
        <div class="summary-stat">
          <span class="stat-icon">🔗</span>
          <div><div class="stat-value">${edgeCount}</div><div class="stat-label">Call Edges</div></div>
        </div>
        <div class="summary-stat">
          <span class="stat-icon">📞</span>
          <div><div class="stat-value">${calleeCount}</div><div class="stat-label">Callees</div></div>
        </div>
        <div class="summary-stat">
          <span class="stat-icon">📥</span>
          <div><div class="stat-value">${callerCount}</div><div class="stat-label">Callers</div></div>
        </div>
      </div>`;

    // Show call edges
    if (data.edges && data.edges.length > 0) {
      html += `<div style="margin-bottom:16px;"><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">Call Edges</h3>`;
      data.edges.forEach(edge => {
        html += `
          <div class="symbol-card" onclick="document.getElementById('cg-symbol').value='${escHtml(edge.caller_name || '')}'; navigateToPage('call-graph');">
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
document.getElementById('cg-dir').addEventListener('keydown', e => { if(e.key==='Enter') loadCallGraph('callers'); });
document.getElementById('cg-package').addEventListener('keydown', e => { if(e.key==='Enter') loadCallGraph('callers'); });

async function loadCallGraph(type) {
  const symbol = document.getElementById('cg-symbol').value.trim();
  const dirVal = document.getElementById('cg-dir')?.value.trim() || null;
  const pkgVal = document.getElementById('cg-package')?.value.trim() || null;
  if (!symbol) { toast('Enter a symbol name', 'error'); return; }
  
  loading(cgResults);
  try {
    const endpoint = type === 'callers' ? '/search/callers' : '/search/callees';
    const params = new URLSearchParams({ symbol_name: symbol });
    if (dirVal) params.append('dir', dirVal);
    if (pkgVal) params.append('package', pkgVal);
    const data = await api(`${endpoint}?${params}`);
    
    if (!data || data.length === 0) {
      empty(cgResults, '🔗', 'No results', `No ${type} found for symbol "${escHtml(symbol)}".`);
      return;
    }

    let html = `<div class="stats-bar"><span class="stats-badge">🔗 ${data.length} ${type}</span> for <code style="font-family:var(--font-mono);background:var(--bg-elevated);padding:2px 6px;border-radius:4px;">${escHtml(symbol)}</code></div>`;
    data.forEach(item => {
      if (type === 'callers') {
        html += `
          <div class="symbol-card" onclick="fillExtract('${escHtml(item.caller_file || '')}',${item.caller_line || 1},${(item.caller_line || 1) + 5})">
            <span class="symbol-kind kind-function">caller</span>
            <span class="symbol-name">${escHtml(item.caller_name || 'unknown')}</span>
            <span class="symbol-file">${escHtml(item.caller_file || '')}</span>
          </div>`;
      } else {
        html += `
          <div class="symbol-card" onclick="document.getElementById('cg-symbol').value='${escHtml(item.callee_name || '')}'; loadCallGraph('callers');">
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
   IMPORT GRAPH PAGE
═══════════════════════════════════════════════════════════ */
const igResults = document.getElementById('ig-results');
let _igMode = 'file-imports';

/* Mode toggle */
document.querySelectorAll('#import-mode-toggle .mode-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#import-mode-toggle .mode-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    _igMode = btn.dataset.mode;
    document.getElementById('import-file-row').style.display = _igMode === 'file-imports' ? 'flex' : 'none';
    document.getElementById('import-module-row').style.display = _igMode === 'module-importers' ? 'flex' : 'none';
  });
});

/* File imports */
document.getElementById('ig-file-btn').addEventListener('click', loadFileImports);
document.getElementById('ig-file').addEventListener('keydown', e => { if(e.key==='Enter') loadFileImports(); });

async function loadFileImports() {
  const file = document.getElementById('ig-file').value.trim();
  if (!file) { toast('Enter a file path', 'error'); return; }

  loading(igResults);
  try {
    const data = await api(`/search/imports?${new URLSearchParams({ file })}`);

    if (!data.imports || data.imports.length === 0) {
      empty(igResults, '📦', 'No imports found', `No imports found for "${escHtml(file)}".`);
      return;
    }

    let html = `<div class="stats-bar"><span class="stats-badge">📦 ${data.imports.length} import${data.imports.length!==1?'s':''}</span> from <code style="font-family:var(--font-mono);background:var(--bg-elevated);padding:2px 6px;border-radius:4px;">${escHtml(file)}</code></div>`;
    data.imports.forEach(imp => {
      const levelLabel = imp.level > 0 ? `relative (${'.'.repeat(imp.level)})` : 'absolute';
      const starBadge = imp.is_star ? '<span style="color:var(--warning);font-size:10px;margin-left:6px;">* star</span>' : '';
      html += `
        <div class="symbol-card" onclick="document.getElementById('ig-module').value='${escHtml(imp.module)}'; document.querySelectorAll('#import-mode-toggle .mode-btn').forEach(b=>b.classList.remove('active')); document.querySelector('[data-mode=module-importers]').classList.add('active'); _igMode='module-importers'; document.getElementById('import-file-row').style.display='none'; document.getElementById('import-module-row').style.display='flex'; loadModuleImporters();">
          <span class="symbol-kind kind-import">import</span>
          <span class="symbol-name">${escHtml(imp.module)}${starBadge}</span>
          <span class="symbol-file" style="font-size:11px;">${levelLabel}</span>
        </div>`;
    });
    igResults.innerHTML = html;
  } catch(e) {
    empty(igResults, '⚠️', 'Search failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

/* Module importers */
document.getElementById('ig-module-btn').addEventListener('click', loadModuleImporters);
document.getElementById('ig-module').addEventListener('keydown', e => { if(e.key==='Enter') loadModuleImporters(); });

async function loadModuleImporters() {
  const module = document.getElementById('ig-module').value.trim();
  if (!module) { toast('Enter a module name', 'error'); return; }

  loading(igResults);
  try {
    const data = await api(`/search/importers?${new URLSearchParams({ module })}`);

    if (!data || data.length === 0) {
      empty(igResults, '📦', 'No importers found', `No files import module "${escHtml(module)}".`);
      return;
    }

    let html = `<div class="stats-bar"><span class="stats-badge">📦 ${data.length} file${data.length!==1?'s':''}</span> import <code style="font-family:var(--font-mono);background:var(--bg-elevated);padding:2px 6px;border-radius:4px;">${escHtml(module)}</code></div>`;
    data.forEach(item => {
      const starBadge = item.is_star ? '<span style="color:var(--warning);font-size:10px;margin-left:6px;">* star</span>' : '';
      html += `
        <div class="symbol-card" onclick="fillExtract('${escHtml(item.file)}',1,50)">
          <span class="symbol-kind kind-function">importer</span>
          <span class="symbol-name">${escHtml(item.file)}</span>
          <span class="symbol-file" style="font-size:11px;">${escHtml(item.module)}${starBadge}</span>
        </div>`;
    });
    igResults.innerHTML = html;
  } catch(e) {
    empty(igResults, '⚠️', 'Search failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

/* Full deps (combined view) */
document.getElementById('ig-file-deps-btn').addEventListener('click', loadFileDeps);

async function loadFileDeps() {
  const file = document.getElementById('ig-file').value.trim();
  if (!file) { toast('Enter a file path', 'error'); return; }

  loading(igResults);
  try {
    const data = await api(`/search/file-deps?${new URLSearchParams({ file })}`);

    let html = `<div class="stats-bar"><span class="stats-badge">📦 Deps for ${escHtml(file)}</span></div>`;

    /* imports section */
    html += `<div style="margin-bottom:16px;"><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">📥 Imports (${(data.imports||[]).length})</h3>`;
    if (data.imports && data.imports.length > 0) {
      data.imports.forEach(imp => {
        html += `<div class="symbol-card" onclick="document.getElementById('ig-module').value='${escHtml(imp.module)}'; _igMode='module-importers'; document.getElementById('import-file-row').style.display='none'; document.getElementById('import-module-row').style.display='flex'; document.querySelectorAll('#import-mode-toggle .mode-btn').forEach(b=>b.classList.remove('active')); document.querySelector('[data-mode=module-importers]').classList.add('active'); loadModuleImporters();">
          <span class="symbol-kind kind-import">import</span>
          <span class="symbol-name">${escHtml(imp.module)}</span>
        </div>`;
      });
    } else {
      html += `<div style="color:var(--text-muted);font-size:12px;padding:8px;">No imports</div>`;
    }
    html += `</div>`;

    /* imported_by section */
    html += `<div><h3 style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">📤 Imported By (${(data.imported_by||[]).length})</h3>`;
    if (data.imported_by && data.imported_by.length > 0) {
      data.imported_by.forEach(item => {
        html += `<div class="symbol-card" onclick="fillExtract('${escHtml(item.file)}',1,50)">
          <span class="symbol-kind kind-function">importer</span>
          <span class="symbol-name">${escHtml(item.file)}</span>
          <span class="symbol-file" style="font-size:11px;">${escHtml(item.module)}</span>
        </div>`;
      });
    } else {
      html += `<div style="color:var(--text-muted);font-size:12px;padding:8px;">No files import this</div>`;
    }
    html += `</div>`;

    igResults.innerHTML = html;
  } catch(e) {
    empty(igResults, '⚠️', 'Search failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

/* Populate file datalist for import graph */
let _igFilesLoaded = false;
async function loadImportGraphFiles() {
  if (_igFilesLoaded) return;
  const datalist = document.getElementById('ig-file-list');
  if (!datalist) return;
  try {
    const data = await api('/search/index?');
    const files = data.files || [];
    datalist.innerHTML = files.map(item => `<option value="${escHtml(item.file)}">`).join('');
    _igFilesLoaded = true;
  } catch (_) {}
}

/* ═══════════════════════════════════════════════════════════
   FUNCTION EXTRACT PAGE
═══════════════════════════════════════════════════════════ */
const feResults = document.getElementById('fe-results');

document.getElementById('fe-signature-btn').addEventListener('click', () => loadFunctionExtract('signature'));
document.getElementById('fe-body-btn').addEventListener('click', () => loadFunctionExtract('body'));



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

  if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.pick_folder === 'function') {
    try {
      const chosen = await window.pywebview.api.pick_folder(current);
      if (chosen) {
        document.getElementById('repo-path').value = chosen;
        toast('Repo set: ' + chosen, 'success');
        await triggerReindex(chosen);
      }
    } catch (e) {
      console.error('pywebview pick_folder failed:', e);
      toast('Folder picker failed — type the path manually', 'error');
    }
  } else {
    // pywebview not ready yet — wait briefly then retry once
    if (window.pywebview) {
      await new Promise(r => setTimeout(r, 500));
      if (window.pywebview.api && typeof window.pywebview.api.pick_folder === 'function') {
        try {
          const chosen = await window.pywebview.api.pick_folder(current);
          if (chosen) {
            document.getElementById('repo-path').value = chosen;
            toast('Repo set: ' + chosen, 'success');
            await triggerReindex(chosen);
          }
        } catch (e) {
          console.error('pywebview pick_folder failed:', e);
          toast('Folder picker failed — type the path manually', 'error');
        }
        return;
      }
    }
    // Fallback: prompt for path input
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
              
              // Auto-start embedding if toggle is ON
              const embedToggle = document.getElementById('embedding-toggle');
              if (embedToggle && embedToggle.checked) {
                appendLogLine('Starting embeddings...', 'log-start');
                api('/search/embedding-toggle', {
                  method: 'POST',
                  body: JSON.stringify({ enabled: true })
                }).then(() => {
                  appendLogLine('Embedding generation started', 'log-indexed');
                  startEmbeddingPoll();
                }).catch(err => {
                  appendLogLine('Failed to start embedding: ' + err.message, 'log-error');
                  toast('Failed to start embedding: ' + err.message, 'error');
                });
              } else {
                stopEmbeddingPoll();
              }
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

/* ═══════════════════════════════════════════════════════════
   INIT AUTOCOMPLETE
   Called after all DOM + CodeMirror instances are ready
═══════════════════════════════════════════════════════════ */
// Use setTimeout to ensure CodeMirror & all IDs are mounted
setTimeout(() => {
  initAllAutocompletes();
  initModuleAutocomplete();

  // Docker/headless mode (no pywebview at all): hide browse button, show hint
  // pywebview is injected AFTER page load, so check again after a delay
  const browseBtn = document.getElementById('browse-btn');
  const repoPath = document.getElementById('repo-path');

  if (!window.pywebview) {
    // Not pywebview — could be headless Docker OR pywebview just hasn't loaded yet
    // Hide optimistically, pywebviewready will restore it
    browseBtn.style.display = 'none';
    repoPath.placeholder = 'e.g. /workspace/Downloads/dev-tool';
  }
}, 0);

// pywebview 5.x fires this event when window.pywebview.api is ready
window.addEventListener('pywebviewready', () => {
  console.log('pywebview API ready');
  // Restore browse button — we're in native desktop mode
  const browseBtn = document.getElementById('browse-btn');
  const repoPath = document.getElementById('repo-path');
  if (browseBtn) browseBtn.style.display = '';
  if (repoPath) repoPath.placeholder = 'C:\\path\\to\\your\\repo';
});

/* ═══════════════════════════════════════════════════════════
   EMBEDDING TOGGLE
   Lazy-load embeddings on user request
═══════════════════════════════════════════════════════════ */
let embeddingPollInterval = null;

function startEmbeddingPoll() {
  stopEmbeddingPoll();
  const embeddingStatusEl = document.getElementById('embedding-status');
  
  embeddingPollInterval = setInterval(async () => {
    try {
      const status = await api('/search/embedding-status');
      updateEmbeddingStatusText(status);
      
      if (status.current_file === 'Done' || status.error) {
        stopEmbeddingPoll();
        toast(status.error ? 'Embedding error: ' + status.error : 'Embedding complete!', status.error ? 'error' : 'success');
      }
    } catch (e) {}
  }, 1000);
}

function stopEmbeddingPoll() {
  if (embeddingPollInterval) {
    clearInterval(embeddingPollInterval);
    embeddingPollInterval = null;
  }
}

function updateEmbeddingStatusText(status) {
  const embeddingStatusEl = document.getElementById('embedding-status');
  if (!embeddingStatusEl) return;
  
  if (status.loading) {
    embeddingStatusEl.textContent = 'Loading...';
    embeddingStatusEl.style.color = 'var(--warning)';
  } else if (status.enabled) {
    const count = status.embedded_count || 0;
    const total = status.total_symbols || 0;
    if (total > 0) {
      embeddingStatusEl.textContent = `${count}/${total}`;
    } else {
      embeddingStatusEl.textContent = 'Starting...';
    }
    embeddingStatusEl.style.color = 'var(--accent)';
  } else if (status.current_file === 'Done') {
    embeddingStatusEl.textContent = 'Ready';
    embeddingStatusEl.style.color = 'var(--success)';
  } else if (status.error) {
    embeddingStatusEl.textContent = 'Error';
    embeddingStatusEl.style.color = 'var(--danger)';
  } else {
    embeddingStatusEl.textContent = 'OFF';
    embeddingStatusEl.style.color = 'var(--text-muted)';
  }
}

// Init embedding toggle
const embeddingToggle = document.getElementById('embedding-toggle');
if (embeddingToggle) {
  // Load initial status
  api('/search/embedding-status').then(status => {
    embeddingToggle.checked = status.enabled || false;
    updateEmbeddingStatusText(status);
  }).catch(() => {});

  // Toggle handler — enable/disable embedding, but only run after indexing finishes
  embeddingToggle.addEventListener('change', () => {
    const enabled = embeddingToggle.checked;
    if (!enabled) {
      stopEmbeddingPoll();
      api('/search/embedding-toggle', {
        method: 'POST',
        body: JSON.stringify({ enabled: false })
      }).catch(() => {});
      toast('Embedding stopped', 'info');
    } else if (!isIndexing) {
      // Not indexing — start embedding now
      appendLogLine('Starting embeddings...', 'log-start');
      api('/search/embedding-toggle', {
        method: 'POST',
        body: JSON.stringify({ enabled: true })
      }).then(() => {
        appendLogLine('Embedding generation started', 'log-indexed');
        startEmbeddingPoll();
        toast('Embedding started', 'success');
      }).catch(err => {
        toast('Failed to start embedding: ' + err.message, 'error');
        embeddingToggle.checked = false;
      });
    } else {
      // Indexing in progress — will start after it finishes
      toast('Embedding will start after indexing', 'info');
    }
  });
}

// Init semantic search
const semanticSearchBtn = document.getElementById('semantic-search-btn');
const semanticQueryInput = document.getElementById('semantic-query');
const semanticLimitInput = document.getElementById('semantic-limit');
const semanticResults = document.getElementById('semantic-results');

if (semanticSearchBtn) {
  semanticSearchBtn.addEventListener('click', async () => {
    const query = semanticQueryInput.value.trim();
    if (!query) {
      toast('Enter a search query', 'error');
      return;
    }

    const limit = parseInt(semanticLimitInput.value) || 10;
    loading(semanticResults);

    try {
      const data = await api(`/search/semantic?q=${encodeURIComponent(query)}&limit=${limit}`);
      
      if (!data.results || data.results.length === 0) {
        empty(semanticResults, '🧠', 'No results found', 'Try a different query or enable embeddings first.');
        return;
      }

      let html = `<div class="stats-bar"><span class="stats-badge">${data.results.length} results</span><span>Query: ${escHtml(query)}</span></div>`;
      
      for (const r of data.results) {
        const distance = r.distance.toFixed(3);
        const similarity = ((1 - r.distance) * 100).toFixed(1);
        html += `
          <div class="symbol-card" data-file="${escHtml(r.file)}" data-line="${r.line_start || 0}" data-name="${escHtml(r.name)}" data-kind="${escHtml(r.kind || 'function')}">
            <span class="symbol-kind kind-${r.kind || 'function'}">${r.kind || 'func'}</span>
            <span class="symbol-name">${escHtml(r.name)}</span>
            <span class="symbol-file">${escHtml(r.file)}</span>
            <span class="symbol-lines" title="Similarity: ${similarity}%">${similarity}%</span>
          </div>`;
      }
      
      semanticResults.innerHTML = html;

      // Add click handlers to fetch and show code
      semanticResults.querySelectorAll('.symbol-card').forEach(card => {
        card.addEventListener('click', async () => {
          const file = card.dataset.file;
          const line = parseInt(card.dataset.line) || 0;
          const name = card.dataset.name;
          const kind = card.dataset.kind;

          try {
            const data = await api(`/search/file-read?file=${encodeURIComponent(file)}`);
            if (data.content) {
              const lang = detectLang(file);
              openCodePanel(`${name} (${file})`, data.content, lang);
            }
          } catch (err) {
            toast('Failed to load file: ' + err.message, 'error');
          }
        });
      });
    } catch (err) {
      toast('Semantic search failed: ' + err.message, 'error');
      empty(semanticResults, '❌', 'Search failed', err.message);
    }
  });

  // Enter key handler
  if (semanticQueryInput) {
    semanticQueryInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') semanticSearchBtn.click();
    });
  }
}

/* ═══════════════════════════════════════════════════════════
   IMPACT ANALYSIS PAGE
═══════════════════════════════════════════════════════════ */
const iaResults = document.getElementById('ia-results');

document.getElementById('ia-analyze-btn').addEventListener('click', () => loadImpact('impact'));
document.getElementById('ia-blast-btn').addEventListener('click', () => loadImpact('blast'));
document.getElementById('ia-symbol').addEventListener('keydown', e => { if(e.key==='Enter') loadImpact('impact'); });

async function loadImpact(type) {
  const symbol = document.getElementById('ia-symbol').value.trim();
  if (!symbol) { toast('Enter a symbol name', 'error'); return; }

    loading(iaResults);
  try {
    const endpoint = type === 'blast' ? '/search/blast-radius' : '/search/impact-analysis';
    const paramName = type === 'blast' ? 'symbol' : 'symbol_name';
    const params = new URLSearchParams({ [paramName]: symbol });
    const data = await api(`${endpoint}?${params}`);

    if (!data || (Array.isArray(data) && data.length === 0) || (!data.callers && !data.references && !data.direct_callers && !data.callers_by_depth)) {
      empty(iaResults, '💥', 'No impact data', `No impact data found for "${escHtml(symbol)}".`);
      return;
    }

    let html = `<div class="stats-bar"><span class="stats-badge">💥 ${type === 'blast' ? 'Blast Radius' : 'Impact Analysis'}</span> for <code style="font-family:var(--font-mono);background:var(--bg-elevated);padding:2px 6px;border-radius:4px;">${escHtml(symbol)}</code></div>`;

    // Blast radius format
    if (data.callers_by_depth) {
      html += `<div class="summary-stats">
        <div class="summary-stat"><span class="stat-icon">📊</span><div><div class="stat-value">${data.total_affected || 0}</div><div class="stat-label">Total Affected</div></div></div>
        <div class="summary-stat"><span class="stat-icon">📞</span><div><div class="stat-value">${Object.keys(data.callers_by_depth).length}</div><div class="stat-label">Depth Levels</div></div></div>
      </div>`;

      Object.entries(data.callers_by_depth).sort((a,b) => Number(a[0]) - Number(b[0])).forEach(([depth, funcs]) => {
        html += `<div style="margin-bottom:12px;"><h3 style="font-size:13px;font-weight:600;color:var(--accent);margin-bottom:6px;">Depth ${depth} (${funcs.length} functions)</h3>`;
        funcs.forEach(f => {
          html += `<div class="symbol-card" onclick="fillExtract('${escHtml(f.file || '')}',${f.line_start || 1},${(f.line_start || 1) + 5})">
            <span class="symbol-kind kind-function">L${depth}</span>
            <span class="symbol-name">${escHtml(f.name || f)}</span>
            <span class="symbol-file">${escHtml(f.file || '')}</span>
          </div>`;
        });
        html += `</div>`;
      });
    }

    // Impact analysis format
    if (data.callers && data.callers.length > 0) {
      html += `<div style="margin-bottom:12px;"><h3 style="font-size:13px;font-weight:600;color:var(--accent);margin-bottom:6px;">Direct Callers (${data.direct_callers})</h3>`;
      data.callers.forEach(c => {
        html += `<div class="symbol-card" onclick="fillExtract('${escHtml(c.file || '')}',${c.line || 1},${(c.line || 1) + 5})">
          <span class="symbol-kind kind-function">caller</span>
          <span class="symbol-name">${escHtml(c.name || c)}</span>
          <span class="symbol-file">${escHtml(c.file || '')}</span>
        </div>`;
      });
      html += `</div>`;
    }

    if (data.all_references) {
      html += `<div style="margin-bottom:12px;"><h3 style="font-size:13px;font-weight:600;color:var(--warning);margin-bottom:6px;">All References (${data.all_references.length})</h3>`;
      data.all_references.forEach(r => {
        html += `<div class="symbol-card" onclick="fillExtract('${escHtml(r.file || '')}',${r.line || 1},${(r.line || 1) + 5})">
          <span class="symbol-kind kind-import">ref</span>
          <span class="symbol-name">${escHtml(r.name || r)}</span>
          <span class="symbol-file">${escHtml(r.file || '')}</span>
        </div>`;
      });
      html += `</div>`;
    }

    if (data.affected_files) {
      html += `<div><h3 style="font-size:13px;font-weight:600;color:var(--danger);margin-bottom:6px;">Affected Files (${data.affected_files.length})</h3>`;
      data.affected_files.forEach(f => {
        html += `<div class="file-item" onclick="fillExtract('${escHtml(f)}',1,50)">📄 ${escHtml(f)}</div>`;
      });
      html += `</div>`;
    }

    iaResults.innerHTML = html;
  } catch(e) {
    empty(iaResults, '⚠️', 'Analysis failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

/* ═══════════════════════════════════════════════════════════
   TRACE EXECUTION PAGE
═══════════════════════════════════════════════════════════ */
const teResults = document.getElementById('te-results');

document.getElementById('te-trace-btn').addEventListener('click', () => loadTrace('trace'));
document.getElementById('te-flow-btn').addEventListener('click', () => loadTrace('flow'));
document.getElementById('te-symbol').addEventListener('keydown', e => { if(e.key==='Enter') loadTrace('trace'); });

async function loadTrace(type) {
  const symbol = document.getElementById('te-symbol').value.trim();
  const depth = document.getElementById('te-depth').value || 5;
  if (!symbol) { toast('Enter a symbol name', 'error'); return; }

  loading(teResults);
  try {
    const endpoint = type === 'flow' ? '/search/endpoint-flow' : '/search/trace-execution';
    const paramName = type === 'flow' ? 'entry' : 'symbol_name';
    const params = new URLSearchParams({ [paramName]: symbol, max_depth: depth });
    const data = await api(`${endpoint}?${params}`);

    if (!data || (!data.trace && !data.flow && (!data.chain || data.chain.length === 0))) {
      empty(teResults, '🔀', 'No trace data', `No execution trace found for "${escHtml(symbol)}".`);
      return;
    }

    let html = `<div class="stats-bar"><span class="stats-badge">🔀 ${type === 'flow' ? 'Endpoint Flow' : 'Execution Trace'}</span> from <code style="font-family:var(--font-mono);background:var(--bg-elevated);padding:2px 6px;border-radius:4px;">${escHtml(symbol)}</code></div>`;

    const chain = data.chain || data.trace || data.flow || [];
    if (Array.isArray(chain)) {
      chain.forEach(item => {
        const depth = item.depth || 0;
        const indent = '  '.repeat(depth);
        const kindClass = depth === 0 ? 'kind-function' : (depth <= 2 ? 'kind-class' : 'kind-method');
        const name = item.name || (item.caller ? `${item.caller} → ${item.callee}` : '') || String(item);
        const file = item.file || item.caller_file || '';
        const line = item.line || item.caller_line || 0;
        html += `<div class="symbol-card" onclick="fillExtract('${escHtml(file)}',${line || 1},${(line || 1) + 5})" style="margin-left:${depth * 20}px;">
          <span class="symbol-kind ${kindClass}">L${depth}</span>
          <span class="symbol-name">${indent}${escHtml(name)}</span>
          <span class="symbol-file">${escHtml(file)}${line ? ':' + line : ''}</span>
        </div>`;
      });
    }

    teResults.innerHTML = html;
  } catch(e) {
    empty(teResults, '⚠️', 'Trace failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

/* ═══════════════════════════════════════════════════════════
   FUNCTION HISTORY PAGE
═══════════════════════════════════════════════════════════ */
const fhResults = document.getElementById('fh-results');

document.getElementById('fh-history-btn').addEventListener('click', loadFunctionHistory);
document.getElementById('fh-index-btn').addEventListener('click', indexGitHistory);
document.getElementById('fh-symbol').addEventListener('keydown', e => { if(e.key==='Enter') loadFunctionHistory(); });

async function loadFunctionHistory() {
  const symbol = document.getElementById('fh-symbol').value.trim();
  const limit = document.getElementById('fh-limit').value || 20;
  if (!symbol) { toast('Enter a function name', 'error'); return; }

  loading(fhResults);
  try {
    const data = await api(`/search/function-history?${new URLSearchParams({ symbol: symbol, limit })}`);

    if (!data || !data.history || data.history.length === 0) {
      empty(fhResults, '📜', 'No history found', `No git history found for "${escHtml(symbol)}". Try indexing git history first.`);
      return;
    }

    let html = `<div class="stats-bar"><span class="stats-badge">📜 ${data.history.length} commit${data.history.length!==1?'s':''}</span> for <code style="font-family:var(--font-mono);background:var(--bg-elevated);padding:2px 6px;border-radius:4px;">${escHtml(symbol)}</code></div>`;

    data.history.forEach(commit => {
      const changeType = commit.change_type || 'modified';
      const typeColor = { signature_change: 'var(--danger)', logic_edit: 'var(--warning)', new: 'var(--success)', deleted: 'var(--danger)' }[changeType] || 'var(--text-muted)';
      html += `<div class="match-card">
        <div class="match-header">
          <span class="file-icon" style="color:${typeColor};">●</span>
          <span class="file-path" style="font-family:var(--font-mono);font-size:11px;">${escHtml(commit.commit || commit.hash || commit.sha || '').slice(0, 8)}</span>
          <span class="line-badge" style="background:${typeColor}20;color:${typeColor};">${changeType}</span>
        </div>
        <div class="match-body">
          <div style="font-size:12.5px;color:var(--text-primary);margin-bottom:4px;">${escHtml(commit.message || '')}</div>
          <div style="font-size:11px;color:var(--text-muted);">${escHtml(commit.date || '')}</div>
        </div>
      </div>`;
    });

    fhResults.innerHTML = html;
  } catch(e) {
    empty(fhResults, '⚠️', 'History failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

async function indexGitHistory() {
  toast('Indexing git history...', 'info');
  try {
    const data = await api('/git-index', { method: 'POST' });
    toast(`Indexed ${data.indexed_commits || 0} commits ✅`, 'success');
  } catch(e) {
    toast('Failed to index git history: ' + e.message, 'error');
  }
}

/* ═══════════════════════════════════════════════════════════
   SIMILAR FUNCTIONS PAGE
═══════════════════════════════════════════════════════════ */
const sfResults = document.getElementById('sf-results');

document.getElementById('sf-search-btn').addEventListener('click', loadSimilarFunctions);
document.getElementById('sf-symbol').addEventListener('keydown', e => { if(e.key==='Enter') loadSimilarFunctions(); });

async function loadSimilarFunctions() {
  const symbol = document.getElementById('sf-symbol').value.trim();
  const limit = document.getElementById('sf-limit').value || 5;
  if (!symbol) { toast('Enter a function name', 'error'); return; }

  loading(sfResults);
  try {
    const data = await api(`/search/similar?${new URLSearchParams({ symbol: symbol, limit })}`);

    if (!data || !data.results || data.results.length === 0) {
      empty(sfResults, '🧬', 'No similar functions found', `No similar functions found for "${escHtml(symbol)}". Make sure embeddings are enabled.`);
      return;
    }

    let html = `<div class="stats-bar"><span class="stats-badge">🧬 ${data.results.length} similar</span> to <code style="font-family:var(--font-mono);background:var(--bg-elevated);padding:2px 6px;border-radius:4px;">${escHtml(symbol)}</code></div>`;

    data.results.forEach(r => {
      const distance = r.distance ? r.distance.toFixed(3) : '?';
      const similarity = r.distance ? ((1 - r.distance) * 100).toFixed(1) : '?';
      html += `<div class="symbol-card" onclick="fillExtract('${escHtml(r.file || '')}',${r.line_start || 1},${(r.line_start || 1) + 5})">
        <span class="symbol-kind kind-${r.kind || 'function'}">${r.kind || 'func'}</span>
        <span class="symbol-name">${escHtml(r.name || '')}</span>
        <span class="symbol-file">${escHtml(r.file || '')}</span>
        <span class="symbol-lines" title="Similarity: ${similarity}%">${similarity}%</span>
      </div>`;
    });

    sfResults.innerHTML = html;
  } catch(e) {
    empty(sfResults, '⚠️', 'Search failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

/* ═══════════════════════════════════════════════════════════
   REFERENCES PAGE
═══════════════════════════════════════════════════════════ */
const refResults = document.getElementById('ref-results');

document.getElementById('ref-count-btn').addEventListener('click', () => loadReferences('count'));
document.getElementById('ref-usages-btn').addEventListener('click', () => loadReferences('usages'));
document.getElementById('ref-symbol').addEventListener('keydown', e => { if(e.key==='Enter') loadReferences('count'); });

async function loadReferences(type) {
  const symbol = document.getElementById('ref-symbol').value.trim();
  if (!symbol) { toast('Enter a symbol name', 'error'); return; }

  loading(refResults);
  try {
    const endpoint = type === 'usages' ? '/search/usages' : '/search/count-references';
    const params = new URLSearchParams({ symbol_name: symbol });
    const data = await api(`${endpoint}?${params}`);

    if (type === 'count') {
      const count = data.count || data.total || 0;
      const files = data.files || [];
      let html = `<div class="stats-bar"><span class="stats-badge">📊 ${count} reference${count!==1?'s':''}</span> for <code style="font-family:var(--font-mono);background:var(--bg-elevated);padding:2px 6px;border-radius:4px;">${escHtml(symbol)}</code></div>`;
      
      html += `<div class="summary-stats">
        <div class="summary-stat"><span class="stat-icon">📊</span><div><div class="stat-value">${count}</div><div class="stat-label">References</div></div></div>
        <div class="summary-stat"><span class="stat-icon">📄</span><div><div class="stat-value>${files.length}</div><div class="stat-label">Files</div></div></div>
      </div>`;

      if (files.length > 0) {
        html += `<div style="margin-top:12px;">`;
        files.forEach(f => {
          const fname = typeof f === 'string' ? f : f.file;
          const fcount = typeof f === 'string' ? '' : ` (${f.count || 0})`;
          html += `<div class="file-item" onclick="fillExtract('${escHtml(fname)}',1,50)">📄 ${escHtml(fname)}${fcount}</div>`;
        });
        html += `</div>`;
      }
      refResults.innerHTML = html;
    } else {
      const usages = data.usages || data.results || data || [];
      if (!Array.isArray(usages) || usages.length === 0) {
        empty(refResults, '📊', 'No usages found', `No usages found for "${escHtml(symbol)}".`);
        return;
      }

      let html = `<div class="stats-bar"><span class="stats-badge">📊 ${usages.length} usage${usages.length!==1?'s':''}</span> for <code style="font-family:var(--font-mono);background:var(--bg-elevated);padding:2px 6px;border-radius:4px;">${escHtml(symbol)}</code></div>`;
      usages.forEach(u => {
        html += `<div class="symbol-card" onclick="fillExtract('${escHtml(u.file || '')}',${u.line || 1},${(u.line || 1) + 5})">
          <span class="symbol-kind kind-import">usage</span>
          <span class="symbol-name">${escHtml(u.context || u.text || u.name || symbol)}</span>
          <span class="symbol-file">${escHtml(u.file || '')}${u.line ? ':' + u.line : ''}</span>
        </div>`;
      });
      refResults.innerHTML = html;
    }
  } catch(e) {
    empty(refResults, '⚠️', 'Search failed', e.message);
    toast('Error: ' + e.message, 'error');
  }
}

// ── INIT ──
loadSandboxStatus();
