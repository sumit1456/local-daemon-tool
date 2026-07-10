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
    async with httpx.AsyncClient(base_url=DAEMON_BASE, timeout=TIMEOUT) as client:
        r = await client.get(endpoint, params=filtered)
        log.debug("GET %s -> %s (%dms)", endpoint, r.status_code, r.elapsed.total_seconds() * 1000)
        r.raise_for_status()
        return r.json()


async def _post(endpoint: str, body: dict) -> dict:
    """Make a POST request to the local daemon."""
    log.debug("POST %s %s", endpoint, {k: v[:80] if isinstance(v, str) and len(v) > 80 else v for k, v in body.items()})
    async with httpx.AsyncClient(base_url=DAEMON_BASE, timeout=TIMEOUT) as client:
        r = await client.post(endpoint, json=body)
        log.debug("POST %s -> %s (%dms)", endpoint, r.status_code, r.elapsed.total_seconds() * 1000)
        r.raise_for_status()
        return r.json()


async def _delete(endpoint: str, params: dict | None = None) -> dict:
    """Make a DELETE request to the local daemon."""
    log.debug("DELETE %s %s", endpoint, params or {})
    async with httpx.AsyncClient(base_url=DAEMON_BASE, timeout=TIMEOUT) as client:
        r = await client.delete(endpoint, params=params or {})
        log.debug("DELETE %s -> %s (%dms)", endpoint, r.status_code, r.elapsed.total_seconds() * 1000)
        r.raise_for_status()
        return r.json()


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
async def scan_codebase(
    rulebook_path: str | None = None,
    rules: list[dict] | None = None,
    output_file: str | None = None,
    list_rulebooks: bool = False,
    exclude_dirs: list[str] | None = None,
) -> dict:
    """
    Scan the currently mounted codebase for bugs using Semgrep.

    Always runs asynchronously — returns immediately with the output file path.
    Results are written as JSON to .code-scan/scan_TIMESTAMP.json inside the repo
    (auto-created when output_file is not specified).

    To read results: use read_file on the returned output_file path.

    ── Semgrep Registry Configs (recommended, require internet) ──
      - "auto"               Auto-detect language, apply best community rules
      - "p/java"             Java security + quality pack
      - "p/python"           Python pack
      - "p/owasp-top-ten"    OWASP Top 10 security rules
      - "p/r2c-security-audit" Broad security audit
      - "p/secrets"          Hardcoded secrets detection
      - "p/default"          Semgrep default recommended rules

    ── Local YAML Rulebooks (offline, no account needed) ──
      - "codeengine/rulebook/java/java-semgrep.yaml"
      - "codeengine/rulebook/python/python-semgrep.yaml"

    If no rulebook_path is given, the first local YAML under codeengine/rulebook/ is used.

    Args:
        rulebook_path: Registry config string (e.g. 'auto', 'p/java') OR
                       absolute/repo-relative path to a local YAML rulebook.
        output_file:   Where to write JSON results. Auto-created if omitted.
        list_rulebooks: If True, lists available local rulebooks without scanning.
        exclude_dirs:  Extra directory names to exclude from the scan.
                       Merged with a built-in default list (node_modules, .venv, __pycache__, etc.).
    """
    if list_rulebooks:
        repo_path = os.getenv("REPO_PATH", ".")
        rulebook_dir = Path(repo_path) / "codeengine" / "rulebook"
        if not rulebook_dir.is_dir():
            rulebook_dir = Path(__file__).parent / "codeengine" / "rulebook"
        
        available = {}
        if rulebook_dir.is_dir():
            for lang_dir in sorted(rulebook_dir.iterdir()):
                if lang_dir.is_dir():
                    files = [f.name for f in lang_dir.iterdir() if f.suffix in (".json", ".yaml", ".yml")]
                    if files:
                        available[lang_dir.name] = {
                            "path": str(lang_dir.relative_to(rulebook_dir.parent)),
                            "semgrep": [f for f in files if f.endswith((".yaml", ".yml"))],
                            "legacy_json": [f for f in files if f.endswith(".json")],
                        }
        
        return {
            "rulebook_dir": str(rulebook_dir),
            "languages": available,
            "usage": "Pass rulebook_path as 'codeengine/rulebook/<lang>/<file>.yaml' for Semgrep (recommended) or '.json' for legacy.",
            "recommended": "Use Semgrep YAML rulebooks for AST-aware scanning with fewer false positives."
        }
    
    log.info("[scan_codebase] Starting codebase scan...")
    body: dict = {}
    if rulebook_path:
        body["rulebook_path"] = rulebook_path
    if rules:
        body["rules"] = rules
    if output_file:
        body["output_file"] = output_file
    if exclude_dirs:
        body["exclude_dirs"] = exclude_dirs
    # If no output_file, backend auto-creates REPO_PATH/.code-scan/scan_TIMESTAMP.json

    result = await _post("/scan", body)
    # Always returns {"status": "running", "output_file": "<abs_path>"}
    return result


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
async def index_repo(repo_path: str) -> dict:
    """
    Index a repository folder by clearing the previous index and scanning all files.

    Args:
        repo_path: Absolute path to the repository directory to index.
    """
    return await reindex(repo_path)


@mcp.tool()
async def grep_code(
    query: str,
    path: str = ".",
    lang: str | None = None,
    limit: int = 50,
    context_lines: int = 0,
    exclude_dirs: list[str] | None = None,
    regex: bool = False,
) -> dict:
    """
    Search source code using ripgrep. Returns matching lines with file, line number, and snippet.

    Use this tool when you need ripgrep-specific filtering (language, path scoping, etc.).

    Args:
        query: Search pattern or text to find.
        path: Root directory to search in (default: currently indexed repo).
        lang: Language filter — python | javascript | typescript | java | go | rust.
        limit: Maximum number of results to return (default: 50).
        context_lines: Lines of context to include before/after each match (default: 0).
        exclude_dirs: Extra directory names to exclude (e.g. ["tests", "migrations"]).
                      Default exclusions (.venv, node_modules, __pycache__, etc.) always apply.
        regex: If True, query is treated as a ripgrep regex pattern (., *, +, \\b, alternation,
              character classes, etc). If False (default), query is matched literally.
    """
    if path == ".":
        path = await _get_repo_path()
    data = await _get("/search/grep-code", q=query, path=path, lang=lang, limit=limit, context_lines=context_lines, exclude_dirs=exclude_dirs, regex=regex)
    return {
        "query": data["query"],
        "total": data["total"],
        "matches": [
            {
                "file": m["file"],
                "line": m["line"],
                "col":  m["col"],
                "text": m["text"].strip(),
                "context_before": m.get("context_before", []),
                "context_after":  m.get("context_after", []),
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
    Returns compact format: "name:kind:file:line_start-line_end"
    Agent can call extract_function(file, name) directly on results.

    Args:
        name: Symbol name to find (partial matches supported).
        kind: Optional filter — function | class | method | interface.
    """
    return await _get("/search/symbol", name=name, kind=kind)


# @mcp.tool()
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


# @mcp.tool()
async def extract_by_name(
    name: str,
    kind: str | None = None,
    extract: str = "body",
) -> dict:
    """
    Search for a function/class by name and extract its code in one call.
    No need to know file path or line numbers — just provide the name.

    Args:
        name: Function or class name to search for (partial matches supported).
        kind: Optional filter — function | class | method | interface.
        extract: What to extract — "signature" (just sig+docstring), "body" (full code), or "both".
    """
    return await _get("/search/extract-by-name", name=name, kind=kind, extract=extract)


@mcp.tool()
async def undo_edit() -> dict:
    """
    Revert the last applied edit by running `git revert HEAD`.
    Use this immediately if a test fails after applying an edit.
    """
    return await _post("/undo", {})


# @mcp.tool()
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
    return await _get("/search/overview", files=files, dir=dir, package=package, q=q, limit=limit, offset=offset)


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


# @mcp.tool()
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


# @mcp.tool()
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


# @mcp.tool()
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
    old_code: str,
    new_code: str,
    mode: str = "fuzzy",
) -> dict:
    """
    Preview a smart code edit as a unified diff WITHOUT writing to disk.
    Uses fuzzy string matching to find the old_code in the file, then shows
    the diff with new_code applied.

    Args:
        file: Relative path to the file to edit.
        old_code: The exact text to find and replace (fuzzy matching supported).
        new_code: The replacement text.
        mode: "fuzzy" (default, opencode-style string matching) or
               "ast" (tree-sitter block parsing with class-aware matching).
    """
    return await _post("/preview-smart-edit", {
        "file":     file,
        "old_code": old_code,
        "new_code": new_code,
        "mode":     mode,
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


# @mcp.tool()
async def get_type_info(symbol_name: str, file: str | None = None) -> dict:
    """
    Return parameter types and return type for a symbol.
    Prevents API misuse by showing type signatures.

    Args:
        symbol_name: Name of the function/class to get type info for.
        file: Optional file path filter to narrow results.
    """
    return await _get("/search/type-info", symbol_name=symbol_name, file=file)


# @mcp.tool()
async def get_defined_symbols(file: str) -> dict:
    """
    Get all symbols defined in a file — functions, classes, methods, constants.
    Quick file overview without reading the full file.

    Args:
        file: Relative path to the file (e.g. "codeengine/core/search.py").
    """
    return await _get("/search/defined-symbols", file=file)


# @mcp.tool()
async def count_references(symbol_name: str) -> dict:
    """
    Count how many times a symbol is referenced across the codebase.
    Great for risk assessment before making changes.

    Args:
        symbol_name: Name of the symbol to count references for.
    """
    return await _get("/search/count-references", symbol_name=symbol_name)


# @mcp.tool()
async def impact_analysis(symbol_name: str) -> dict:
    """
    Full impact assessment before changing a symbol.
    Shows direct callers, all references, and affected files.

    Args:
        symbol_name: Name of the symbol to analyze impact for.
    """
    return await _get("/search/impact-analysis", symbol_name=symbol_name)


# @mcp.tool()
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

# @mcp.tool()
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


# @mcp.tool()
async def get_docstring(symbol_name: str, file: str | None = None) -> dict:
    """
    Retrieve docstrings for a symbol, optionally filtered by file.

    Args:
        symbol_name: Symbol name to get docstring for.
        file: Optional file path filter to narrow results.
    """
    return await _get("/search/docstring", symbol_name=symbol_name, file=file)


# @mcp.tool()
async def sandbox_status() -> dict:
    """
    Return Docker availability and detected stack for the current repo.
    Useful to check if sandbox is ready before running check_syntax, compile_project, or run_tests.
    """
    return await _get("/sandbox/status")


# @mcp.tool()
async def stop_sandbox(stack: str) -> dict:
    """
    Stop and remove a specific sandbox container.

    Args:
        stack: Stack to stop — python | node | java-maven | java-gradle | go | rust | ruby | php | cpp.
    """
    return await _delete("/sandbox/stop", params={"stack": stack})


# @mcp.tool()
async def list_workspace() -> dict:
    """
    List subdirectories inside /workspace that look like repos.
    Useful for discovering available repositories to index.
    """
    return await _get("/workspace/list")


# ── New Feature Tools ────────────────────────────────────────────────────────

# @mcp.tool()
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


# @mcp.tool()
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


# @mcp.tool()
# async def get_function_history(symbol_name: str, limit: int = 20) -> dict:
#     """
#     Return the precomputed git commit history for a specific function or class.
#     Each entry is a compact record: commit hash, date, message, and change type
#     (signature_change | logic_edit | new | deleted).
#
#     Use this INSTEAD of running raw git log commands, which burn 10,000+ tokens.
#     This returns a 150-token summary of the function's full change history.
#
#     Args:
#         symbol_name: The exact function or class name.
#         limit: Maximum number of commits to return (default 20).
#     """
#     log.info("[get_function_history] symbol=%s limit=%d", symbol_name, limit)
#     return await _get("/search/function-history", symbol=symbol_name, limit=limit)


# @mcp.tool()
# async def index_git_history() -> dict:
#     """
#     Trigger indexing of the git commit history for the current repository.
#     Must be called once after /reindex before get_function_history works.
#     Processes the last 200 commits. Run in the background (takes ~5-30 seconds).
#     """
#     log.info("[index_git_history] Triggering git history indexing")
#     return await _post("/git-index", {})


# @mcp.tool()
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


# @mcp.tool()
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


# @mcp.tool()
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


# @mcp.tool()
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


# @mcp.tool()
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


# @mcp.tool()
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
            "search_symbol": {
                "description": "Search AST symbol index for functions, classes, methods by name. Returns compact format: name:kind:file:line_start-line_end. Agent can call extract_function directly on results.",
                "params": {"name": "string (required)", "kind": "function|class|method|interface"},
                "token_cost": "~50-100 tokens",
                "use_when": "Finding exact symbol definitions, locating where a function/class is defined",
                "tradeoff": "AST-aware (kind + line ranges). Requires indexed repo."
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
            }
        },
        "call_graph": {
            "get_callers": {
                "description": "Find all functions that call the given symbol.",
                "params": {"symbol_name": "string (required)"},
                "token_cost": "~200-500 tokens",
                "use_when": "Understanding who depends on a function, blast radius analysis",
                "tradeoff": "Essential for impact analysis. Use before modifying critical functions."
            },
            "get_callees": {
                "description": "Find all functions called by the given symbol.",
                "params": {"symbol_name": "string (required)"},
                "token_cost": "~200-500 tokens",
                "use_when": "Understanding function dependencies, what a function relies on",
                "tradeoff": "Use with get_callers for full call graph picture."
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
            "undo_edit": {
                "description": "Revert the last applied edit by running git revert HEAD.",
                "params": {},
                "token_cost": "~30-50 tokens",
                "use_when": "Immediately after apply_smart_edit if a test fails or change is wrong",
                "tradeoff": "Creates a new revert commit."
            }
        },
        "scan": {
            "scan_codebase": {
                "description": "Scan the codebase for bug patterns using Semgrep (AST-aware) or legacy REGEX/SQL rules.",
                "params": {
                    "rulebook_path": "string (optional) — Semgrep config. Accepts: (1) Registry configs: 'auto', 'p/java', 'p/python', 'p/owasp-top-ten', 'p/r2c-security-audit', 'p/secrets', 'p/default'; (2) Local YAML rulebooks: 'codeengine/rulebook/java/java-semgrep.yaml', 'codeengine/rulebook/python/python-semgrep.yaml'; (3) Auto-discover: omit to use first YAML under codeengine/rulebook/",
                    "rules": "list of dicts (optional) — inline JSON rule definitions (legacy REGEX mode).",
                    "output_file": "string (optional) — path to write results asynchronously",
                    "list_rulebooks": "bool (optional) — set true to list available rulebooks without scanning"
                },
                "token_cost": "~200-500 tokens",
                "use_when": "Code review, bug pattern detection, security scanning, pre-commit checks",
                "tradeoff": "Semgrep: AST-aware, accurate. Legacy REGEX: fast, less accurate."
            }
        },
        "filesystem": {
            "build_tree": {
                "description": "Build a visual directory tree for a given root path. Returns a tree-formatted string showing folder/file structure.",
                "params": {"root": "string (required) — directory path to tree", "ignore": "list of strings (optional) — directory names to skip (default: .git, node_modules, __pycache__, .venv, target, dist)"},
                "token_cost": "~100-500 tokens",
                "use_when": "Understanding project layout, discovering directory structure, exploring unfamiliar repos",
                "tradeoff": "Local tool, no daemon needed. Skips common large dirs by default."
            },
            "write_file": {
                "description": "Write content to a file. Creates parent directories if needed. Overwrites existing files entirely.",
                "params": {"path": "string (required) — file path", "content": "string (required) — content to write"},
                "token_cost": "~50-100 tokens",
                "use_when": "Creating new files, replacing file contents, scaffolding",
                "tradeoff": "Local tool, no daemon needed. Overwrites without warning."
            }
        },
        "file_ops": {
            "read_file": {
                "description": "Read content of a file, selecting lines by range, explicit line numbers, or pattern match.",
                "params": {
                    "file": "string (required)",
                    "start_line": "int (optional) — used with end_line for a range",
                    "end_line": "int (optional, inclusive)",
                    "lines": "list of ints (optional) — read specific non-contiguous lines",
                    "pattern": "string (optional) — search for a pattern instead of specifying lines",
                    "context_lines": "int (optional, default 0) — lines of context around each pattern match"
                },
                "token_cost": "~50-300 tokens",
                "use_when": "Reading a file — full, ranged, scattered lines, or pattern-matched.",
                "tradeoff": "Provide only the params relevant to your selection mode: (start_line+end_line) for range, (lines) for scattered, (pattern) for search. Omit all three to read the whole file."
            }
        },
        "semantic": {
            "semantic_search": {
                "description": "Find code by natural language description using embeddings.",
                "params": {"query": "string (required)", "limit": "int (default: 10)"},
                "token_cost": "~200-500 tokens",
                "use_when": "Finding code by concept, not by exact name",
                "tradeoff": "Requires embeddings to be enabled and generated."
            }
        },
        "utility": {
            "find_unused": {
                "description": "Find unused code artifacts.",
                "params": {"scope": "string (required) — 'imports' | 'symbols' | 'calls'"},
                "token_cost": "~50-100 tokens",
                "use_when": "Code cleanup, finding dead code",
                "tradeoff": "Scope determines what to find: imports (unused), symbols (never called), calls (references to non-existent)."
            },
            "index_health": {
                "description": "Report index health and whether trust-sensitive tools are blocked.",
                "params": {},
                "token_cost": "~100-300 tokens",
                "use_when": "Debugging index issues",
                "tradeoff": "Diagnostic tool for troubleshooting."
            },
            "run_query": {
                "description": "Execute a raw SQL query against the codebase index database.",
                "params": {"query": "string (required)", "params": "list (optional)"},
                "token_cost": "~100-500 tokens",
                "use_when": "Advanced queries not covered by other tools",
                "tradeoff": "Powerful but requires SQL knowledge. Use other tools first."
            },
            "ping": {
                "description": "Check if the Code Search Engine daemon is running and healthy.",
                "params": {},
                "token_cost": "~30-50 tokens",
                "use_when": "Verifying daemon status before using other tools",
                "tradeoff": "Quick health check."
            }
        }
    },
    "workflow": {
        "recommended": [
            "0. Use build_tree to understand project layout",
            "1. Use search_symbol to locate symbols",
            "2. Use get_edit_context to understand the symbol before editing",
            "3. Use preview_smart_edit to stage block-based changes",
            "4. Use apply_smart_edit to commit",
            "5. Use undo_edit to revert if something goes wrong",
            "6. Use scan_codebase with list_rulebooks=true to see available rulebooks",
            "7. Use scan_codebase with rulebook_path to scan for bugs"
        ],
        "token_optimization": [
            "Use build_tree first to understand project layout before diving into files",
            "Use extract_function/extract_class instead of reading full files",
            "Use get_edit_context for structured context (callers, callees, imports)",
            "Batch parallel tool calls when possible",
            "Use scan_codebase with list_rulebooks=true first to discover available rulebooks"
        ]
    }
}


# @mcp.tool()
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

# @mcp.tool()
async def embedding_status() -> dict:
    """
    Get current embedding status.
    Shows if embeddings are enabled, progress, and model info.
    
    Returns:
        Status including enabled, loading, progress, model name, dimensions
    """
    return await _get("/search/embedding-status")


# @mcp.tool()
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


# @mcp.tool()
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


@mcp.tool()
async def find_unused(scope: str) -> dict:
    """
    Find unused code artifacts.

    Args:
        scope: "imports" | "symbols" | "calls"
            - imports: imported but never used
            - symbols: defined functions/methods never called
            - calls: call references to non-existent symbols

    Token cost: ~50-100 tokens
    """
    return await _get("/search/unused", scope=scope)


@mcp.tool()
async def index_health() -> dict:
    """
    Report index health and whether trust-sensitive tools such as find_unused are blocked.

    Token cost: ~100-300 tokens
    """
    return await _get("/search/doctor")


@mcp.tool()
async def run_query(query: str, params: list = []) -> dict:
    """
    Execute a raw SQL query against the codebase index database.

    Args:
        query: SQL query to execute (e.g. "SELECT * FROM symbols LIMIT 10")
        params: Optional list of parameterized query values

    Token cost: ~100-500 tokens
    """
    return await _post("/search/query", {"query": query, "params": params})


# ── File Reading Tools ────────────────────────────────────────────────────────

@mcp.tool()
async def read_file(
    file: str,
    start_line: int | None = None,
    end_line: int | None = None,
    lines: list[int] | None = None,
    pattern: str | None = None,
    context_lines: int = 0,
) -> dict:
    """
    Read content of a file, selecting lines by range, explicit line numbers, or pattern match.

    Args:
        file: Relative path to the file (e.g. "codeengine/app.py").
        start_line: Start line number (1-indexed). Use with end_line for a range.
        end_line: End line number (inclusive). Use with start_line for a range.
        lines: List of specific line numbers to read (1-indexed). For non-contiguous lines.
        pattern: Regex pattern to search for instead of specifying lines.
        context_lines: Lines of context around each pattern match (default: 0).

    Modes (provide only one):
        - Whole file: omit all optional params
        - Range: provide start_line + end_line
        - Scattered lines: provide lines list
        - Pattern search: provide pattern (+ optional context_lines)

    Returns:
        dict with keys: file, total_lines, mode, content/lines/matches
    """
    if pattern:
        return await _get("/search/grep-file", file=file, pattern=pattern, context=context_lines)
    elif lines:
        return await _post("/search/read-lines", {"file": file, "lines": lines})
    else:
        params = {"file": file}
        if start_line is not None:
            params["start_line"] = start_line
        if end_line is not None:
            params["end_line"] = end_line
        return await _get("/search/file-read", **params)


# ── Filesystem Tools ────────────────────────────────────────────────────────

@mcp.tool()
async def build_tree(
    root: str,
    ignore: list[str] | None = None,
    include_deps: bool = False,
) -> dict:
    """
    Build a visual directory tree for a given root path.
    Returns a tree-formatted string showing the folder/file structure.

    Args:
        root: Absolute or relative path to the directory to tree.
        ignore: Optional list of directory names to skip
                (default: .git, node_modules, __pycache__, .venv, target, dist).
        include_deps: If True, include dependency folders (node_modules, .venv, etc.).
                      Only .git is always excluded.
    """
    _deps_dirs = {"node_modules", "__pycache__", ".venv", "target", "dist", ".tox", "venv", "env", ".env", "build", "out"}
    _always_ignore = {".git"}
    if include_deps:
        skip = _always_ignore
    elif ignore:
        skip = set(ignore)
    else:
        skip = _deps_dirs | _always_ignore

    def _is_skipped(name: str) -> bool:
        return any(
            name == s or name.startswith(s + "-") or name.startswith(s + "_")
            for s in skip
        )

    def walk(dir_path: Path):
        entries = sorted(
            [p for p in dir_path.iterdir() if not _is_skipped(p.name)],
            key=lambda p: (p.is_file(), p.name.lower()),
        )
        return entries

    def render(dir_path: Path, prefix: str = "") -> list[str]:
        lines: list[str] = []
        entries = walk(dir_path)
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            name = entry.name + "/" if entry.is_dir() else entry.name
            lines.append(prefix + connector + name)
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                lines.extend(render(entry, prefix + extension))
        return lines

    path = Path(root)
    if not path.is_dir():
        return {"error": f"Not a directory: {root}"}

    tree = path.name + "/\n" + "\n".join(render(path))
    return {"root": str(path), "tree": tree}


@mcp.tool()
async def write_file(path: str, content: str) -> dict:
    """
    Write content to a file. Creates parent directories if needed.
    Overwrites existing files entirely.

    Args:
        path: Absolute or relative path to the file to write.
        content: The full content to write to the file.
    """
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        log.info("[write_file] Wrote %d bytes to %s", len(content), path)
        return {"ok": True, "path": str(p), "bytes": len(content.encode("utf-8"))}
    except Exception as e:
        log.error("[write_file] Failed: %s", e)
        return {"ok": False, "error": str(e)}


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

