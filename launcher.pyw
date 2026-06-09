
"""
launcher.pyw — Code Search Engine desktop launcher.

The .pyw extension suppresses the console window on Windows.
Double-click this file (or run: pythonw launcher.pyw) to start the app.

How it works:
  1. Shows a game-style tkinter splash screen immediately
  2. Starts FastAPI/Uvicorn in a daemon thread
  3. Polls until the server is up, animating the splash progress bar
  4. Closes the splash, opens the pywebview native window
"""

import sys
import os
import time
import math
import atexit
import signal
import threading
import subprocess
import urllib.request
import urllib.error
import traceback
import logging

# ── Ensure the local .venv is on sys.path ────────────────────────────────────
_here = os.path.dirname(os.path.abspath(__file__))
_venv_site = os.path.join(_here, ".venv", "Lib", "site-packages")
if os.path.isdir(_venv_site) and _venv_site not in sys.path:
    sys.path.insert(0, _venv_site)

# ── Setup Logging immediately ────────────────────────────────────────────────
os.makedirs(os.path.join(_here, "logs"), exist_ok=True)
log_file = os.path.join(_here, "logs", "launcher.log")

logging.basicConfig(
    filename=log_file,
    filemode="w",
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("launcher")

# Global buffer to capture stdout/stderr so we can display it if the server crashes
console_buffer = []

# Redirect stdout/stderr to log file so we catch all exceptions/print statements
class StreamToLogger:
    def __init__(self, logger, log_level, collect=False):
        self.logger = logger
        self.log_level = log_level
        self.collect = collect

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            line_str = line.rstrip()
            self.logger.log(self.log_level, line_str)
            if self.collect:
                console_buffer.append(line_str)
                # Keep the last 40 lines of console output
                if len(console_buffer) > 40:
                    console_buffer.pop(0)

    def flush(self):
        pass

    def isatty(self):
        return False

# Capture both stdout and stderr so we get tracebacks and logs
# sys.stdout = StreamToLogger(logger, logging.INFO, collect=True)
# sys.stderr = StreamToLogger(logger, logging.ERROR, collect=True)

logger.info("Launcher started.")
logger.info(f"Site packages path injected: {_venv_site}")

# ── Try imports and fail gracefully with GUI if packages are missing ────────
try:
    import tkinter as tk
    from tkinter import messagebox
    from tkinter import filedialog
    import webview
    import uvicorn
    logger.info("Successfully imported tkinter, webview, and uvicorn.")
except Exception as e:
    error_detail = traceback.format_exc()
    logger.critical(f"Failed to import dependencies:\n{error_detail}")
    
    # Try using tkinter to show the error dialog
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Launcher Dependency Error",
            f"Failed to load dependencies.\n\nError: {e}\n\nMake sure your virtual environment (.venv) is fully set up.\nLogs written to: logs/launcher.log"
        )
    except Exception:
        pass
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 8000
URL  = f"http://{HOST}:{PORT}"

# Global to store background thread exceptions (if any raised directly)
server_exception = None
server_process = None


def cleanup_server():
    """Kill the server subprocess if it's still running."""
    global server_process
    if server_process is not None:
        try:
            if server_process.poll() is None:
                logger.info("Stopping server process pid=%s", server_process.pid)
                server_process.terminate()
                try:
                    server_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    logger.warning("Server did not terminate in 3s, killing.")
                    server_process.kill()
                    server_process.wait(timeout=2)
                logger.info("Server process stopped.")
        except Exception as e:
            logger.error("Error stopping server: %s", e)
        finally:
            server_process = None


atexit.register(cleanup_server)


def _signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM to ensure server is stopped."""
    logger.info("Signal %s received, cleaning up.", signum)
    cleanup_server()
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

class JSApi:
    """Methods exposed to the web page via window.pywebview.api.*"""

    def pick_folder(self, initial: str = "") -> str | None:
        """Open a modern native OS folder-picker dialog and return the chosen path."""
        logger.info("Folder picker opened by webview API.")
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        
        result = filedialog.askdirectory(
            initialdir=initial or "",
            title="Select Repository Folder",
            parent=root
        )
        
        root.destroy()
        logger.info(f"Folder picker returned: {result}")
        return result if result else None


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
        logger.info("Initializing splash screen UI.")
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
        """Close the launcher window."""
        logger.info("Exit launcher requested.")
        try:
            self.root.destroy()
        except Exception:
            pass

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
def kill_stale_server():
    """Kill any existing process bound to our port so we can start fresh."""
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((HOST, PORT))
        sock.close()
        if result == 0:
            # Port is in use — find and kill the process
            logger.info("Port %d is in use, killing stale process.", PORT)
            if os.name == "nt":
                # Windows: use netstat + taskkill
                import re
                out = subprocess.check_output(
                    ["netstat", "-ano", "-p", "tcp"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                ).decode(errors="replace")
                for line in out.splitlines():
                    if f":{PORT}" in line and "LISTENING" in line:
                        parts = line.split()
                        stale_pid = int(parts[-1])
                        logger.info("Killing stale server PID=%d", stale_pid)
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(stale_pid)],
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            capture_output=True,
                        )
                        time.sleep(0.5)
                        break
            else:
                # Unix: use fuser
                subprocess.run(["fuser", "-k", f"{PORT}/tcp"],
                               capture_output=True)
                time.sleep(0.5)
    except Exception as e:
        logger.warning("Could not check/kill stale server: %s", e)


def start_server():
    global server_process

    os.chdir(_here)

    # Kill any leftover server on our port
    kill_stale_server()

    # Use the venv's Python executable
    venv_python = os.path.join(_here, ".venv", "Scripts", "python.exe")

    # Set up environment with PYTHONPATH to find codeengine module
    env = os.environ.copy()
    env["PYTHONPATH"] = _here

    server_process = subprocess.Popen(
        [
            venv_python,
            "-m",
            "uvicorn",
            "codeengine.app:app",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--log-level",
            "debug",
        ],
        cwd=_here,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    logger.info(
        f"Started uvicorn process pid={server_process.pid}"
    )


def server_waiter(splash: SplashScreen) -> None:
    """Wait briefly for the server subprocess to start, then close splash."""
    splash.update(0.1, "Starting server…")
    time.sleep(1.0)

    # Check if the server process died
    if server_process and server_process.poll() is not None:
        logger.error("Server process died unexpectedly.")
        splash.update(0.0, "Server failed to start!")

        error_details = "\n".join(console_buffer[-25:])
        if not error_details:
            error_details = server_exception or "No error output captured in stderr."

        def show_server_error():
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Server Startup Failure",
                f"The Code Search Engine server failed to start.\n\nCaptured Console Output/Traceback:\n{error_details}\n\nFull logs written to: logs/launcher.log"
            )

        splash.root.after(0, show_server_error)
        return

    logger.info("Server started. Closing splash and launching webview.")
    splash.update(1.0, "Ready!  Launching…")
    splash.close_after(500)


if __name__ == "__main__":
    # 1 Show the splash screen immediately (main thread)
    splash = SplashScreen()

    # 2 Start the FastAPI backend
    logger.info("Starting a new local server process.")
    start_server()
    # 3 Wait briefly for server subprocess to boot — drives the splash progress bar
    threading.Thread(target=server_waiter, args=(splash,), daemon=True).start()

    # 4️⃣  Block until the splash closes itself (server is ready)
    splash.mainloop()

    # 5️⃣  Splash is gone → open the main native window if server didn't fail
    if server_process and server_process.poll() is not None:
        logger.info("Server crashed. Exiting launcher instead of opening webview.")
        cleanup_server()
        sys.exit(1)

    logger.info("Opening pywebview window.")
    try:
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
        logger.info("Webview window closed. Launcher exiting clean.")
    except Exception as e:
        logger.critical(f"Webview encountered an error:\n{traceback.format_exc()}")
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Webview Window Error",
                f"Failed to open native window.\n\nError: {e}\n\nLogs written to: logs/launcher.log"
            )
        except Exception:
            pass
        sys.exit(1)
    finally:
        cleanup_server()
