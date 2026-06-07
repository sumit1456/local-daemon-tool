"""
launcher.pyw — Code Search Engine desktop launcher.

The .pyw extension suppresses the console window on Windows.
Double-click this file (or run: pythonw launcher.pyw) to start the app.

How it works:
  1. Shows a game-style tkinter splash screen immediately
  2. Starts FastAPI/Uvicorn in a daemon thread
  3. Polls until the server is up, animating the splash progress bar
  4. Closes the splash, opens the pywebview native window

Requirements (already in requirements.txt / pyproject.toml):
    pip install pywebview uvicorn fastapi
"""

import sys
import os
import time
import math
import threading
import urllib.request
import urllib.error
import tkinter as tk

# ── Ensure the local .venv is on sys.path ────────────────────────────────────
_here = os.path.dirname(os.path.abspath(__file__))
_venv_site = os.path.join(_here, ".venv", "Lib", "site-packages")
if os.path.isdir(_venv_site) and _venv_site not in sys.path:
    sys.path.insert(0, _venv_site)

import webview
import uvicorn

# ─────────────────────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 8000
URL  = f"http://{HOST}:{PORT}"


# ══════════════════════════════════════════════════════════════════════════════
#  JS API  —  exposed to the web page via  window.pywebview.api.*
# ══════════════════════════════════════════════════════════════════════════════
class JSApi:
    """Methods exposed to the web page via window.pywebview.api.*"""

    def pick_folder(self, initial: str = "") -> str | None:
        """Open a native OS folder-picker dialog and return the chosen path."""
        import webview as _wv
        result = _wv.windows[0].create_file_dialog(
            _wv.FOLDER_DIALOG,
            directory=initial or "",
            allow_multiple=False,
        )
        return result[0] if result else None


# ══════════════════════════════════════════════════════════════════════════════
#  SPLASH SCREEN  (tkinter, borderless, dark-themed)
# ══════════════════════════════════════════════════════════════════════════════
class SplashScreen:
    W, H    = 580, 340
    BG      = "#0d0f14"
    SURFACE = "#13161e"
    BORDER  = "#1a2540"
    ACCENT  = "#4299e1"
    GLOW    = "#90cdf4"
    TEXT    = "#e2e8f0"
    SUBTEXT = "#8892a4"
    MUTED   = "#4a5568"
    SUCCESS = "#68d391"
    SUCCESS2= "#9ae6b4"

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)        # borderless window
        self.root.configure(bg=self.BG)
        self.root.attributes("-topmost", True)  # stay on top while loading
        self.root.resizable(False, False)

        # Center on screen
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = (sw - self.W) // 2
        y  = (sh - self.H) // 2
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

        # Bind Escape key to close launcher instantly
        self.root.bind("<Escape>", lambda e: self.exit_launcher())

        self._shimmer_pos = 0.0
        self._shimmer_dir = 1
        self._build_ui()

    def exit_launcher(self):
        """Force quit the entire python launcher execution."""
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)  # Immediate hard exit to kill background threads as well

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        W, H = self.W, self.H
        c = tk.Canvas(self.root, width=W, height=H,
                      bg=self.BG, highlightthickness=0)
        c.pack(fill="both", expand=True)
        self.canvas = c

        # Outer border
        c.create_rectangle(0, 0, W-1, H-1,
                           outline=self.BORDER, width=1)

        # Top accent stripe (gradient simulation: 3 rectangles)
        c.create_rectangle(0, 0, W, 3,  fill="#2b4e7a", outline="")
        c.create_rectangle(0, 3, W, 5,  fill="#1a3254", outline="")
        c.create_rectangle(0, 5, W, 7,  fill="#11213a", outline="")

        # Visual close button in the top-right corner
        self.close_btn = c.create_text(W - 20, 20, text="✕", font=("Segoe UI", 11, "bold"), fill=self.MUTED)
        c.tag_bind(self.close_btn, "<Button-1>", lambda e: self.exit_launcher())
        c.tag_bind(self.close_btn, "<Enter>", lambda e: c.itemconfigure(self.close_btn, fill="#fc8181"))
        c.tag_bind(self.close_btn, "<Leave>", lambda e: c.itemconfigure(self.close_btn, fill=self.MUTED))

        # ── Icon box ─────────────────────────────────────────────────────────
        ix, iy = W//2, 82
        c.create_rectangle(ix-32, iy-32, ix+32, iy+32,
                           fill="#111827", outline=self.ACCENT, width=1)
        # Glow behind icon
        for r, a in [(38, "#0d1f38"), (45, "#0a1828"), (52, "#080f1c")]:
            c.create_oval(ix-r, iy-r, ix+r, iy+r, outline=a, width=1)
        c.create_text(ix, iy, text="⚡", font=("Segoe UI Emoji", 28), fill="#63b3ed")

        # ── App title ────────────────────────────────────────────────────────
        c.create_text(W//2, 136,
                      text="Code Search Engine",
                      font=("Segoe UI Semibold", 20, "bold"),
                      fill=self.TEXT)
        c.create_text(W//2, 160,
                      text="Universal Code Intelligence Platform",
                      font=("Segoe UI", 10),
                      fill=self.SUBTEXT)

        # Thin separator
        c.create_line(80, 182, W-80, 182, fill=self.BORDER, width=1)

        # ── Progress bar track ───────────────────────────────────────────────
        bx1, by1 = 72,  215
        bx2, by2 = W-72, 233
        # Track bg + inner glow
        c.create_rectangle(bx1-1, by1-1, bx2+1, by2+1,
                           outline="#1e2d45", width=1, fill="")
        c.create_rectangle(bx1, by1, bx2, by2,
                           fill="#0e1420", outline="")

        # Progress fill
        self._bx1, self._by1 = bx1, by1
        self._bx2, self._by2 = bx2, by2
        self._fill = c.create_rectangle(bx1, by1, bx1, by2,
                                        fill=self.ACCENT, outline="")
        # Top shimmer strip
        self._shimmer = c.create_rectangle(bx1, by1, bx1, by1+2,
                                            fill=self.GLOW, outline="")
        # Percentage label
        self._pct = c.create_text(W-80, (by1+by2)//2,
                                  text="0%",
                                  font=("Segoe UI", 8, "bold"),
                                  fill=self.MUTED)

        # ── Status label ─────────────────────────────────────────────────────
        self._status = c.create_text(W//2, 258,
                                     text="Initializing…",
                                     font=("Segoe UI", 9),
                                     fill=self.SUBTEXT)

        # ── Loading dots ─────────────────────────────────────────────────────
        self._dots = [
            c.create_oval(W//2-22+i*16, 278, W//2-14+i*16, 286,
                          fill=self.BORDER, outline="")
            for i in range(5)
        ]

        # ── Bottom version strip ─────────────────────────────────────────────
        c.create_rectangle(0, H-30, W, H, fill=self.SURFACE, outline="")
        c.create_line(0, H-30, W, H-30, fill=self.BORDER, width=1)
        c.create_text(W//2, H-15,
                      text="v1.0.0  ·  Stage 1  ·  Code Search Engine",
                      font=("Segoe UI", 8),
                      fill=self.MUTED)

        # Start the animation loop
        self._pct_value  = 0.0
        self._dot_frame  = 0
        self._animate()

    # ── Animation loop (runs every 80 ms in the main thread) ─────────────────
    def _animate(self):
        c = self.canvas
        frame = self._dot_frame

        # Pulse the loading dots
        for i, dot in enumerate(self._dots):
            phase = (frame - i * 3) % 20
            alpha = max(0, 1 - abs(phase - 10) / 10)
            r = int(0x20 + alpha * (0x42 - 0x20))
            g = int(0x25 + alpha * (0x99 - 0x25))
            b = int(0x3a + alpha * (0xe1 - 0x3a))
            color = f"#{r:02x}{g:02x}{b:02x}"
            c.itemconfigure(dot, fill=color)

        self._dot_frame = (frame + 1) % 60

        # Shimmer sweep across the progress bar fill
        pct    = self._pct_value
        bx1, by1 = self._bx1, self._by1
        bx2, by2 = self._bx2, self._by2
        fill_x = bx1 + int((bx2 - bx1) * pct)
        sw     = max(0, fill_x - bx1)
        if sw > 0:
            self._shimmer_pos += self._shimmer_dir * 0.04
            if self._shimmer_pos > 1.0:
                self._shimmer_pos = 1.0; self._shimmer_dir = -1
            elif self._shimmer_pos < 0.0:
                self._shimmer_pos = 0.0; self._shimmer_dir = 1
            sx = bx1 + int(sw * self._shimmer_pos)
            c.coords(self._shimmer, sx-8, by1, sx+8, by1+2)

        self.root.after(80, self._animate)

    # ── Public: called from a background thread ───────────────────────────────
    def update(self, pct: float, status: str):
        """Thread-safe progress update."""
        self.root.after(0, self._do_update, pct, status)

    def _do_update(self, pct: float, status: str):
        pct = max(0.0, min(1.0, pct))
        self._pct_value = pct
        c = self.canvas

        bx1, by1 = self._bx1, self._by1
        bx2, by2 = self._bx2, self._by2
        fill_x   = bx1 + int((bx2 - bx1) * pct)

        c.coords(self._fill, bx1, by1, fill_x, by2)
        c.itemconfigure(self._status, text=status)
        c.itemconfigure(self._pct, text=f"{int(pct*100)}%")

        if pct >= 1.0:
            c.itemconfigure(self._fill,    fill=self.SUCCESS)
            c.itemconfigure(self._shimmer, fill=self.SUCCESS2)
            for dot in self._dots:
                c.itemconfigure(dot, fill=self.SUCCESS)

    def close_after(self, ms: int = 400):
        """Schedule window destruction on the main thread."""
        self.root.after(ms, self.root.destroy)

    def mainloop(self):
        self.root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
#  BACKEND
# ══════════════════════════════════════════════════════════════════════════════
def start_server() -> None:
    """Start FastAPI/Uvicorn (blocking — runs in a daemon thread)."""
    os.chdir(_here)
    uvicorn.run(
        "codeengine.app:app",
        host=HOST,
        port=PORT,
        log_level="warning",
    )


def server_poller(splash: SplashScreen, timeout: float = 30.0) -> None:
    """Poll until the server responds, then signal the splash to close."""
    STEPS = [
        "Starting server…",
        "Loading database…",
        "Indexing repository…",
        "Setting up file watchers…",
        "Almost there…",
    ]
    splash.update(0.04, "Starting server…")
    time.sleep(0.3)

    deadline = time.monotonic() + timeout
    step = 0

    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(URL + "/docs", timeout=0.8)
            splash.update(1.0, "Ready!  Launching…")
            splash.close_after(500)
            return
        except urllib.error.URLError:
            pass

        # Asymptotic approach to 90% so the bar never stalls at 100% prematurely
        fake_pct = 0.04 + 0.82 * (1 - math.exp(-step / 14))
        label    = STEPS[min(step // 4, len(STEPS) - 1)]
        splash.update(fake_pct, label)
        step += 1
        time.sleep(0.4)

    # Timed out — open anyway
    splash.update(1.0, "Ready!")
    splash.close_after(400)


if __name__ == "__main__":
    # Check if server is already running
    server_already_running = False
    try:
        with urllib.request.urlopen(URL + "/docs", timeout=0.5) as response:
            if response.status == 200:
                server_already_running = True
    except Exception:
        pass

    # 1️⃣  Show the splash screen immediately (main thread)
    splash = SplashScreen()

    # 2️⃣  Start the FastAPI backend ONLY if not already running
    if not server_already_running:
        threading.Thread(target=start_server, daemon=True).start()
        # 3️⃣  Poll server in background — drives the splash progress bar
        threading.Thread(target=server_poller, args=(splash,), daemon=True).start()
    else:
        # Jump directly to ready
        def skip_splash():
            time.sleep(0.1)
            splash.update(1.0, "Ready! (Connected to running server)")
            splash.close_after(300)
        threading.Thread(target=skip_splash, daemon=True).start()

    # 4️⃣  Block until the splash closes itself (server is ready)
    splash.mainloop()

    # 5️⃣  Splash is gone → open the main native window
    api = JSApi()
    webview.create_window(
        title  = "Code Search Engine",
        url    = URL,
        width  = 1280,
        height = 820,
        min_size    = (960, 640),
        resizable   = True,
        text_select = True,
        js_api      = api,
    )
    webview.start(debug=True)   # blocks until window is closed
