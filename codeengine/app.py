import os
from pathlib import Path
import time
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

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
    """Initialize DB, index repository, and start watcher on startup."""
    await init_db()
    repo = os.getenv("REPO_PATH", ".")
    await index_repo(repo)
    start_watcher(repo)
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
