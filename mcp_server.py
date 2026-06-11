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

import asyncio
import sys
import logging
import httpx
from mcp.server.fastmcp import FastMCP
from pathlib import Path
from datetime import datetime

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "mcp_server.log"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("mcp_server")

DAEMON_BASE = "http://127.0.0.1:8000"
TIMEOUT = 30.0

log.info("=" * 60)
log.info("MCP Server starting — PID %s", __import__("os").getpid())
log.info("Log file: %s", LOG_FILE)
log.info("Daemon target: %s", DAEMON_BASE)
log.info("=" * 60)

mcp = FastMCP("CodeSearchEngine")


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
        path: Root directory to search in (default: project root).
        lang: Language filter — python | javascript | typescript | java | go | rust.
        limit: Maximum number of results to return (default: 50).
    """
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
        root: Root directory to search in (default: project root).
    """
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
    Get a full repository overview including the symbol call graph.
    Useful for understanding the architecture of a codebase before making changes.

    Args:
        files: Optional list of specific files to scope the overview to. Omit for the full repo.
        dir: Directory prefix filter (e.g. "src/core").
        package: Package path filter (e.g. "codeengine.core").
        q: Substring match on file path.
        limit: Max number of files to return (default: 50).
        offset: Number of files to skip for pagination (default: 0).
    """
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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("MCP Server ready, running stdio transport...")
    mcp.run(transport="stdio")

