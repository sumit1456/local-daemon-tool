"""
launcher_v2.pyw — Code Search Engine launcher (FastAPI + MCP combined).

Starts both the FastAPI daemon (port 8000) and the MCP server (stdio)
in a single launcher. The MCP server process is kept alive so MCP clients
(Claude Desktop, Aider, etc.) can connect to it.

The .pyw extension suppresses the console window on Windows.
Double-click this file (or run: pythonw launcher_v2.pyw) to start.

How it works:
  1. Shows a tkinter splash screen immediately
  2. Starts FastAPI/Uvicorn in a daemon thread
  3. Starts MCP server as a background subprocess
  4. Polls until the server is up, animating the splash progress bar
  5. Closes the splash, opens the pywebview native window
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
log_file = os.path.join(_here, "logs", "launcher_v2.log")

logging.basicConfig(
    filename=log_file,
    filemode="w",
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("launcher_v2")

console_buffer = []


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
                if len(console_buffer) > 40:
                    console_buffer.pop(0)

    def flush(self):
        pass

    def isatty(self):
        return False


logger.info("Launcher v2 started.")
logger.info(f"Site packages path injected: {_venv_site}")

# ── Try imports and fail gracefully ──────────────────────────────────────────
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
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Launcher Dependency Error",
            f"Failed to load dependencies.\n\nError: {e}\n\nMake sure your virtual environment (.venv) is fully set up.\nLogs written to: logs/launcher_v2.log"
        )
    except Exception:
        pass
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 8000
URL  = f"http://{HOST}:{PORT}"

server_process = None
mcp_process = None


def cleanup_servers():
    """Kill both daemon and MCP subprocesses if still running."""
    global server_process, mcp_process

    for name, proc in [("daemon", server_process), ("MCP", mcp_process)]:
        if proc is not None:
            try:
                if proc.poll() is None:
                    logger.info("Stopping %s process pid=%s", name, proc.pid)
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        logger.warning("%s did not terminate in 3s, killing.", name)
                        proc.kill()
                        proc.wait(timeout=2)
                    logger.info("%s process stopped.", name)
            except Exception as e:
                logger.error("Error stopping %s: %s", name, e)

    server_process = None
    mcp_process = None


atexit.register(cleanup_servers)


def _signal_handler(signum, frame):
    logger.info("Signal %s received, cleaning up.", signum)
    cleanup_servers()
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


class JSApi:
    """Methods exposed to the web page via window.pywebview.api.*"""

    def pick_folder(self, initial: str = "") -> str | None:
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
#  SPLASH SCREEN
# ══════════════════════════════════════════════════════════════════════════════
class SplashScreen:
    W, H    = 580, 360
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
        self.root.overrideredirect(True)
        self.root.configure(bg=self.BG)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = (sw - self.W) // 2
        y  = (sh - self.H) // 2
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

        self.root.bind("<Escape>", lambda e: self.exit_launcher())

        self._shimmer_pos = 0.0
        self._shimmer_dir = 1
        self._build_ui()

    def exit_launcher(self):
        logger.info("Exit launcher requested.")
        try:
            self.root.destroy()
        except Exception:
            pass

    def _build_ui(self):
        W, H = self.W, self.H
        c = tk.Canvas(self.root, width=W, height=H,
                      bg=self.BG, highlightthickness=0)
        c.pack(fill="both", expand=True)
        self.canvas = c

        c.create_rectangle(0, 0, W-1, H-1, outline=self.BORDER, width=1)

        # Top accent stripe
        c.create_rectangle(0, 0, W, 3,  fill="#2b4e7a", outline="")
        c.create_rectangle(0, 3, W, 5,  fill="#1a3254", outline="")
        c.create_rectangle(0, 5, W, 7,  fill="#11213a", outline="")

        # Close button
        self.close_btn = c.create_text(W - 20, 20, text="\u2715",
                                       font=("Segoe UI", 11, "bold"),
                                       fill=self.MUTED)
        c.tag_bind(self.close_btn, "<Button-1>", lambda e: self.exit_launcher())
        c.tag_bind(self.close_btn, "<Enter>", lambda e: c.itemconfigure(self.close_btn, fill="#fc8181"))
        c.tag_bind(self.close_btn, "<Leave>", lambda e: c.itemconfigure(self.close_btn, fill=self.MUTED))

        # Icon box
        ix, iy = W//2, 78
        c.create_rectangle(ix-32, iy-32, ix+32, iy+32,
                           fill="#111827", outline=self.ACCENT, width=1)
        for r, a in [(38, "#0d1f38"), (45, "#0a1828"), (52, "#080f1c")]:
            c.create_oval(ix-r, iy-r, ix+r, iy+r, outline=a, width=1)
        c.create_text(ix, iy, text="\u26a1", font=("Segoe UI Emoji", 28), fill="#63b3ed")

        # Title
        c.create_text(W//2, 130,
                      text="Code Search Engine",
                      font=("Segoe UI Semibold", 20, "bold"),
                      fill=self.TEXT)
        c.create_text(W//2, 154,
                      text="FastAPI + MCP Server",
                      font=("Segoe UI", 10),
                      fill=self.SUBTEXT)

        c.create_line(80, 176, W-80, 176, fill=self.BORDER, width=1)

        # ── Service status labels ────────────────────────────────────────────
        self._daemon_status = c.create_text(W//2 - 80, 198,
                                            text="\u25cf FastAPI: starting\u2026",
                                            font=("Segoe UI", 9),
                                            fill=self.SUBTEXT)
        self._mcp_status = c.create_text(W//2 + 80, 198,
                                         text="\u25cf MCP: starting\u2026",
                                         font=("Segoe UI", 9),
                                         fill=self.SUBTEXT)

        # Progress bar track
        bx1, by1 = 72,  222
        bx2, by2 = W-72, 240
        c.create_rectangle(bx1-1, by1-1, bx2+1, by2+1, outline="#1e2d45", width=1, fill="")
        c.create_rectangle(bx1, by1, bx2, by2, fill="#0e1420", outline="")

        self._bx1, self._by1 = bx1, by1
        self._bx2, self._by2 = bx2, by2
        self._fill = c.create_rectangle(bx1, by1, bx1, by2,
                                        fill=self.ACCENT, outline="")
        self._shimmer = c.create_rectangle(bx1, by1, bx1, by1+2,
                                           fill=self.GLOW, outline="")
        self._pct = c.create_text(W-80, (by1+by2)//2,
                                  text="0%",
                                  font=("Segoe UI", 8, "bold"),
                                  fill=self.MUTED)

        # Status label
        self._status = c.create_text(W//2, 260,
                                     text="Initializing\u2026",
                                     font=("Segoe UI", 9),
                                     fill=self.SUBTEXT)

        # Loading dots
        self._dots = [
            c.create_oval(W//2-22+i*16, 278, W//2-14+i*16, 286,
                          fill=self.BORDER, outline="")
            for i in range(5)
        ]

        # Bottom version strip
        c.create_rectangle(0, H-30, W, H, fill=self.SURFACE, outline="")
        c.create_line(0, H-30, W, H-30, fill=self.BORDER, width=1)
        c.create_text(W//2, H-15,
                      text="v2.0.0  \u00b7  FastAPI + MCP  \u00b7  Code Search Engine",
                      font=("Segoe UI", 8),
                      fill=self.MUTED)

        self._pct_value  = 0.0
        self._dot_frame  = 0
        self._animate()

    def _animate(self):
        c = self.canvas
        frame = self._dot_frame

        for i, dot in enumerate(self._dots):
            phase = (frame - i * 3) % 20
            alpha = max(0, 1 - abs(phase - 10) / 10)
            r = int(0x20 + alpha * (0x42 - 0x20))
            g = int(0x25 + alpha * (0x99 - 0x25))
            b = int(0x3a + alpha * (0xe1 - 0x3a))
            color = f"#{r:02x}{g:02x}{b:02x}"
            c.itemconfigure(dot, fill=color)

        self._dot_frame = (frame + 1) % 60

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

    def update(self, pct: float, status: str):
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

    def set_daemon_status(self, ready: bool):
        """Update FastAPI status indicator."""
        text = "\u25cf FastAPI: ready on :8000" if ready else "\u25cf FastAPI: starting\u2026"
        color = self.SUCCESS if ready else self.SUBTEXT
        self.root.after(0, lambda: (
            self.canvas.itemconfigure(self._daemon_status, text=text, fill=color)
        ))

    def set_mcp_status(self, ready: bool):
        """Update MCP status indicator."""
        text = "\u25cf MCP: ready (stdio)" if ready else "\u25cf MCP: starting\u2026"
        color = self.SUCCESS if ready else self.SUBTEXT
        self.root.after(0, lambda: (
            self.canvas.itemconfigure(self._mcp_status, text=text, fill=color)
        ))

    def close_after(self, ms: int = 400):
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
            logger.info("Port %d is in use, killing stale process.", PORT)
            if os.name == "nt":
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
                subprocess.run(["fuser", "-k", f"{PORT}/tcp"],
                               capture_output=True)
                time.sleep(0.5)
    except Exception as e:
        logger.warning("Could not check/kill stale server: %s", e)


def start_daemon():
    """Start the FastAPI/Uvicorn daemon on port 8000."""
    global server_process

    os.chdir(_here)
    kill_stale_server()

    venv_python = os.path.join(_here, ".venv", "Scripts", "python.exe")
    env = os.environ.copy()
    env["PYTHONPATH"] = _here

    server_process = subprocess.Popen(
        [
            venv_python,
            "-m", "uvicorn",
            "codeengine.app:app",
            "--host", HOST,
            "--port", str(PORT),
            "--log-level", "debug",
        ],
        cwd=_here,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    logger.info("Started FastAPI daemon pid=%s", server_process.pid)


def start_mcp_server():
    """Start the MCP server as a background subprocess (stdio transport)."""
    global mcp_process

    os.chdir(_here)

    venv_python = os.path.join(_here, ".venv-mcp", "Scripts", "python.exe")
    if not os.path.isfile(venv_python):
        # Fallback to main venv
        venv_python = os.path.join(_here, ".venv", "Scripts", "python.exe")

    env = os.environ.copy()
    env["PYTHONPATH"] = _here

    mcp_script = os.path.join(_here, "mcp_server.py")

    mcp_process = subprocess.Popen(
        [venv_python, mcp_script],
        cwd=_here,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    logger.info("Started MCP server pid=%s", mcp_process.pid)


def server_waiter(splash: SplashScreen) -> None:
    """Wait for both servers to start, then close splash."""
    splash.update(0.1, "Starting FastAPI daemon\u2026")
    time.sleep(1.0)

    # Check if daemon died
    if server_process and server_process.poll() is not None:
        logger.error("FastAPI daemon died unexpectedly.")
        splash.update(0.0, "Daemon failed to start!")
        error_details = "\n".join(console_buffer[-25:])
        if not error_details:
            error_details = "No error output captured."

        def show_error():
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Server Startup Failure",
                f"FastAPI daemon failed to start.\n\n{error_details}\n\nLogs: logs/launcher_v2.log"
            )
        splash.root.after(0, show_error)
        return

    splash.set_daemon_status(True)
    splash.update(0.5, "Starting MCP server\u2026")
    time.sleep(0.5)

    # Check if MCP server died
    if mcp_process and mcp_process.poll() is not None:
        logger.warning("MCP server died, continuing without MCP.")
        splash.set_mcp_status(False)
    else:
        splash.set_mcp_status(True)

    splash.update(1.0, "Ready!  Launching\u2026")
    splash.close_after(500)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 1. Show splash screen immediately (main thread)
    splash = SplashScreen()

    # 2. Start both backends
    logger.info("Starting FastAPI daemon and MCP server.")
    start_daemon()
    start_mcp_server()

    # 3. Wait for servers to boot (drives splash progress)
    threading.Thread(target=server_waiter, args=(splash,), daemon=True).start()

    # 4. Block until splash closes (server ready)
    splash.mainloop()

    # 5. If daemon crashed, exit instead of opening webview
    if server_process and server_process.poll() is not None:
        logger.info("Daemon crashed. Exiting launcher.")
        cleanup_servers()
        sys.exit(1)

    # 6. Open the native webview window
    logger.info("Opening pywebview window.")
    try:
        api = JSApi()
        webview.create_window(
            title  = "Code Search Engine v2",
            url    = URL,
            width  = 1280,
            height = 820,
            min_size    = (960, 640),
            resizable   = True,
            text_select = True,
            js_api      = api,
        )
        webview.start(debug=True)
        logger.info("Webview window closed. Launcher exiting clean.")
    except Exception as e:
        logger.critical(f"Webview error:\n{traceback.format_exc()}")
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Webview Error",
                f"Failed to open native window.\n\nError: {e}\n\nLogs: logs/launcher_v2.log"
            )
        except Exception:
            pass
        sys.exit(1)
    finally:
        cleanup_servers()
