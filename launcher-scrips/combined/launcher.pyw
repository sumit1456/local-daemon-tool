"""
launcher.pyw — Code Search Engine combined desktop launcher.

The .pyw extension suppresses the console window on Windows.
Double-click this file (or run: pythonw launcher.pyw) to start both
FastAPI daemon (port 8000) and the MCP server, ensuring a fresh restart of both.
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
_root = os.path.dirname(os.path.dirname(_here))
_venv_scripts = "Scripts" if os.name == "nt" else "bin"
_venv_site = os.path.join(_root, ".venv", "Lib" if os.name == "nt" else "lib", "site-packages")
if os.path.isdir(_venv_site) and _venv_site not in sys.path:
    sys.path.insert(0, _venv_site)

# ── Platform helpers ────────────────────────────────────────────────────────
_IS_WINDOWS = os.name == "nt"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0
_IS_HEADLESS = (
    os.name != "nt"
    and not os.environ.get("DISPLAY")
    and not os.environ.get("WAYLAND_DISPLAY")
)

# ── Setup Logging immediately ────────────────────────────────────────────────
os.makedirs(os.path.join(_root, "logs"), exist_ok=True)
log_file = os.path.join(_root, "logs", "launcher.log")

logging.basicConfig(
    filename=log_file,
    filemode="w",
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("launcher")

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


logger.info("Launcher started.")
logger.info(f"Site packages path injected: {_venv_site}")

# ── Verify .venv exists — auto-setup if missing ─────────────────────────────
_venv_python = os.path.join(_root, ".venv", _venv_scripts, "python.exe" if _IS_WINDOWS else "python")
if not os.path.isfile(_venv_python):
    setup_script = os.path.join(_root, "setup.bat" if _IS_WINDOWS else "setup.sh")
    if os.path.isfile(setup_script):
        logger.info(".venv not found, running setup ...")
        if not _IS_HEADLESS:
            try:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showinfo(
                    "First-Time Setup",
                    "Virtual environment not found.\n\n"
                    "Running setup to install dependencies.\n"
                    "This may take a few minutes..."
                )
                root.destroy()
            except Exception:
                pass
        if _IS_WINDOWS:
            subprocess.run(["cmd", "/c", setup_script], cwd=_root)
        else:
            subprocess.run(["bash", setup_script], cwd=_root)
        if not os.path.isfile(_venv_python):
            logger.error("Setup completed but .venv still missing.")
            sys.exit(1)
        logger.info("Setup complete, continuing launch.")
    else:
        logger.error("No .venv found at: %s", _venv_python)
        sys.exit(1)

# ── Import uvicorn (always needed); tkinter/webview only for GUI mode ───────
import uvicorn
if not _IS_HEADLESS:
    try:
        import tkinter as tk
        from tkinter import messagebox
        from tkinter import filedialog
        import webview
        logger.info("Successfully imported tkinter, webview, and uvicorn.")
    except Exception as e:
        logger.critical(f"Failed to import GUI dependencies:\n{traceback.format_exc()}")
        sys.exit(1)
else:
    logger.info("Headless mode detected. Skipping GUI imports.")

# ─────────────────────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 8000
URL  = f"http://{HOST}:{PORT}"

server_process = None
mcp_process = None

# File used by FastAPI /restart-mcp to signal a restart
_MCP_PID_FILE = os.path.join(_root, ".mcp_pid")


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

    # Clean up PID files
    for pf in (_MCP_PID_FILE,):
        try:
            if os.path.isfile(pf):
                os.remove(pf)
        except Exception:
            pass


atexit.register(cleanup_servers)


def _signal_handler(signum, frame):
    logger.info("Signal %s received, cleaning up.", signum)
    cleanup_servers()
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


if not _IS_HEADLESS:
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

            c.create_rectangle(0, 0, W, 3,  fill="#2b4e7a", outline="")
            c.create_rectangle(0, 3, W, 5,  fill="#1a3254", outline="")
            c.create_rectangle(0, 5, W, 7,  fill="#11213a", outline="")

            self.close_btn = c.create_text(W - 20, 20, text="\u2715",
                                           font=("Segoe UI", 11, "bold"),
                                           fill=self.MUTED)
            c.tag_bind(self.close_btn, "<Button-1>", lambda e: self.exit_launcher())
            c.tag_bind(self.close_btn, "<Enter>", lambda e: c.itemconfigure(self.close_btn, fill="#fc8181"))
            c.tag_bind(self.close_btn, "<Leave>", lambda e: c.itemconfigure(self.close_btn, fill=self.MUTED))

            ix, iy = W//2, 78
            c.create_rectangle(ix-32, iy-32, ix+32, iy+32,
                               fill="#111827", outline=self.ACCENT, width=1)
            for r, a in [(38, "#0d1f38"), (45, "#0a1828"), (52, "#080f1c")]:
                c.create_oval(ix-r, iy-r, ix+r, iy+r, outline=a, width=1)
            c.create_text(ix, iy, text="\u26a1", font=("Segoe UI Emoji", 28), fill="#63b3ed")

            c.create_text(W//2, 130,
                          text="Code Search Engine",
                          font=("Segoe UI Semibold", 20, "bold"),
                          fill=self.TEXT)
            c.create_text(W//2, 154,
                          text="FastAPI + MCP Server",
                          font=("Segoe UI", 10),
                          fill=self.SUBTEXT)

            c.create_line(80, 182, W-80, 182, fill=self.BORDER, width=1)

            bx1, by1 = 72,  215
            bx2, by2 = W-72, 233
            c.create_rectangle(bx1-1, by1-1, bx2+1, by2+1, outline="#1e2d45", width=1, fill="")
            c.create_rectangle(bx1, by1, bx2, by2, fill="#0e1420", outline="")

            self._bx1, self._by1 = bx1, by1
            self._bx2, self._by2 = bx2, by2
            self._fill = c.create_rectangle(bx1, by1, bx1, by2, fill=self.ACCENT, outline="")
            self._shimmer = c.create_rectangle(bx1, by1, bx1, by1+2, fill=self.GLOW, outline="")
            self._pct = c.create_text(W-80, (by1+by2)//2, text="0%", font=("Segoe UI", 8, "bold"), fill=self.MUTED)

            self._status = c.create_text(W//2, 258, text="Initializing\u2026", font=("Segoe UI", 9), fill=self.SUBTEXT)

            self._daemon_status = c.create_text(120, 298, text="\u25cf FastAPI: starting\u2026", font=("Segoe UI", 9), fill=self.SUBTEXT, anchor="w")
            self._mcp_status = c.create_text(W-240, 298, text="\u25cf MCP: starting\u2026", font=("Segoe UI", 9), fill=self.SUBTEXT, anchor="w")

            self._dots = [
                c.create_oval(W//2-22+i*16, 278, W//2-14+i*16, 286, fill=self.BORDER, outline="")
                for i in range(5)
            ]

            c.create_rectangle(0, H-30, W, H, fill=self.SURFACE, outline="")
            c.create_line(0, H-30, W, H-30, fill=self.BORDER, width=1)
            c.create_text(W//2, H-15, text="v2.0.0  \u00b7  Stage 2  \u00b7  Code Search Engine", font=("Segoe UI", 8), fill=self.MUTED)

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
            text = "\u25cf FastAPI: ready on :8000" if ready else "\u25cf FastAPI: starting\u2026"
            color = self.SUCCESS if ready else self.SUBTEXT
            self.root.after(0, lambda: (
                self.canvas.itemconfigure(self._daemon_status, text=text, fill=color)
            ))

        def set_mcp_status(self, ready: bool):
            text = "\u25cf MCP: ready (stdio)" if ready else "\u25cf MCP: starting\u2026"
            color = self.SUCCESS if ready else self.SUBTEXT
            self.root.after(0, lambda: (
                self.canvas.itemconfigure(self._mcp_status, text=text, fill=color)
            ))

        def close_after(self, ms: int = 400):
            self.root.after(ms, self.root.destroy)

        def mainloop(self):
            self.root.mainloop()


    def server_waiter(splash: SplashScreen) -> None:
        """Wait for both servers to start, then close splash."""
        splash.update(0.1, "Starting FastAPI daemon\u2026")
        time.sleep(1.0)

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
                    f"FastAPI daemon failed to start.\n\n{error_details}\n\nLogs: logs/launcher.log"
                )
            splash.root.after(0, show_error)
            return

        splash.set_daemon_status(True)
        splash.update(0.5, "Starting MCP server\u2026")
        time.sleep(0.5)

        if mcp_process and mcp_process.poll() is not None:
            logger.warning("MCP server died, continuing without MCP.")
            splash.set_mcp_status(False)
        else:
            splash.set_mcp_status(True)

        splash.update(1.0, "Ready!  Launching\u2026")
        splash.close_after(500)


# ══════════════════════════════════════════════════════════════════════════════
#  BACKEND
# ══════════════════════════════════════════════════════════════════════════════

def kill_stale_processes():
    """Kill any existing process bound to our port and any stale mcp servers so we start fresh."""
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((HOST, PORT))
        sock.close()
        if result == 0:
            logger.info("Port %d is in use, killing stale process.", PORT)
            if _IS_WINDOWS:
                import re
                out = subprocess.check_output(
                    ["netstat", "-ano", "-p", "tcp"],
                    creationflags=_NO_WINDOW,
                ).decode(errors="replace")
                for line in out.splitlines():
                    if f":{PORT}" in line and "LISTENING" in line:
                        parts = line.split()
                        stale_pid = int(parts[-1])
                        logger.info("Killing stale server PID=%d", stale_pid)
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(stale_pid)],
                            creationflags=_NO_WINDOW,
                            capture_output=True,
                        )
                        time.sleep(0.5)
                        break
            else:
                subprocess.run(["fuser", "-k", f"{PORT}/tcp"], capture_output=True)
                time.sleep(0.5)
    except Exception as e:
        logger.warning("Could not check/kill stale server: %s", e)

    # Kill any stale mcp_server.py processes running on the machine
    try:
        logger.info("Killing any stale mcp_server.py processes.")
        if _IS_WINDOWS:
            # Use PowerShell instead of deprecated wmic
            ps_cmd = (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -like '*mcp_server.py*' -and $_.ProcessId -ne $PID } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                creationflags=_NO_WINDOW,
                capture_output=True
            )
        else:
            subprocess.run(["pkill", "-f", "mcp_server.py"], capture_output=True)
    except Exception as e:
        logger.warning("Could not kill stale MCP server processes: %s", e)


def start_daemon():
    """Start the FastAPI/Uvicorn daemon on port 8000."""
    global server_process

    os.chdir(_root)
    kill_stale_processes()

    venv_python = os.path.join(_root, ".venv", _venv_scripts, "python.exe" if _IS_WINDOWS else "python")
    env = os.environ.copy()
    env["PYTHONPATH"] = _root

    server_process = subprocess.Popen(
        [
            venv_python,
            "-m", "uvicorn",
            "codeengine.app:app",
            "--host", HOST,
            "--port", str(PORT),
            "--log-level", "debug",
            "--reload",
        ],
        cwd=_root,
        env=env,
        creationflags=_NO_WINDOW,
    )

    logger.info("Started FastAPI daemon pid=%s", server_process.pid)

    # Start a monitor thread that auto-restarts the daemon if it exits
    threading.Thread(target=_monitor_daemon, daemon=True).start()


def _monitor_daemon():
    """Watch the daemon process; restart it if it exits cleanly (e.g. /restart)."""
    global server_process
    restart_delay = 1.5  # seconds before restart

    while True:
        if server_process is None:
            break
        ret = server_process.wait()
        logger.info("FastAPI daemon exited with code %s", ret)
        if ret == 0 or ret == -2:  # 0 = clean exit, -2 = SIGINT
            logger.info("Auto-restarting FastAPI daemon in %.1fs...", restart_delay)
            time.sleep(restart_delay)
            start_daemon_single()
        else:
            logger.warning("Daemon crashed (exit %s), NOT auto-restarting.", ret)
            break


def start_daemon_single():
    """Start a single daemon instance (used by auto-restart)."""
    global server_process
    venv_python = os.path.join(_root, ".venv", _venv_scripts, "python.exe" if _IS_WINDOWS else "python")
    env = os.environ.copy()
    env["PYTHONPATH"] = _root

    server_process = subprocess.Popen(
        [
            venv_python,
            "-m", "uvicorn",
            "codeengine.app:app",
            "--host", HOST,
            "--port", str(PORT),
            "--log-level", "debug",
            "--reload",
        ],
        cwd=_root,
        env=env,
        creationflags=_NO_WINDOW,
    )
    logger.info("Restarted FastAPI daemon pid=%s", server_process.pid)


def start_mcp_server():
    """Start the MCP server as a background subprocess (stdio transport)."""
    global mcp_process

    os.chdir(_root)

    python_name = "python.exe" if _IS_WINDOWS else "python"
    venv_python = os.path.join(_root, ".venv-mcp", _venv_scripts, python_name)
    if not os.path.isfile(venv_python):
        venv_python = os.path.join(_root, ".venv", _venv_scripts, python_name)

    env = os.environ.copy()
    env["PYTHONPATH"] = _root
    env["PYTHONUNBUFFERED"] = "1"

    mcp_script = os.path.join(_root, "mcp_server.py")

    mcp_process = subprocess.Popen(
        [venv_python, mcp_script],
        cwd=_root,
        env=env,
        creationflags=_NO_WINDOW,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Persist PID so the FastAPI /restart-mcp endpoint can kill it
    try:
        with open(_MCP_PID_FILE, "w") as f:
            f.write(str(mcp_process.pid))
    except Exception as exc:
        logger.warning("Could not write MCP PID file: %s", exc)

    logger.info("Started MCP server pid=%s", mcp_process.pid)

    # Monitor thread — auto-restart MCP if it exits (same pattern as daemon monitor)
    threading.Thread(target=_monitor_mcp, daemon=True).start()


def _monitor_mcp():
    """Watch the MCP process; restart it if it exits cleanly."""
    global mcp_process
    restart_delay = 1.5

    while True:
        if mcp_process is None:
            break
        ret = mcp_process.wait()
        logger.info("MCP server exited with code %s", ret)
        if ret == 0 or ret == -2:
            logger.info("Auto-restarting MCP server in %.1fs...", restart_delay)
            time.sleep(restart_delay)
            _start_mcp_single()
        else:
            logger.warning("MCP server crashed (exit %s), NOT auto-restarting.", ret)
            break


def _start_mcp_single():
    """Start a single MCP instance (used by auto-restart)."""
    global mcp_process

    python_name = "python.exe" if _IS_WINDOWS else "python"
    venv_python = os.path.join(_root, ".venv-mcp", _venv_scripts, python_name)
    if not os.path.isfile(venv_python):
        venv_python = os.path.join(_root, ".venv", _venv_scripts, python_name)

    env = os.environ.copy()
    env["PYTHONPATH"] = _root
    env["PYTHONUNBUFFERED"] = "1"

    mcp_script = os.path.join(_root, "mcp_server.py")

    mcp_process = subprocess.Popen(
        [venv_python, mcp_script],
        cwd=_root,
        env=env,
        creationflags=_NO_WINDOW,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        with open(_MCP_PID_FILE, "w") as f:
            f.write(str(mcp_process.pid))
    except Exception:
        pass

    logger.info("Restarted MCP server pid=%s", mcp_process.pid)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logger.info("Starting FastAPI daemon and MCP server.")
    start_daemon()
    start_mcp_server()

    if _IS_HEADLESS:
        logger.info("Headless mode: services started, blocking with sleep loop.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            logger.info("Interrupted, shutting down.")
            cleanup_servers()
    else:
        splash = SplashScreen()
        threading.Thread(target=server_waiter, args=(splash,), daemon=True).start()
        splash.mainloop()

        if server_process and server_process.poll() is not None:
            logger.info("Daemon crashed. Exiting launcher.")
            cleanup_servers()
            sys.exit(1)

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
            sys.exit(1)
        finally:
            cleanup_servers()
