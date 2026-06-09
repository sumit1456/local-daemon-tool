import os
import sys
import json
import logging
import asyncio
from pathlib import Path
import time
from datetime import datetime
from collections import deque
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from contextlib import asynccontextmanager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("codeengine")


# ── Log streaming infrastructure ─────────────────────────────────────────────
_log_subscribers: list = []
_log_buffer: deque = deque(maxlen=500)

class _StreamHandler(logging.Handler):
    """Push log records to SSE subscribers."""
    def emit(self, record):
        try:
            msg = self.format(record)
            entry = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": record.levelname,
                "name": record.name,
                "msg": msg,
            }
            _log_buffer.append(entry)
            for q in _log_subscribers:
                try:
                    q.put_nowait(entry)
                except asyncio.QueueFull:
                    pass
        except Exception:
            pass

_stream_handler = _StreamHandler()
_stream_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_stream_handler)


class _StdioCapture:
    """Capture stdout/stderr writes and forward to log stream."""
    def __init__(self, original, level):
        self._orig = original
        self._level = level
        self._buf = ""

    def write(self, s):
        self._orig.write(s)
        self._buf += s
        if "\n" in self._buf:
            lines = self._buf.split("\n")
            self._buf = lines.pop()
            for line in lines:
                line = line.strip()
                if line:
                    entry = {
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "level": self._level,
                        "name": "server",
                        "msg": line,
                    }
                    _log_buffer.append(entry)
                    for q in _log_subscribers:
                        try:
                            q.put_nowait(entry)
                        except asyncio.QueueFull:
                            pass

    def flush(self):
        self._orig.flush()

sys.stdout = _StdioCapture(sys.stdout, "INFO")
sys.stderr = _StdioCapture(sys.stderr, "ERROR")

def load_dotenv():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip()
                        if val.startswith(('"', "'")) and val.endswith(val[0]):
                            val = val[1:-1]
                        os.environ[key] = val
        except Exception:
            pass

load_dotenv()


from codeengine.api.search import router as search_router
from codeengine.api.edit import router as edit_router
from codeengine.api.build import router as build_router
from codeengine.database.sqlite import init_db
from codeengine.core.index_engine import index_repo, start_watcher, clear_index, stop_watcher
from pydantic import BaseModel

# Absolute path to the bundled static UI
_STATIC_DIR = Path(__file__).parent / "static"

# Lifespan handler (FastAPI v0.110+)
@asynccontextmanager
async def lifespan(app: FastAPI):

    print("1 init_db")
    await init_db()

    print("2 init_db done")

    # Indexing happens only when a directory is selected via /reindex endpoint
    # repo = os.getenv("REPO_PATH", ".")
    # print(f"3 indexing {repo}")
    # await index_repo(repo)
    # print("4 indexing complete")
    # start_watcher(repo)
    # print("5 watcher started")

    yield

    stop_watcher()
    

class ReindexRequest(BaseModel):
    repo_path: str

app = FastAPI(title="Code Search Engine", version="1.0.0", lifespan=lifespan)

# CORS — allow the pywebview embedded browser (same-origin: 127.0.0.1:8000)
# and the Vite dev server for local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://localhost:5173",   # Vite dev server (keep for local dev)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def request_logging_middleware(request, call_next):
    logging_enabled = os.getenv("LOGGING", "false").lower() == "true"
    if not logging_enabled:
        return await call_next(request)

    start_time = time.time()
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as e:
        status_code = 500
        raise e
    finally:
        duration = (time.time() - start_time) * 1000
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        method = request.method
        path = request.url.path
        
        log_dir = Path(__file__).resolve().parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "requests.log"
        try:
            with open(log_file, "a", encoding="utf-8") as lf:
                lf.write(f"{timestamp} - {method} {path} - {status_code} - {duration:.2f}ms\n")
        except Exception:
            pass
    return response

# ── API routers ──────────────────────────────────────────────────────────────
app.include_router(search_router)
app.include_router(edit_router)
app.include_router(build_router)

@app.post("/reindex")
async def reindex_repo(body: ReindexRequest):
    os.environ["REPO_PATH"] = body.repo_path
    await clear_index()
    count = await index_repo(body.repo_path)
    start_watcher(body.repo_path)
    return {"status": "ok", "indexed": count, "repo": body.repo_path}


@app.post("/reindex/stream")
async def reindex_repo_stream(body: ReindexRequest):
    """SSE endpoint — streams indexing progress events to the frontend."""
    os.environ["REPO_PATH"] = body.repo_path

    async def event_generator():
        import asyncio, queue

        q: queue.Queue = queue.Queue()

        async def on_progress(event_type, data):
            q.put(("progress", event_type, data))

        async def run_index():
            try:
                await clear_index()
                await on_progress("clear", {})
                count = await index_repo(body.repo_path, on_progress=on_progress)
                await on_progress("watcher", {"repo": body.repo_path})
                start_watcher(body.repo_path)
            except Exception as exc:
                await on_progress("error", {"message": str(exc)})

        loop = asyncio.get_event_loop()
        index_task = asyncio.create_task(run_index())

        while not index_task.done() or not q.empty():
            try:
                kind, event_type, data = q.get_nowait()
                payload = json.dumps({"type": event_type, **data})
                yield f"data: {payload}\n\n"
            except queue.Empty:
                await asyncio.sleep(0.05)

        # Drain remaining events
        while not q.empty():
            kind, event_type, data = q.get_nowait()
            payload = json.dumps({"type": event_type, **data})
            yield f"data: {payload}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/logs/stream")
async def stream_logs():
    """SSE endpoint — streams server log output to the FastAPI terminal."""
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _log_subscribers.append(q)

    async def event_generator():
        # Replay buffered logs first
        for entry in _log_buffer:
            yield f"data: {json.dumps(entry)}\n\n"
        try:
            while True:
                entry = await asyncio.wait_for(q.get(), timeout=15)
                yield f"data: {json.dumps(entry)}\n\n"
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if q in _log_subscribers:
                _log_subscribers.remove(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Static files (served AFTER API routes to avoid shadowing) ────────────────
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# ── Root — serve the SPA shell ───────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve the bundled single-page application."""
    index = _STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(str(index), media_type="text/html")
    return {"message": "Code Search Engine API — static UI not found."}
