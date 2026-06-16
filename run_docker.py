"""
not recommended to useg
run_docker.py — Launch Code Search Engine in Docker.

Runs the FastAPI daemon inside a container while keeping
the MCP server and pywebview UI on the host.

Usage:
    python run_docker.py              # reuse existing image
    python run_docker.py --rebuild    # force rebuild the image
"""

import os
import sys
import json
import time
import signal
import atexit
import shutil
import subprocess
from pathlib import Path

# ── Ensure we're running from the host .venv ─────────────────────────────────
_here = Path(__file__).resolve().parent
_venv_site = _here / ".venv" / "Lib" / "site-packages"
if _venv_site.is_dir() and str(_venv_site) not in sys.path:
    sys.path.insert(0, str(_venv_site))

# ── Flags ────────────────────────────────────────────────────────────────────

FORCE_REBUILD = "--rebuild" in sys.argv

# ── Constants ────────────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.json"
IMAGE_NAME = "codeengine-daemon"
CONTAINER_NAME = "codeengine-daemon"
HOST_PORT = 8000
DAEMON_URL = f"http://127.0.0.1:{HOST_PORT}"
TOOL_DIR_NAME = "local-daemon-tool"


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def find_tool_dir(folder: str) -> Path | None:
    """Auto-detect local-daemon-tool inside the selected folder."""
    candidate = Path(folder) / TOOL_DIR_NAME
    if candidate.is_dir():
        return candidate
    # Maybe the folder itself IS the tool dir
    if (Path(folder) / "codeengine").is_dir():
        return Path(folder)
    return None


def find_mount_root(selected_folder: str) -> Path:
    """Return the user's home directory so all repos on the PC are accessible."""
    return Path.home()


def check_docker() -> bool:
    """Return True if Docker daemon is reachable."""
    try:
        r = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def docker_running_hint():
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Docker Not Running",
        "Docker Desktop daemon is not running.\n\n"
        "Please start Docker Desktop and try again."
    )
    root.destroy()


def pick_folder(initial: str = "") -> str | None:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    result = filedialog.askdirectory(
        initialdir=initial,
        title="Select Repository Folder to Analyze",
        parent=root,
    )
    root.destroy()
    return result if result else None


# ── Docker operations ────────────────────────────────────────────────────────

def image_exists() -> bool:
    """Check if the codeengine-daemon image already exists locally."""
    r = subprocess.run(
        ["docker", "image", "inspect", IMAGE_NAME],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return r.returncode == 0


def prune_dangling_images():
    """Remove old dangling images left from previous builds."""
    print("[build] Pruning dangling images ...")
    subprocess.run(
        ["docker", "image", "prune", "-f"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def build_image(tool_dir: Path) -> bool:
    if image_exists() and not FORCE_REBUILD:
        print(f"[build] Image '{IMAGE_NAME}' already exists. Skipping build.")
        print("[build]   Use --rebuild to force a fresh build.")
        return True

    print(f"[build] Building {IMAGE_NAME} from {tool_dir} ...")
    r = subprocess.run(
        ["docker", "build", "-t", IMAGE_NAME, "."],
        cwd=str(tool_dir),
        capture_output=False,
    )
    if r.returncode != 0:
        print("[build] ERROR: Docker build failed.")
        return False

    prune_dangling_images()
    print("[build] Image built successfully.")
    return True


def stop_container():
    print("[docker] Stopping container ...")
    subprocess.run(
        ["docker", "stop", CONTAINER_NAME],
        capture_output=True,
        timeout=15,
    )
    subprocess.run(
        ["docker", "rm", CONTAINER_NAME],
        capture_output=True,
        timeout=10,
    )
    print("[docker] Container stopped and removed.")


def run_container(workspace: Path) -> subprocess.Popen | None:
    """
    Start the container in detached mode.
    Returns the Popen handle (for logs) or None on failure.
    """
    workspace_mount = f"{workspace}:/workspace"

    cmd = [
        "docker", "run",
        "--name", CONTAINER_NAME,
        "-d",
        "-p", f"{HOST_PORT}:8000",
        "-v", workspace_mount,
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        IMAGE_NAME,
    ]

    print(f"[docker] Starting container (workspace={workspace}) ...")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if r.returncode != 0:
        print(f"[docker] ERROR: {r.stderr.strip()}")
        return None

    cid = r.stdout.strip()[:12]
    print(f"[docker] Container started: {cid}")
    return r


def wait_for_daemon(timeout: float = 30.0) -> bool:
    """Poll the FastAPI daemon until it responds or timeout."""
    import urllib.request
    import urllib.error

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(DAEMON_URL + "/docs", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


# ── MCP server (host side) ──────────────────────────────────────────────────

mcp_process: subprocess.Popen | None = None


def start_mcp_server(tool_dir: Path):
    global mcp_process

    venv_python = tool_dir / ".venv-mcp" / "Scripts" / "python.exe"
    if not venv_python.is_file():
        venv_python = tool_dir / ".venv" / "Scripts" / "python.exe"
    if not venv_python.is_file():
        venv_python = shutil.which("python")

    mcp_script = tool_dir / "mcp_server.py"
    if not mcp_script.is_file():
        print("[mcp] WARNING: mcp_server.py not found, skipping MCP.")
        return

    env = os.environ.copy()
    env["PYTHONPATH"] = str(tool_dir)

    mcp_process = subprocess.Popen(
        [str(venv_python), str(mcp_script)],
        cwd=str(tool_dir),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    print(f"[mcp] MCP server started (pid={mcp_process.pid})")


def stop_mcp_server():
    global mcp_process
    if mcp_process is None:
        return
    try:
        if mcp_process.poll() is None:
            mcp_process.terminate()
            try:
                mcp_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                mcp_process.kill()
    except Exception:
        pass
    mcp_process = None
    print("[mcp] MCP server stopped.")


# ── Cleanup ──────────────────────────────────────────────────────────────────

def cleanup():
    stop_container()
    stop_mcp_server()


atexit.register(cleanup)


def signal_handler(signum, frame):
    cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # 0. Check host-side dependencies
    try:
        import tkinter  # noqa: F401
        import webview  # noqa: F401
    except ImportError as e:
        print(f"[launcher] ERROR: Missing host dependency: {e}")
        print(f"[launcher] Run:  {_here / '.venv' / 'Scripts' / 'pip.exe'} install pywebview")
        print(f"[launcher] Or use: {_here / '.venv' / 'Scripts' / 'python.exe'} run_docker.py")
        sys.exit(1)

    # 1. Check Docker
    if not check_docker():
        docker_running_hint()
        sys.exit(1)

    # 2. Pick workspace (or use cached)
    cfg = load_config()
    workspace = cfg.get("workspace")
    tool_dir = cfg.get("tool_dir")

    # Validate cached paths
    if workspace and tool_dir:
        if not Path(workspace).is_dir() or not Path(tool_dir).is_dir():
            workspace = None
            tool_dir = None

    if not workspace:
        folder = pick_folder()
        if not folder:
            print("[launcher] No folder selected. Exiting.")
            sys.exit(0)

        detected = find_tool_dir(folder)
        if detected is None:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Tool Not Found",
                f"Could not find '{TOOL_DIR_NAME}' inside:\n{folder}\n\n"
                "Please select the repository root that contains it."
            )
            root.destroy()
            sys.exit(1)

        tool_dir = str(detected)
        # Mount parent dir so sibling repos are accessible in container
        workspace = str(find_mount_root(folder))

        # Save for next time
        save_config({"workspace": workspace, "tool_dir": tool_dir})
        print(f"[launcher] Workspace (mounted): {workspace}")
        print(f"[launcher] Tool dir:  {tool_dir}")

    # 3. Stop any stale container
    stop_container()

    # 4. Build image
    if not build_image(Path(tool_dir)):
        sys.exit(1)

    # 5. Run container
    if run_container(Path(workspace)) is None:
        sys.exit(1)

    # 6. Wait for daemon
    print("[launcher] Waiting for daemon to be ready ...")
    if not wait_for_daemon(timeout=30):
        print("[launcher] ERROR: Daemon did not start in time.")
        cleanup()
        sys.exit(1)
    print("[launcher] Daemon is ready!")

    # 7. Start MCP server on host
    start_mcp_server(Path(tool_dir))

    # 8. Open pywebview
    print("[launcher] Opening UI window ...")
    try:
        webview.create_window(
            title="Code Search Engine (Docker)",
            url=DAEMON_URL,
            width=1280,
            height=820,
            min_size=(960, 640),
            resizable=True,
            text_select=True,
        )
        webview.start(debug=True)
    except Exception as e:
        print(f"[launcher] ERROR: {e}")
    finally:
        cleanup()
        print("[launcher] Done.")


if __name__ == "__main__":
    main()
