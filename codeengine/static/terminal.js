/* ═══════════════════════════════════════════════════════════════
   terminal.js — xterm.js powered terminal for CodeEngine
   Separate from static.js to keep things modular.
   ═══════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  const BASE = window.location.origin;

  let term = null;
  let fitAddon = null;
  let currentMode = 'sandbox'; // 'sandbox' | 'local'
  let commandHistory = [];
  let historyIndex = -1;
  let currentInput = '';
  let promptText = '\x1b[1;32m❯\x1b[0m ';
  let isProcessing = false;

  /* ── Init ─────────────────────────────────────────────────── */

  function initTerminal() {
    if (term) return; // already initialized

    term = new Terminal({
      theme: {
        background: '#0a0c10',
        foreground: '#c9d1d9',
        cursor: '#58a6ff',
        cursorAccent: '#0a0c10',
        selectionBackground: 'rgba(88,166,255,0.3)',
        black: '#0d1117',
        red: '#ff7b72',
        green: '#3fb950',
        yellow: '#d29922',
        blue: '#58a6ff',
        magenta: '#bc8cff',
        cyan: '#39c5cf',
        white: '#c9d1d9',
        brightBlack: '#484f58',
        brightRed: '#ffa198',
        brightGreen: '#56d364',
        brightYellow: '#e3b341',
        brightBlue: '#79c0ff',
        brightMagenta: '#d2a8ff',
        brightCyan: '#56d4dd',
        brightWhite: '#f0f6fc',
      },
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
      fontSize: 13,
      lineHeight: 1.3,
      cursorBlink: true,
      cursorStyle: 'bar',
      allowProposedApi: true,
      scrollback: 5000,
    });

    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);

    try {
      const webLinksAddon = new WebLinksAddon.WebLinksAddon();
      term.loadAddon(webLinksAddon);
    } catch (e) { /* optional */ }

    const container = document.getElementById('xterm-container');
    if (!container) return;
    term.open(container);
    fitAddon.fit();

    // Handle resize
    const observer = new ResizeObserver(() => {
      if (fitAddon) fitAddon.fit();
    });
    observer.observe(container);

    // Input handler
    term.onData(handleInput);

    // Show welcome + prompt
    writeLine('\x1b[1;36m╔══════════════════════════════════════════╗');
    writeLine('\x1b[1;36m║\x1b[0m  \x1b[1;37mCodeEngine Terminal\x1b[0m                    \x1b[1;36m║');
    writeLine('\x1b[1;36m║\x1b[0m  Type commands and press Enter.          \x1b[1;36m║');
    writeLine('\x1b[1;36m║\x1b[0m  History: ↑/↓  |  Clear: Ctrl+L         \x1b[1;36m║');
    writeLine('\x1b[1;36m╚══════════════════════════════════════════╝\x1b[0m');
    writeLine('');
    showPrompt();
  }

  /* ── Input handling ───────────────────────────────────────── */

  function handleInput(data) {
    if (isProcessing) return;

    const code = data.charCodeAt(0);

    // Ctrl+C — cancel / newline
    if (data === '\x03') {
      writeLine('^C');
      currentInput = '';
      showPrompt();
      return;
    }

    // Ctrl+L — clear
    if (data === '\x0c') {
      term.clear();
      showPrompt();
      return;
    }

    // Ctrl+U — clear line
    if (data === '\x15') {
      currentInput = '';
      term.write('\r\x1b[K');
      showPrompt();
      return;
    }

    // Enter — execute
    if (data === '\r') {
      writeLine('');
      if (currentInput.trim()) {
        commandHistory.push(currentInput.trim());
        historyIndex = commandHistory.length;
        executeCommand(currentInput.trim());
      } else {
        showPrompt();
      }
      return;
    }

    // Backspace
    if (data === '\x7f' || data === '\b') {
      if (currentInput.length > 0) {
        currentInput = currentInput.slice(0, -1);
        term.write('\b \b');
      }
      return;
    }

    // Arrow Up — history prev
    if (data === '\x1b[A') {
      if (historyIndex > 0) {
        historyIndex--;
        replaceInput(commandHistory[historyIndex]);
      }
      return;
    }

    // Arrow Down — history next
    if (data === '\x1b[B') {
      if (historyIndex < commandHistory.length - 1) {
        historyIndex++;
        replaceInput(commandHistory[historyIndex]);
      } else {
        historyIndex = commandHistory.length;
        replaceInput('');
      }
      return;
    }

    // Arrow Left / Right — skip (let terminal handle cursor)
    if (data === '\x1b[C' || data === '\x1b[D') return;

    // Home / End
    if (data === '\x1b[H' || data === '\x1b[F') return;

    // Ignore other escape sequences
    if (data.startsWith('\x1b')) return;

    // Printable characters
    if (data >= ' ') {
      currentInput += data;
      term.write(data);
    }
  }

  function replaceInput(text) {
    // Clear current input visually
    term.write('\r\x1b[K');
    currentInput = text;
    showPrompt(false);
    term.write(text);
  }

  /* ── Prompt ───────────────────────────────────────────────── */

  function showPrompt(newline = true) {
    if (newline) term.write('\r\n');
    const mode = currentMode === 'sandbox' ? '\x1b[1;33msandbox\x1b[0m' : '\x1b[1;34mlocal\x1b[0m';
    term.write(`${mode} ${promptText}`);
  }

  /* ── Command execution ────────────────────────────────────── */

  async function executeCommand(cmd) {
    isProcessing = true;
    const endpoint = currentMode === 'sandbox'
      ? `${BASE}/sandbox/terminal/exec`
      : `${BASE}/sandbox/terminal/exec-local`;

    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd }),
      });

      const data = await resp.json();

      if (data.error) {
        writeLine(`\x1b[31mError: ${data.error}\x1b[0m`);
      } else if (data.output) {
        const output = data.output.replace(/\n$/, '');
        if (output) writeLine(output);
        if (data.exit_code !== 0 && data.exit_code !== undefined) {
          writeLine(`\x1b[33m(exit code: ${data.exit_code})\x1b[0m`);
        }
      }
    } catch (e) {
      writeLine(`\x1b[31mConnection error: ${e.message}\x1b[0m`);
      writeLine(`\x1b[33mMake sure the CodeEngine server is running on ${BASE}\x1b[0m`);
    }

    isProcessing = false;
    showPrompt();
  }

  /* ── Output helpers ───────────────────────────────────────── */

  function writeLine(text) {
    if (!term) return;
    term.writeln(text);
  }

  /* ── Mode switching ───────────────────────────────────────── */

  function setMode(mode) {
    currentMode = mode;
    const label = document.getElementById('terminal-mode-label');
    if (label) {
      label.textContent = mode === 'sandbox'
        ? 'Running in Docker container'
        : 'Running on host machine';
    }

    // Update toggle buttons
    document.querySelectorAll('#terminal-mode-toggle .mode-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    // Reset terminal with new mode info
    if (term) {
      writeLine('');
      writeLine(`\x1b[1;35m── Switched to ${mode === 'sandbox' ? '🐳 Sandbox (Docker)' : '🖥 Local (Host)'} ──\x1b[0m`);
      showPrompt();
    }
  }

  /* ── Clear / Reset ────────────────────────────────────────── */

  function clearTerminal() {
    if (term) {
      term.clear();
      showPrompt();
    }
  }

  function resetTerminal() {
    if (term) {
      term.clear();
      commandHistory = [];
      historyIndex = -1;
      currentInput = '';
      writeLine('\x1b[1;35mTerminal reset.\x1b[0m');
      showPrompt();
    }
  }

  /* ── Wire up sidebar nav ──────────────────────────────────── */

  function setupNav() {
    const navItem = document.getElementById('nav-terminal');
    if (navItem) {
      navItem.addEventListener('click', () => {
        // Show terminal page
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        const page = document.getElementById('page-terminal');
        if (page) page.classList.add('active');
        navItem.classList.add('active');

        // Init terminal on first visit
        setTimeout(() => {
          initTerminal();
          if (fitAddon) fitAddon.fit();
        }, 50);
      });
    }
  }

  /* ── Wire up toolbar buttons ──────────────────────────────── */

  function setupToolbar() {
    // Mode toggle
    const modeToggle = document.getElementById('terminal-mode-toggle');
    if (modeToggle) {
      modeToggle.addEventListener('click', (e) => {
        const btn = e.target.closest('.mode-btn');
        if (btn && btn.dataset.mode) {
          setMode(btn.dataset.mode);
        }
      });
    }

    // Clear button
    const clearBtn = document.getElementById('terminal-clear-btn');
    if (clearBtn) clearBtn.addEventListener('click', clearTerminal);

    // Reset button
    const resetBtn = document.getElementById('terminal-reset-btn');
    if (resetBtn) resetBtn.addEventListener('click', resetTerminal);
  }

  /* ── Boot ─────────────────────────────────────────────────── */

  document.addEventListener('DOMContentLoaded', () => {
    setupNav();
    setupToolbar();
  });

})();
