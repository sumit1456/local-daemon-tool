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
from codeengine.api.sandbox import router as sandbox_router
from codeengine.database.sqlite import init_db
from codeengine.core.index_engine import index_repo, start_watcher, clear_index, stop_watcher
from codeengine.core.embedding_engine import get_status as get_embedding_status
from codeengine.api.search import _run_embedding
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
    from codeengine.core.sandbox_engine import stop_all_sandboxes
    stop_all_sandboxes()
    logger.info("All sandbox containers stopped.")

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
app.include_router(sandbox_router)

@app.get("/workspace")
async def get_workspace():
    """Return the workspace path mounted inside the container (or host path)."""
    ws = os.environ.get("REPO_PATH", "/workspace")
    exists = Path(ws).is_dir()
    return {"path": ws, "exists": exists}


@app.get("/workspace/list")
async def list_workspace():
    """List subdirectories inside /workspace that look like repos."""
    ws = Path("/workspace")
    if not ws.is_dir():
        return {"repos": [], "workspace": str(ws)}
    repos = []
    for entry in sorted(ws.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name in ("__pycache__", "node_modules", ".venv", "venv"):
            continue
        has_git = (entry / ".git").is_dir()
        # Count code files recursively (shallow)
        code_exts = {".py", ".js", ".ts", ".java", ".go", ".rs", ".rb", ".cpp", ".c", ".h"}
        code_count = sum(1 for f in entry.rglob("*") if f.suffix in code_exts and ".venv" not in str(f) and "node_modules" not in str(f))
        repos.append({
            "name": entry.name,
            "path": str(entry),
            "has_git": has_git,
            "code_files": code_count,
        })
    return {"repos": repos, "workspace": str(ws)}

@app.post("/reindex")
async def reindex_repo(body: ReindexRequest):
    repo_path = body.repo_path
    # Resolve relative paths against /workspace inside the container
    p = Path(repo_path)
    if not p.is_absolute():
        ws = Path("/workspace")
        candidate = ws / repo_path
        if candidate.is_dir():
            repo_path = str(candidate)
    os.environ["REPO_PATH"] = repo_path
    await clear_index()
    count = await index_repo(repo_path)
    start_watcher(repo_path)
    # Auto-start embedding if toggle is ON
    if get_embedding_status().get("enabled") and count > 0:
        import asyncio
        asyncio.create_task(_run_embedding())
    return {"status": "ok", "indexed": count, "repo": repo_path}


@app.post("/git-index")
async def git_index_route():
    """Index git commit history for all currently indexed symbols."""
    from codeengine.core.git_engine import index_git_history
    repo = os.getenv("REPO_PATH", ".")
    count = await index_git_history(repo)
    return {"indexed_commits": count}


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
                # Auto-start embedding if toggle is ON
                if get_embedding_status().get("enabled") and count > 0:
                    asyncio.create_task(_run_embedding())
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


@app.get("/tools")
async def get_tools():
    """Return comprehensive documentation about all tools, capabilities, and tradeoffs for agents."""
    return {
        "name": "CodeSearchEngine",
        "version": "1.0.0",
        "description": "MCP-based code search and editing engine with AST analysis, call graph, and dependency tracking.",
        "tools": {
            "search": {
                "search_code": {
                    "description": "Search source code using ripgrep. Returns matching lines with file, line number, and snippet.",
                    "params": {"q": "string (required)", "path": "string (default: '.')", "lang": "python|javascript|typescript|java|go|rust", "limit": "int (default: 50)"},
                    "token_cost": "~300-500 tokens",
                    "use_when": "Finding text patterns, function names, variable references, string literals",
                    "tradeoff": "Slower than native grep due to HTTP overhead, but integrates with other tools for context."
                },
                "search_symbol": {
                    "description": "Search AST symbol index for functions, classes, methods by name. Returns compact format: name:kind:file:line_start-line_end. Agent can call extract_function directly on results.",
                    "params": {"name": "string (required)", "kind": "function|class|method|interface"},
                    "token_cost": "~50-100 tokens",
                    "use_when": "Finding exact symbol definitions, locating where a function/class is defined",
                    "tradeoff": "AST-aware (kind + line ranges). Requires indexed repo. For simple grep, use native search_code."
                },
                "find_file": {
                    "description": "Find files by name pattern using fd.",
                    "params": {"pattern": "string (glob pattern)", "root": "string (default: '.')"},
                    "token_cost": "~50-100 tokens",
                    "use_when": "Locating files by name, finding config files, finding test files",
                    "tradeoff": "Slower than native fd/glob, but useful when combined with other MCP tools."
                },
                "search_usages": {
                    "description": "Find all references including imports, type annotations, variable references.",
                    "params": {"symbol_name": "string (required)", "limit": "int (default: 50)"},
                    "token_cost": "~200-500 tokens",
                    "use_when": "Finding all usages of a symbol, not just direct callers",
                    "tradeoff": "More comprehensive than get_callers."
                },
                "read_file": {
                    "description": "Read full content of a file.",
                    "params": {"file": "string (required, relative path)"},
                    "token_cost": "~100-500 tokens",
                    "use_when": "Reading file content when extract_function is not sufficient",
                    "tradeoff": "Returns full file, use extract_function for specific functions."
                },
                "get_index": {
                    "description": "Get file and symbol index for the repository. Cheap — no file reads.",
                    "params": {"files": "list of strings", "dir": "directory prefix filter", "package": "package path filter", "q": "substring match on file path", "limit": "int (default: 50)", "offset": "int (default: 0)"},
                    "token_cost": "~200-500 tokens",
                    "use_when": "Getting overview of repo structure, finding files by directory, pagination",
                    "tradeoff": "Good for scoped searches. Use for initial exploration."
                },
                "get_overview": {
                    "description": "Get compact file listing + call graph edges. Requires at least one filter (dir, package, query, or files). Returns flattened symbols and grouped edges (~3KB for 10 files).",
                    "params": {"files": "list of strings", "dir": "directory prefix filter", "package": "package path filter", "q": "substring match on file path", "limit": "int (default: 50)", "offset": "int (default: 0)"},
                    "token_cost": "~200-500 tokens",
                    "use_when": "Zooming into a directory or package, understanding call graph for a code area",
                    "tradeoff": "Requires filter. Compact format saves tokens vs old verbose format."
                }
            },
            "ast_extraction": {
                "extract_function": {
                    "description": "Extract exact source code of a single function using tree-sitter AST.",
                    "params": {"file": "string (relative path)", "name": "string (exact function name)"},
                    "token_cost": "~50-150 tokens",
                    "use_when": "Reading a specific function without reading the whole file",
                    "tradeoff": "Very efficient. Only returns the function body."
                },
                "extract_class": {
                    "description": "Extract exact source code of a single class using tree-sitter AST.",
                    "params": {"file": "string (relative path)", "name": "string (exact class name)"},
                    "token_cost": "~100-300 tokens",
                    "use_when": "Reading a specific class without reading the whole file",
                    "tradeoff": "May be large for complex classes."
                },
                "extract_by_name": {
                    "description": "Search for a symbol by name and extract its signature/body in one call.",
                    "params": {"name": "string (required)", "kind": "function|class|method|interface", "extract": "signature|body|both"},
                    "token_cost": "~100-300 tokens",
                    "use_when": "Finding and extracting a symbol without knowing its file",
                    "tradeoff": "Searches across all files."
                },
                "get_signature": {
                    "description": "Get only the signature and docstring of a function — NOT the full body.",
                    "params": {"file": "string", "line_start": "int", "line_end": "int"},
                    "token_cost": "~30-80 tokens",
                    "use_when": "Understanding function API without implementation details",
                    "tradeoff": "Cheapest way to understand what a function does."
                },
                "get_body": {
                    "description": "Get full function body by line range (no surrounding noise).",
                    "params": {"file": "string", "line_start": "int", "line_end": "int"},
                    "token_cost": "~200-500 tokens",
                    "use_when": "Reading function implementation after locating it",
                    "tradeoff": "Requires knowing line numbers. Use extract_function if you know the name."
                }
            },
            "call_graph": {
                "get_callers": {
                    "description": "Find all functions that call the given symbol.",
                    "params": {"symbol_name": "string (required)", "file": "string", "dir": "string", "package": "string"},
                    "token_cost": "~200-500 tokens",
                    "use_when": "Understanding who depends on a function, blast radius analysis",
                    "tradeoff": "Essential for impact analysis."
                },
                "get_callees": {
                    "description": "Find all functions called by the given symbol.",
                    "params": {"symbol_name": "string (required)", "file": "string", "dir": "string", "package": "string"},
                    "token_cost": "~200-500 tokens",
                    "use_when": "Understanding function dependencies, what a function relies on",
                    "tradeoff": "Use with get_callers for full call graph picture."
                },
                "trace_execution": {
                    "description": "Trace execution flow through the application from a given symbol.",
                    "params": {"symbol_name": "string (required)", "max_depth": "int (default: 5)"},
                    "token_cost": "~500-1000 tokens",
                    "use_when": "Understanding call chains, debugging execution flow",
                    "tradeoff": "Expensive but invaluable for complex debugging."
                },
                "trace_endpoint_flow": {
                    "description": "Trace complete execution path from an entry point through all callees.",
                    "params": {"entry_point": "string (required)", "max_depth": "int (default: 8)"},
                    "token_cost": "~200-400 tokens",
                    "use_when": "Tracing API routes, CLI commands, event handlers",
                    "tradeoff": "Saves 5-10 file reads vs manual tracing."
                }
            },
            "dependencies": {
                "get_imports": {
                    "description": "Get all imports used by a file.",
                    "params": {"file": "string (required, relative path)"},
                    "token_cost": "~50-100 tokens",
                    "use_when": "Understanding file dependencies",
                    "tradeoff": "Quick overview of what a file needs."
                },
                "get_importers": {
                    "description": "Find all files that import a given module (reverse dependency lookup).",
                    "params": {"module": "string (required)"},
                    "token_cost": "~200-500 tokens",
                    "use_when": "Finding who depends on a module, blast radius before changes",
                    "tradeoff": "Essential for safe refactoring."
                },
                "get_file_deps": {
                    "description": "Get complete dependency picture for a file — both directions.",
                    "params": {"file": "string (required)"},
                    "token_cost": "~300-600 tokens",
                    "use_when": "Full dependency analysis for a file",
                    "tradeoff": "One call gives both imports and importers."
                }
            },
            "analysis": {
                "get_edit_context": {
                    "description": "Get all structured context required to edit a symbol without reading the whole file.",
                    "params": {"symbol": "string (required)", "file": "string", "dir": "string", "package": "string"},
                    "token_cost": "~150-300 tokens",
                    "use_when": "Before editing a function/class, understanding its context",
                    "tradeoff": "Returns source, callers, callees, imports in one call."
                },
                "count_references": {
                    "description": "Count how many times a symbol is referenced across the codebase.",
                    "params": {"symbol_name": "string (required)"},
                    "token_cost": "~100-300 tokens",
                    "use_when": "Risk assessment before making changes",
                    "tradeoff": "Quick check of how widely used a symbol is."
                },
                "impact_analysis": {
                    "description": "Full impact assessment before changing a symbol.",
                    "params": {"symbol_name": "string (required)"},
                    "token_cost": "~500-1000 tokens",
                    "use_when": "Before major refactoring, understanding blast radius",
                    "tradeoff": "Most comprehensive impact view."
                },
                "get_defined_symbols": {
                    "description": "Get all symbols defined in a file — functions, classes, methods, constants.",
                    "params": {"file": "string (required)"},
                    "token_cost": "~50-100 tokens",
                    "use_when": "Quick file overview without reading the full file",
                    "tradeoff": "Fast way to see what's in a file."
                },
                "get_blast_radius": {
                    "description": "Get precomputed transitive blast radius for a symbol.",
                    "params": {"symbol_name": "string (required)"},
                    "token_cost": "~100-300 tokens",
                    "use_when": "Quick blast radius check",
                    "tradeoff": "O(1) lookup, faster than impact_analysis."
                },
                "get_error_context": {
                    "description": "Diagnostic bundle for compiler/linter errors.",
                    "params": {"error_message": "string (required)", "file": "string (required)", "line": "int (required)"},
                    "token_cost": "~200-500 tokens",
                    "use_when": "Debugging compiler or linter errors",
                    "tradeoff": "Includes type signatures, enclosing function, imports, callers."
                }
            },
            "editing": {
                "preview_smart_edit": {
                    "description": "Preview a smart block-based code edit as a unified diff WITHOUT writing to disk.",
                    "params": {"file": "string", "new_code": "string"},
                    "token_cost": "~100-200 tokens",
                    "use_when": "Replacing entire blocks (functions, classes) with new code",
                    "tradeoff": "Auto-detects which block to replace."
                },
                "apply_smart_edit": {
                    "description": "Apply a smart edit preview to disk and create a git commit.",
                    "params": {"edit_id": "string (from preview_smart_edit)"},
                    "token_cost": "~50-100 tokens",
                    "use_when": "After preview_smart_edit confirms the change",
                    "tradeoff": "Creates a git commit."
                },
                "get_edit_context": {
                    "description": "Get all structured context required to edit a symbol without reading the whole file.",
                    "params": {"symbol": "string (required)", "file": "string", "dir": "string", "package": "string"},
                    "token_cost": "~150-300 tokens",
                    "use_when": "Before editing a function/class, understanding its context",
                    "tradeoff": "Returns source, callers, callees, imports in one call."
                }
            },
            "utility": {
                "ping": {
                    "description": "Check if the daemon is running.",
                    "params": {},
                    "token_cost": "~20 tokens",
                    "use_when": "Verifying daemon availability",
                    "tradeoff": "Very cheap."
                },
                "list_workspace": {
                    "description": "List available repositories in workspace.",
                    "params": {},
                    "token_cost": "~50-100 tokens",
                    "use_when": "Discovering repos to index",
                    "tradeoff": "Returns repo names, paths, git status, code file counts."
                },
                "parse_blocks": {
                    "description": "Parse code into structural blocks (functions, classes).",
                    "params": {"code": "string (required)", "file_hint": "string", "lang_hint": "string"},
                    "token_cost": "~100-200 tokens",
                    "use_when": "Understanding code structure before editing",
                    "tradeoff": "AST-aware parsing."
                },
                "detect_snippet": {
                    "description": "Locate a code snippet's original source in the codebase.",
                    "params": {"code": "string (required)", "file_hint": "string", "lang_hint": "string"},
                    "token_cost": "~100-200 tokens",
                    "use_when": "Finding where a code snippet came from",
                    "tradeoff": "Searches indexed symbols."
                }
            }
        },
        "workflow": {
            "recommended": [
                "1. Use get_index or search_symbol to locate symbols",
                "2. Use get_edit_context to understand the symbol before editing",
                "3. Use preview_smart_edit to stage changes",
                "4. Use apply_smart_edit to commit"
            ],
            "token_optimization": [
                "Use extract_function/extract_class instead of reading full files",
                "Use get_edit_context for structured context (callers, callees, imports)",
                "Use get_defined_symbols for quick file overview",
                "Use count_references before modifying widely-used symbols",
                "Batch parallel tool calls when possible"
            ]
        },
        "tradeoffs_summary": {
            "mcp_vs_native": {
                "slower_than_native": ["search_code (use native grep)", "find_file (use native fd/glob)", "get_index (use native ls/find)"],
                "worth_the_overhead": ["extract_function/extract_class", "get_edit_context", "get_callers/get_callees", "trace_execution", "get_importers", "search_symbol", "get_file_deps"],
                "rule_of_thumb": "Use native tools for file finding and simple text search. Use MCP for AST extraction, call graph analysis, dependency tracing, and structured context."
            },
            "token_costs": {
                "cheap": ["get_defined_symbols (~50-80)", "get_signature (~30-80)", "find_file (~50-100)", "get_imports (~50-100)", "extract_function (~50-150)", "count_references (~100-300)", "search_symbol (~50-100)"],
                "moderate": ["search_code (~300-500)", "get_edit_context (~200-500)", "get_callers (~200-500)", "get_callees (~200-500)", "get_body (~200-500)", "get_importers (~200-500)", "get_file_deps (~300-600)", "get_index (~200-500)", "get_overview (~200-500)"],
                "expensive": ["trace_execution (~500-1000)", "impact_analysis (~500-1000)", "extract_class (~100-300 for small, 500+ for large)"]
            }
        }
    }
