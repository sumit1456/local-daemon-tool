"""
mcp_server.py — Code Search Engine MCP Server

Exposes all Code Search Engine tools via the Model Context Protocol (stdio).
Agents (Claude Desktop, Aider, etc.) connect to this server and can call tools
directly without needing to run shell commands.

The local daemon must be running at http://127.0.0.1:8000.
Start it with: .venv/bin/python launcher.pyw  (Linux/Mac)
                .venv\\Scripts\\pythonw.exe launcher.pyw  (Windows)

Usage (how you configure your agent to use this):
    Command: .venv/bin/python mcp_server.py  (Linux/Mac)
             .venv\\Scripts\\python.exe mcp_server.py  (Windows)
    Transport: stdio
"""

import sys
import os
from pathlib import Path

# ── Logging and exception setup first ─────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "mcp_server.log"

try:
    import logging
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    log = logging.getLogger("mcp_server")
except Exception as e:
    # Fallback raw file logging if basicConfig fails
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"{datetime.now().isoformat()} [CRITICAL] Failed to configure logging: {e}\n")
    except Exception:
        pass
    sys.exit(1)

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log.critical("Unhandled exception in main thread", exc_info=(exc_type, exc_value, exc_traceback))
    for handler in logging.getLogger().handlers:
        handler.flush()

sys.excepthook = handle_exception

# Catch thread exceptions (Python 3.8+)
import threading
def handle_thread_exception(args):
    if issubclass(args.exc_type, KeyboardInterrupt):
        return
    log.critical("Unhandled exception in thread %s", args.thread.name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    for handler in logging.getLogger().handlers:
        handler.flush()
threading.excepthook = handle_thread_exception

try:
    import asyncio
    import httpx
    from mcp.server.fastmcp import FastMCP
    from datetime import datetime
except Exception as e:
    log.critical("Failed to import required libraries. Make sure the virtual environment '.venv-mcp' is active and dependencies are installed.", exc_info=True)
    for handler in logging.getLogger().handlers:
        handler.flush()
    sys.exit(1)

DAEMON_BASE = "http://127.0.0.1:8000"
TIMEOUT = 30.0
_REPO_PATH_CACHE: str | None = None

log.info("=" * 60)
log.info("MCP Server starting — PID %s", os.getpid())
log.info("Log file: %s", LOG_FILE)
log.info("Daemon target: %s", DAEMON_BASE)
log.info("=" * 60)
for handler in logging.getLogger().handlers:
    handler.flush()

mcp = FastMCP("CodeSearchEngine")


# ── Repo path helper ─────────────────────────────────────────────────────────

async def _get_repo_path() -> str:
    """Get the currently indexed repo path from the daemon, with local cache."""
    global _REPO_PATH_CACHE
    try:
        data = await _get("/workspace")
        _REPO_PATH_CACHE = data.get("path", ".")
        return _REPO_PATH_CACHE
    except Exception:
        return _REPO_PATH_CACHE or "."


# ── HTTP helpers ──────────────────────────────────────────────────────────────

async def _get(endpoint: str, **params) -> dict:
    """Make a GET request to the local daemon."""
    filtered = {k: v for k, v in params.items() if v is not None}
    log.debug("GET %s %s", endpoint, filtered)
    try:
        async with httpx.AsyncClient(base_url=DAEMON_BASE, timeout=TIMEOUT) as client:
            r = await client.get(endpoint, params=filtered)
            log.debug("GET %s -> %s (%dms)", endpoint, r.status_code, r.elapsed.total_seconds() * 1000)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.json().get("detail", str(e)) if e.response.content else str(e)
        return {"error": detail}
    except httpx.ConnectError:
        return {"error": "Daemon not running. Start with: pythonw launcher.pyw"}
    except Exception as e:
        return {"error": str(e)}


async def _post(endpoint: str, body: dict) -> dict:
    """Make a POST request to the local daemon."""
    log.debug("POST %s %s", endpoint, {k: v[:80] if isinstance(v, str) and len(v) > 80 else v for k, v in body.items()})
    try:
        async with httpx.AsyncClient(base_url=DAEMON_BASE, timeout=TIMEOUT) as client:
            r = await client.post(endpoint, json=body)
            log.debug("POST %s -> %s (%dms)", endpoint, r.status_code, r.elapsed.total_seconds() * 1000)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.json().get("detail", str(e)) if e.response.content else str(e)
        return {"error": detail}
    except httpx.ConnectError:
        return {"error": "Daemon not running. Start with: pythonw launcher.pyw"}
    except Exception as e:
        return {"error": str(e)}


async def _delete(endpoint: str, params: dict | None = None) -> dict:
    """Make a DELETE request to the local daemon."""
    log.debug("DELETE %s %s", endpoint, params or {})
    try:
        async with httpx.AsyncClient(base_url=DAEMON_BASE, timeout=TIMEOUT) as client:
            r = await client.delete(endpoint, params=params or {})
            log.debug("DELETE %s -> %s (%dms)", endpoint, r.status_code, r.elapsed.total_seconds() * 1000)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.json().get("detail", str(e)) if e.response.content else str(e)
        return {"error": detail}
    except httpx.ConnectError:
        return {"error": "Daemon not running. Start with: pythonw launcher.pyw"}
    except Exception as e:
        return {"error": str(e)}


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def ping() -> dict:
    """Check if the Code Search Engine daemon is running and healthy."""
    log.info("[ping] Checking daemon...")
    try:
        async with httpx.AsyncClient(base_url=DAEMON_BASE, timeout=3.0) as client:
            await client.get("/docs")
        log.info("[ping] Daemon OK")
        return {"status": "ok", "url": DAEMON_BASE}
    except Exception as e:
        log.error("[ping] Daemon offline: %s", e)
        return {
            "status": "offline",
            "message": "Daemon not running. Start the launcher for your platform."
        }


@mcp.tool()
async def reindex(repo_path: str) -> dict:
    """
    Switch the daemon to index a different repository.
    Clears the previous index and rebuilds it for the new repo.

    Args:
        repo_path: Absolute path to the repository directory to index.
    """
    global _REPO_PATH_CACHE
    log.info("[reindex] Switching to repo: %s", repo_path)
    result = await _post("/reindex", {"repo_path": repo_path})
    _REPO_PATH_CACHE = result.get("repo", repo_path)
    log.info("[reindex] Done — indexed %d files", result.get("indexed", 0))
    return result


@mcp.tool()
async def search_code(
    query: str,
    path: str = ".",
    lang: str | None = None,
    limit: int = 50,
) -> dict:
    """
    Search source code using ripgrep. Returns matching lines with file, line number, and snippet.

    IMPORTANT: For broad queries, prefer the native grep_search tool — it is more token-efficient.
    Use this tool when you need ripgrep-specific filtering (language, path scoping, etc.).

    Args:
        query: Search pattern or text to find.
        path: Root directory to search in (default: currently indexed repo).
        lang: Language filter — python | javascript | typescript | java | go | rust.
        limit: Maximum number of results to return (default: 50).
    """
    if path == ".":
        path = await _get_repo_path()
    data = await _get("/search/code", q=query, path=path, lang=lang, limit=limit)
    return {
        "query": data["query"],
        "total": data["total"],
        "matches": [
            {
                "file": m["file"],
                "line": m["line"],
                "col":  m["col"],
                "text": m["text"].strip(),
            }
            for m in data["matches"]
        ],
    }


@mcp.tool()
async def search_symbol(
    name: str,
    kind: str | None = None,
) -> dict:
    """
    Search the AST symbol index for functions, classes, and methods by name.
    Faster and more precise than text search for finding where a symbol is defined.

    Args:
        name: Symbol name to find (partial matches supported).
        kind: Optional filter — function | class | method | interface.
    """
    return await _get("/search/symbol", name=name, kind=kind)


@mcp.tool()
async def find_file(
    pattern: str,
    root: str = ".",
) -> dict:
    """
    Find files by name pattern using fd.

    Args:
        pattern: Filename pattern to search for (e.g. "*.py", "PDFRenderer").
        root: Root directory to search in (default: currently indexed repo).
    """
    if root == ".":
        root = await _get_repo_path()
    return await _get("/search/file", pattern=pattern, root=root)


@mcp.tool()
async def extract_function(
    file: str,
    name: str,
) -> dict:
    """
    Extract the exact source code of a single function using tree-sitter AST.
    Much cheaper than reading the whole file — only returns the specific function body.

    Args:
        file: Relative path to the file (e.g. "codeengine/app.py").
        name: Exact function name to extract.
    """
    return await _get("/search/function", file=file, name=name)


@mcp.tool()
async def extract_class(
    file: str,
    name: str,
) -> dict:
    """
    Extract the exact source code of a single class using tree-sitter AST.
    Much cheaper than reading the whole file — only returns the specific class block.

    Args:
        file: Relative path to the file (e.g. "codeengine/core/models.py").
        name: Exact class name to extract.
    """
    return await _get("/search/class", file=file, name=name)


@mcp.tool()
async def preview_edit(
    file: str,
    old_code: str,
    new_code: str,
) -> dict:
    """
    Stage a code edit and preview it as a unified diff WITHOUT writing to disk.
    Always call this before apply_edit to verify the change is correct.

    Args:
        file: Relative path to the file to edit.
        old_code: The exact code block to replace (must match verbatim).
        new_code: The replacement code.

    Returns an edit_id and a unified diff showing the proposed change.
    """
    return await _post("/preview-edit", {
        "file":     file,
        "old_code": old_code,
        "new_code": new_code,
    })


@mcp.tool()
async def apply_edit(edit_id: str) -> dict:
    """
    Write a previewed edit to disk and automatically create a git commit.
    You must call preview_edit first to get the edit_id.

    Args:
        edit_id: The edit_id returned by a previous preview_edit call.
    """
    return await _post("/apply-edit", {"edit_id": edit_id})


@mcp.tool()
async def undo_edit() -> dict:
    """
    Revert the last applied edit by running `git revert HEAD`.
    Use this immediately if a test fails after applying an edit.
    """
    return await _post("/undo", {})


@mcp.tool()
async def get_index(
    files: list[str] | None = None,
    dir: str | None = None,
    package: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    Get the file and symbol index for the repository. Cheap — no file reads.
    Provides a high-level map of what's in the codebase.

    Args:
        files: Optional list of specific files to scope the index to. Omit for the full repo.
        dir: Directory prefix filter (e.g. "src/core").
        package: Package path filter (e.g. "codeengine.core").
        q: Substring match on file path.
        limit: Max number of files to return (default: 50).
        offset: Number of files to skip for pagination (default: 0).
    """
    return await _get("/search/index", files=files, dir=dir, package=package, q=q, limit=limit, offset=offset)


@mcp.tool()
async def get_overview(
    files: list[str] | None = None,
    dir: str | None = None,
    package: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    Get compact file listing + call graph edges. Requires at least one filter.
    Returns flattened symbols per file and grouped call edges (~3KB for 10 files).

    Args:
        files: List of specific files to scope the overview to.
        dir: Directory prefix filter (e.g. "src/core").
        package: Package path filter (e.g. "codeengine.core").
        q: Substring match on file path.
        limit: Max number of files to return (default: 50).
        offset: Number of files to skip for pagination (default: 0).
    """
    has_filter = any([files, dir, package, q])
    if not has_filter:
        return {"error": "At least one filter required. Use dir, package, query, or files param."}
    try:
        return await _get("/search/overview", files=files, dir=dir, package=package, q=q, limit=limit, offset=offset)
    except httpx.HTTPStatusError as e:
        detail = e.response.json().get("detail", str(e)) if e.response.content else str(e)
        return {"error": detail}


@mcp.tool()
async def get_callers(symbol_name: str) -> dict:
    """
    Find all functions in the codebase that call the given symbol.
    Great for understanding the blast radius before changing a function.

    Args:
        symbol_name: Exact name of the symbol to find callers of.
    """
    return await _get("/search/callers", symbol_name=symbol_name)


@mcp.tool()
async def get_callees(symbol_name: str) -> dict:
    """
    Find all functions that are called internally by the given symbol.
    Great for understanding what a function depends on.

    Args:
        symbol_name: Exact name of the symbol to find callees of.
    """
    return await _get("/search/callees", symbol_name=symbol_name)


@mcp.tool()
async def get_signature(
    file: str,
    line_start: int,
    line_end: int,
) -> dict:
    """
    Get only the signature and docstring of a function — NOT the full body.
    The cheapest way to understand what a function does and its parameters.

    Args:
        file: Relative path to the file.
        line_start: First line number of the function.
        line_end: Last line number of the function.
    """
    return await _get(
        "/search/function-signature",
        file=file,
        line_start=line_start,
        line_end=line_end,
    )


@mcp.tool()
async def get_body(
    file: str,
    line_start: int,
    line_end: int,
) -> dict:
    """
    Get the full body of a function by line range (no surrounding noise).

    Args:
        file: Relative path to the file.
        line_start: First line number of the function.
        line_end: Last line number of the function.
    """
    return await _get(
        "/search/function-body",
        file=file,
        line_start=line_start,
        line_end=line_end,
    )


@mcp.tool()
async def detect_snippet(
    code: str,
    file_hint: str | None = None,
    lang_hint: str | None = None,
) -> dict:
    """
    Given a code snippet, detect and locate its original source block in the codebase.
    Useful for finding where a piece of code lives without knowing the file.

    Args:
        code: The code snippet to locate.
        file_hint: Optional file path hint to narrow the search.
        lang_hint: Optional language hint (e.g. "python", "javascript").
    """
    return await _post("/search/detect-original", {
        "code":           code,
        "file_path_hint": file_hint,
        "lang_hint":      lang_hint,
    })


@mcp.tool()
async def preview_smart_edit(
    file: str,
    new_code: str,
) -> dict:
    """
    Preview a smart block-based code edit as a unified diff WITHOUT writing to disk.
    Automatically detects which block in the file the new_code is replacing.

    Args:
        file: Relative path to the file to edit.
        new_code: The new code block to insert (the engine figures out what it replaces).
    """
    return await _post("/preview-smart-edit", {
        "file":     file,
        "new_code": new_code,
    })


@mcp.tool()
async def apply_smart_edit(edit_id: str) -> dict:
    """
    Apply a smart edit preview to disk and create a git commit.
    You must call preview_smart_edit first to get the edit_id.

    Args:
        edit_id: The edit_id returned by a previous preview_smart_edit call.
    """
    return await _post("/apply-smart-edit", {"edit_id": edit_id})


@mcp.tool()
async def parse_blocks(
    code: str,
    file_hint: str | None = None,
    lang_hint: str | None = None,
) -> dict:
    """
    Parse a pasted code string into its top-level structural blocks (functions, classes, etc.).
    Useful for understanding the structure of code before applying edits.

    Args:
        code: The code string to parse.
        file_hint: Optional file path hint to infer the language.
        lang_hint: Optional explicit language hint (e.g. "python", "typescript").
    """
    return await _post("/parse-blocks", {
        "code":           code,
        "file_path_hint": file_hint,
        "lang_hint":      lang_hint,
    })


@mcp.tool()
async def get_imports(file: str) -> dict:
    """
    Get all imports used by a file.
    Helps agents understand dependencies without reading the file.

    Args:
        file: Relative path to the file (e.g. "services/user_service.py").
    """
    return await _get("/search/imports", file=file)


@mcp.tool()
async def get_importers(module: str) -> dict:
    """
    Reverse dependency lookup — find all files that import a given module.
    Use this to understand the blast radius before changing a module.

    Args:
        module: Module name to search for (e.g. "utils.auth", "models.user").
    """
    return await _get("/search/importers", module=module)


@mcp.tool()
async def get_file_deps(file: str) -> dict:
    """
    Get complete dependency picture for a file — both what it imports and what imports it.
    Useful for understanding file dependencies in both directions.

    Args:
        file: Relative path to the file (e.g. "codeengine/core/search.py").
    """
    return await _get("/search/file-deps", file=file)


@mcp.tool()
async def get_type_info(symbol_name: str, file: str | None = None) -> dict:
    """
    Return parameter types and return type for a symbol.
    Prevents API misuse by showing type signatures.

    Args:
        symbol_name: Name of the function/class to get type info for.
        file: Optional file path filter to narrow results.
    """
    return await _get("/search/type-info", symbol_name=symbol_name, file=file)


@mcp.tool()
async def get_defined_symbols(file: str) -> dict:
    """
    Get all symbols defined in a file — functions, classes, methods, constants.
    Quick file overview without reading the full file.

    Args:
        file: Relative path to the file (e.g. "codeengine/core/search.py").
    """
    return await _get("/search/defined-symbols", file=file)


@mcp.tool()
async def count_references(symbol_name: str) -> dict:
    """
    Count how many times a symbol is referenced across the codebase.
    Great for risk assessment before making changes.

    Args:
        symbol_name: Name of the symbol to count references for.
    """
    return await _get("/search/count-references", symbol_name=symbol_name)


@mcp.tool()
async def impact_analysis(symbol_name: str) -> dict:
    """
    Full impact assessment before changing a symbol.
    Shows direct callers, all references, and affected files.

    Args:
        symbol_name: Name of the symbol to analyze impact for.
    """
    return await _get("/search/impact-analysis", symbol_name=symbol_name)


@mcp.tool()
async def trace_execution(symbol_name: str, max_depth: int = 5) -> dict:
    """
    Trace execution flow through the application from a given symbol.
    Shows the call chain: who calls this, who calls those callers, etc.

    Args:
        symbol_name: Name of the symbol to trace execution from.
        max_depth: Maximum call chain depth (default: 5).
    """
    return await _get("/search/trace-execution", symbol_name=symbol_name, max_depth=max_depth)


@mcp.tool()
async def get_edit_context(
    symbol: str,
    file: str | None = None,
    dir: str | None = None,
    package: str | None = None,
) -> dict:
    """
    Get all structured context required to edit a symbol without reading the whole file.
    If multiple symbols match, returns candidate details for disambiguation.

    Args:
        symbol: The name of the function, class, or method to get context for.
        file: Optional relative path filter (e.g. "codeengine/core/search.py").
        dir: Optional directory prefix filter (e.g. "codeengine/core").
        package: Optional package path filter (e.g. "codeengine.core").
    """
    log.info("[get_edit_context] symbol=%s file=%s dir=%s package=%s", symbol, file, dir, package)
    try:
        result = await _get("/search/edit-context", symbol=symbol, file=file, dir=dir, package=package)
        log.info("[get_edit_context] OK — keys=%s", list(result.keys()) if isinstance(result, dict) else f"list({len(result)} items)")
        return result
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 300:
            log.info("[get_edit_context] 300 Multiple Choices — %d candidates", len(e.response.json().get("candidates", [])))
            return e.response.json()
        log.error("[get_edit_context] HTTP %d: %s", e.response.status_code, e.response.text[:200])
        raise e
    except Exception as e:
        log.error("[get_edit_context] Error: %s", e)
        raise


# ── Missing Daemon Endpoints ─────────────────────────────────────────────────

@mcp.tool()
async def search_usages(symbol_name: str, limit: int = 50) -> dict:
    """
    Find all places where a symbol is referenced (used) in the codebase.
    Unlike get_callers which only shows direct callers, this shows all usages
    including variable references, imports, type annotations, etc.

    Args:
        symbol_name: Symbol name to find usages for.
        limit: Maximum number of results (default: 50).
    """
    return await _get("/search/usages", symbol_name=symbol_name, limit=limit)


@mcp.tool()
async def get_docstring(symbol_name: str, file: str | None = None) -> dict:
    """
    Retrieve docstrings for a symbol, optionally filtered by file.

    Args:
        symbol_name: Symbol name to get docstring for.
        file: Optional file path filter to narrow results.
    """
    return await _get("/search/docstring", symbol_name=symbol_name, file=file)


@mcp.tool()
async def read_file(file: str) -> dict:
    """
    Read full content of a file relative to the indexed repo path.

    Args:
        file: Relative path to the file (e.g. "codeengine/app.py").
    """
    return await _get("/search/file-read", file=file)


@mcp.tool()
async def sandbox_status() -> dict:
    """
    Return Docker availability and detected stack for the current repo.
    Useful to check if sandbox is ready before running check_syntax, compile_project, or run_tests.
    """
    return await _get("/sandbox/status")


@mcp.tool()
async def stop_sandbox(stack: str) -> dict:
    """
    Stop and remove a specific sandbox container.

    Args:
        stack: Stack to stop — python | node | java-maven | java-gradle | go | rust | ruby | php | cpp.
    """
    return await _delete("/sandbox/stop", params={"stack": stack})


@mcp.tool()
async def list_workspace() -> dict:
    """
    List subdirectories inside /workspace that look like repos.
    Useful for discovering available repositories to index.
    """
    return await _get("/workspace/list")


# ── New Feature Tools ────────────────────────────────────────────────────────

@mcp.tool()
async def get_blast_radius(symbol_name: str) -> dict:
    """
    Get the PRECOMPUTED full blast radius for a symbol — every function that
    transitively calls it, grouped by call depth. O(1) lookup (no live tracing).
    Much faster and cheaper than impact_analysis for large codebases.

    Args:
        symbol_name: The function or method name to check.
    """
    log.info("[get_blast_radius] symbol=%s", symbol_name)
    return await _get("/search/blast-radius", symbol=symbol_name)


@mcp.tool()
async def get_error_context(error_message: str, file: str, line: int) -> dict:
    """
    Given a compiler, linter, or runtime error, return a pre-packaged diagnostic
    bundle in a single call. Includes:
    - The exact offending line of code
    - The enclosing function (what function contains the error)
    - Type signatures of all symbols referenced in the error
    - All imports of the erroring file
    - Who calls the enclosing function (to understand the call chain)

    Use this INSTEAD of manually calling get_type_info + get_imports + get_callers
    separately. Saves 3-5 tool calls and ~1500 tokens.

    Args:
        error_message: The full compiler/linter error string.
        file: Relative path to the file with the error (e.g. "codeengine/core/search.py").
        line: The line number where the error occurred.
    """
    log.info("[get_error_context] file=%s line=%d", file, line)
    return await _get("/search/error-context", error=error_message, file=file, line=line)


@mcp.tool()
async def get_function_history(symbol_name: str, limit: int = 20) -> dict:
    """
    Return the precomputed git commit history for a specific function or class.
    Each entry is a compact record: commit hash, date, message, and change type
    (signature_change | logic_edit | new | deleted).

    Use this INSTEAD of running raw git log commands, which burn 10,000+ tokens.
    This returns a 150-token summary of the function's full change history.

    Args:
        symbol_name: The exact function or class name.
        limit: Maximum number of commits to return (default 20).
    """
    log.info("[get_function_history] symbol=%s limit=%d", symbol_name, limit)
    return await _get("/search/function-history", symbol=symbol_name, limit=limit)


@mcp.tool()
async def index_git_history() -> dict:
    """
    Trigger indexing of the git commit history for the current repository.
    Must be called once after /reindex before get_function_history works.
    Processes the last 200 commits. Run in the background (takes ~5-30 seconds).
    """
    log.info("[index_git_history] Triggering git history indexing")
    return await _post("/git-index", {})


@mcp.tool()
async def trace_endpoint_flow(entry_point: str, max_depth: int = 8) -> dict:
    """
    Trace the complete execution path from an entry point (API route handler,
    CLI command, event listener) down through all function calls to leaf nodes.

    Returns a compact call-chain tree showing: function name, file, line number,
    depth in the chain, and what it calls next.

    Use this INSTEAD of reading router → service → repository files one by one.
    Saves 5-10 file reads (~5000-8000 tokens) and gives the complete picture
    in a single call (~200-400 tokens).

    Args:
        entry_point: Function name or partial name of the entry point
                     (e.g. "search_code_route", "handle_login", "main").
        max_depth: How deep to trace the call chain (default 8).
    """
    log.info("[trace_endpoint_flow] entry=%s depth=%d", entry_point, max_depth)
    return await _get("/search/endpoint-flow", entry=entry_point, max_depth=max_depth)


@mcp.tool()
async def setup_sandbox() -> dict:
    """
    Detect the project stack and start a Docker sandbox container.
    Installs all project dependencies inside the container.
    Must be called once before using check_syntax, compile_project, or run_tests.
    Safe to call multiple times — idempotent.

    Returns: stack detected, image used, container ID, deps_installed status.
    """
    log.info("[setup_sandbox] Starting sandbox...")
    return await _post("/sandbox/setup", {})


@mcp.tool()
async def check_syntax(file: str) -> dict:
    """
    Lint a single file inside the Docker sandbox using the stack's native linter.
    Returns structured errors only — never raw linter output.

    Supported: Python (ruff), JavaScript/TypeScript (eslint/tsc),
               Java (javac), Go (go vet), Rust (cargo check).

    Fallback: If Docker is unavailable, uses Python's built-in ast.parse for .py files.

    Use this INSTEAD of running linter commands in terminal and reading all output.
    Saves 1000-3000 tokens of raw linter output per check.

    Args:
        file: Relative path to the file to lint (e.g. "src/main.py").
    """
    log.info("[check_syntax] file=%s", file)
    return await _get("/sandbox/lint", file=file)


@mcp.tool()
async def compile_project() -> dict:
    """
    Compile the entire project inside the Docker sandbox.
    Returns structured errors with file, line, column, and message.
    Never returns raw build log output.

    Token cost: ~100-300 tokens (vs 3000-8000 for reading raw build output).

    Call setup_sandbox() first if not already done.
    """
    log.info("[compile_project] Compiling project...")
    return await _post("/sandbox/compile", {})


@mcp.tool()
async def run_tests(test_path: str | None = None) -> dict:
    """
    Run the project's test suite inside the Docker sandbox.
    Returns a structured summary: total, passed, failed, and failure details.
    Never returns raw test runner output.

    Token cost: ~150-400 tokens (vs 5000-15000 for reading raw pytest/jest output).

    Args:
        test_path: Optional relative path to a specific test file or directory.
                   If None, runs all tests.
    """
    log.info("[run_tests] test_path=%s", test_path)
    return await _post("/sandbox/test", {"path": test_path} if test_path else {})


@mcp.tool()
async def install_deps() -> dict:
    """
    Reinstall all dependencies (system packages + project deps) inside the Docker sandbox.
    Useful when deps are stale or container was rebuilt.

    Call setup_sandbox() first if not already done.
    """
    log.info("[install_deps] Installing deps in sandbox...")
    return await _post("/sandbox/install-deps", {})


# ── Tools Documentation Endpoint ────────────────────────────────────────────

TOOLS_DOCS = {
    "name": "CodeSearchEngine MCP Tools",
    "description": "Complete documentation of all available MCP tools, their capabilities, and tradeoffs.",
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
                "description": "Search AST symbol index for functions, classes, methods by name. Faster and more precise than text search.",
                "params": {"name": "string (required)", "kind": "function|class|method|interface"},
                "token_cost": "~100-300 tokens",
                "use_when": "Finding exact symbol definitions, locating where a function/class is defined",
                "tradeoff": "Only finds definitions, not usages. Use get_edit_context or count_references for full picture."
            },
            "find_file": {
                "description": "Find files by name pattern using fd.",
                "params": {"pattern": "string (glob pattern)", "root": "string (default: '.')"},
                "token_cost": "~50-100 tokens",
                "use_when": "Locating files by name, finding config files, finding test files",
                "tradeoff": "Slower than native fd/glob, but useful when combined with other MCP tools."
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
                "tradeoff": "May be large for complex classes. Consider using get_edit_context for structured view."
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
                "tradeoff": "Essential for impact analysis. Use before modifying critical functions."
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
                "token_cost": "~200-500 tokens",
                "use_when": "Before editing a function/class, understanding its context",
                "tradeoff": "Returns source, callers, callees, imports in one call. Very efficient for edit preparation."
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
                "tradeoff": "Most comprehensive impact view. Use for critical changes."
            },
            "get_defined_symbols": {
                "description": "Get all symbols defined in a file — functions, classes, methods, constants.",
                "params": {"file": "string (required)"},
                "token_cost": "~50-100 tokens",
                "use_when": "Quick file overview without reading the full file",
                "tradeoff": "Fast way to see what's in a file."
            }
        },
        "editing": {
            "preview_edit": {
                "description": "Stage a code edit and preview it as a unified diff WITHOUT writing to disk.",
                "params": {"file": "string", "old_code": "string", "new_code": "string"},
                "token_cost": "~100-200 tokens",
                "use_when": "Before applying any edit, to verify correctness",
                "tradeoff": "Always call before apply_edit. Returns edit_id."
            },
            "apply_edit": {
                "description": "Write a previewed edit to disk and automatically create a git commit.",
                "params": {"edit_id": "string (from preview_edit)"},
                "token_cost": "~50-100 tokens",
                "use_when": "After preview_edit confirms the change",
                "tradeoff": "Creates a git commit. Use undo_edit to revert if needed."
            },
            "preview_smart_edit": {
                "description": "Preview a smart block-based code edit as a unified diff WITHOUT writing to disk.",
                "params": {"file": "string", "new_code": "string"},
                "token_cost": "~100-200 tokens",
                "use_when": "Replacing entire blocks (functions, classes) with new code",
                "tradeoff": "Auto-detects which block to replace. More intelligent than preview_edit."
            },
            "apply_smart_edit": {
                "description": "Apply a smart edit preview to disk and create a git commit.",
                "params": {"edit_id": "string (from preview_smart_edit)"},
                "token_cost": "~50-100 tokens",
                "use_when": "After preview_smart_edit confirms the change",
                "tradeoff": "Creates a git commit. Use undo_edit to revert if needed."
            },
            "undo_edit": {
                "description": "Revert the last applied edit by running git revert HEAD.",
                "params": {},
                "token_cost": "~50-100 tokens",
                "use_when": "When an edit breaks things or is wrong",
                "tradeoff": "Creates a new revert commit. Does not delete history."
            }
        },
        "sandbox": {
            "setup_sandbox": {
                "description": "Detect the project stack and start a Docker sandbox container with deps installed.",
                "params": {},
                "token_cost": "~100-200 tokens",
                "use_when": "Before running check_syntax, compile_project, or run_tests",
                "tradeoff": "Idempotent. Safe to call multiple times."
            },
            "sandbox_status": {
                "description": "Return Docker availability and detected stack for the current repo.",
                "params": {},
                "token_cost": "~50-100 tokens",
                "use_when": "Checking if sandbox is ready before other sandbox operations",
                "tradeoff": "Quick check of Docker and stack detection."
            },
            "check_syntax": {
                "description": "Lint a single file inside the Docker sandbox using the stack's native linter.",
                "params": {"file": "string (required, relative path)"},
                "token_cost": "~100-300 tokens",
                "use_when": "Linting a file, finding syntax errors",
                "tradeoff": "Returns structured errors only — never raw linter output."
            },
            "compile_project": {
                "description": "Compile the entire project inside the Docker sandbox.",
                "params": {},
                "token_cost": "~100-300 tokens",
                "use_when": "Full project compilation check",
                "tradeoff": "Returns structured errors with file, line, column, and message."
            },
            "run_tests": {
                "description": "Run the project's test suite inside the Docker sandbox.",
                "params": {"test_path": "string (optional, relative path to specific test file or dir)"},
                "token_cost": "~150-400 tokens",
                "use_when": "Running tests, checking test results",
                "tradeoff": "Returns structured summary: total, passed, failed, and failure details."
            },
            "install_deps": {
                "description": "Reinstall all dependencies (system packages + project deps) inside the Docker sandbox.",
                "params": {},
                "token_cost": "~100-200 tokens",
                "use_when": "When deps are stale or container was rebuilt",
                "tradeoff": "Call setup_sandbox() first if not already done."
            },
            "stop_sandbox": {
                "description": "Stop and remove a specific sandbox container.",
                "params": {"stack": "string (required, python|node|java-maven|java-gradle|go|rust|ruby|php|cpp)"},
                "token_cost": "~50-100 tokens",
                "use_when": "Cleaning up sandbox containers",
                "tradeoff": "Permanently removes the container."
            }
        }
    },
    "workflow": {
        "recommended": [
            "1. Use get_index or search_symbol to locate symbols",
            "2. Use get_edit_context to understand the symbol before editing",
            "3. Use preview_edit or preview_smart_edit to stage changes",
            "4. Use apply_edit or apply_smart_edit to commit",
            "5. Use undo_edit if the change breaks things"
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
            "cheap": ["get_defined_symbols (~50-80)", "get_signature (~30-80)", "find_file (~50-100)", "get_imports (~50-100)", "extract_function (~50-150)", "count_references (~100-300)", "search_symbol (~100-300)"],
            "moderate": ["search_code (~300-500)", "get_edit_context (~200-500)", "get_callers (~200-500)", "get_callees (~200-500)", "get_body (~200-500)", "get_importers (~200-500)", "get_file_deps (~300-600)", "get_index (~200-500)", "get_overview (~200-500)"],
            "expensive": ["trace_execution (~500-1000)", "impact_analysis (~500-1000)", "extract_class (~100-300 for small, 500+ for large)"]
        }
    }
}


@mcp.tool()
async def get_tools_docs() -> dict:
    """
    Get comprehensive documentation about all MCP tools, their capabilities, and tradeoffs.
    Call this to understand what tools are available, when to use them, and their token costs.
    
    Returns:
        Complete tool documentation including:
        - All available tools grouped by category
        - Token costs for each tool
        - When to use each tool
        - Tradeoffs and recommendations
        - Recommended workflows
        - Token optimization tips
    """
    log.info("[get_tools_docs] Returning tools documentation")
    return TOOLS_DOCS


# ── Embedding Tools ────────────────────────────────────────────────────────

@mcp.tool()
async def embedding_status() -> dict:
    """
    Get current embedding status.
    Shows if embeddings are enabled, progress, and model info.
    
    Returns:
        Status including enabled, loading, progress, model name, dimensions
    """
    return await _get("/search/embedding-status")


@mcp.tool()
async def toggle_embeddings(enabled: bool) -> dict:
    """
    Enable or disable embedding generation.
    When enabled, starts generating embeddings in background.
    When disabled, stops embedding.
    
    Args:
        enabled: True to start embedding, False to stop
    
    Returns:
        Status of the toggle
    """
    return await _post("/search/embedding-toggle", {"enabled": enabled})


@mcp.tool()
async def semantic_search(query: str, limit: int = 10) -> dict:
    """
    Find code by natural language description using embeddings.
    Requires embeddings to be enabled and generated first.
    
    Args:
        query: Natural language description (e.g. "handle user login")
        limit: Max results (default: 10)
    
    Token cost: ~200-500 tokens
    """
    return await _get("/search/semantic", q=query, limit=limit)


@mcp.tool()
async def find_similar_functions(symbol_name: str, file: str | None = None, limit: int = 5) -> dict:
    """
    Find functions with similar behavior by embedding distance.
    Requires embeddings to be enabled and generated first.
    
    Args:
        symbol_name: Name of the function to find similar ones for
        file: Optional file path filter
        limit: Max results (default: 5)
    
    Token cost: ~150-300 tokens
    """
    return await _get("/search/similar", symbol=symbol_name, file=file, limit=limit)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("MCP Server ready, running stdio transport...")
    for handler in logging.getLogger().handlers:
        handler.flush()
    try:
        # Set asyncio event loop exception handler
        loop = asyncio.get_event_loop()
        def handle_async_exception(loop, context):
            msg = context.get("exception", context.get("message"))
            log.error("Unhandled exception in asyncio loop: %s", msg, exc_info=context.get("exception"))
            for handler in logging.getLogger().handlers:
                handler.flush()
        loop.set_exception_handler(handle_async_exception)
    except Exception as e:
        log.warning("Could not set asyncio loop exception handler: %s", e)

    try:
        mcp.run(transport="stdio")
    except Exception as e:
        log.critical("MCP Server crashed during execution", exc_info=True)
        for handler in logging.getLogger().handlers:
            handler.flush()
        sys.exit(1)

