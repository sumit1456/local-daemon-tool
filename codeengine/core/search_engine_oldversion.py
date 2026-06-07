# import os
# import shutil
# import json
# import asyncio
# import subprocess
# from pathlib import Path
# from codeengine.database.sqlite import get_db
# from codeengine.models.search_models import Match, Symbol

# RG_LANG_MAP = {
#     "python": "py", "py": "py",
#     "java": "java",
#     "javascript": "js", "js": "js",
#     "typescript": "ts", "ts": "ts",
#     "go": "go",
#     "rust": "rust"
# }

# def _get_binary_path(name: str) -> str:
#     """Resolve binary location, checking system PATH first, then WinGet Packages folders as fallback."""
#     binary = shutil.which(name)
#     if binary:
#         return binary

#     # WinGet AppData folder fallback (highly robust on Windows)
#     local_appdata = os.getenv("LOCALAPPDATA")
#     if local_appdata:
#         packages_dir = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
#         if packages_dir.is_dir():
#             pattern = "rg.exe" if name == "rg" else "fd.exe"
#             found_exes = list(packages_dir.rglob(pattern))
#             if found_exes:
#                 return str(found_exes[0])

#     return name

# def _run_subprocess(args: list[str]) -> bytes:
#     """Run a subprocess synchronously and return stdout bytes. Safe on Windows."""
#     try:
#         result = subprocess.run(
#             args,
#             stdout=subprocess.PIPE,
#             stderr=subprocess.PIPE,
#             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
#         )
#         return result.stdout
#     except FileNotFoundError:
#         return b""

# def _escape_regex(pattern: str) -> str:
#     metacharacters = r".^$*+?{}[]\|()"
#     escaped = ""
#     for char in pattern:
#         if char in metacharacters:
#             escaped += "\\" + char
#         else:
#             escaped += char
#     return escaped

# async def search_code(query: str, root: str, lang: str | None, limit: int) -> list[Match]:
#     """Search for query in code files using ripgrep subprocess."""
#     rg_path = _get_binary_path("rg")
#     # Add --multiline flag to enable multiline pattern matching
#     args = [rg_path, "--json", f"--max-count={limit}", "--multiline"]

#     if lang:
#         rg_type = RG_LANG_MAP.get(lang.lower())
#         if rg_type:
#             args.extend(["--type", rg_type])

#     # Escape regex metacharacters for literal matching and normalize line endings
#     escaped_query = _escape_regex(query)
#     normalized_query = escaped_query.replace("\r\n", "\n").replace("\n", "\r?\n")
#     args.extend(["-e", normalized_query, root])

#     # Use asyncio.to_thread so the blocking subprocess.run doesn't block the event loop
#     stdout = await asyncio.to_thread(_run_subprocess, args)

#     matches = []
#     for line in stdout.decode(errors="replace").splitlines():
#         if not line.strip():
#             continue
#         try:
#             obj = json.loads(line)
#             if obj.get("type") == "match":
#                 data = obj["data"]
#                 file_path = data["path"]["text"]
#                 line_num = data["line_number"]
#                 submatches = data["submatches"]
#                 col = submatches[0]["start"] if submatches else 0
#                 # Preserve leading indentation of the match block, only strip trailing newlines/spaces
#                 text = data["lines"]["text"].rstrip()
#                 matches.append(Match(file=file_path, line=line_num, col=col, text=text))
#         except (json.JSONDecodeError, KeyError, IndexError):
#             continue

#     return matches

# async def search_symbol(name: str, kind: str | None) -> list[Symbol]:
#     """Search for symbols stored in SQLite by name match and optional kind filter."""
#     query_str = (
#         "SELECT s.name, s.kind, f.path as file, s.line_start, s.line_end "
#         "FROM symbols s "
#         "JOIN files f ON s.file_id = f.id "
#         "WHERE s.name LIKE ?"
#     )
#     params = [f"%{name}%"]

#     if kind:
#         query_str += " AND s.kind = ?"
#         params.append(kind)

#     symbols = []
#     async with get_db() as db:
#         async with db.execute(query_str, params) as cursor:
#             rows = await cursor.fetchall()
#             for r in rows:
#                 symbols.append(Symbol(
#                     name=r["name"],
#                     kind=r["kind"],
#                     file=r["file"],
#                     line_start=r["line_start"],
#                     line_end=r["line_end"]
#                 ))
#     return symbols

# async def find_file(pattern: str, root: str) -> list[str]:
#     """Find files matching the pattern in the root directory using fd."""
#     fd_path = _get_binary_path("fd")
#     args = [fd_path, "--type", "f"]
#     if pattern:
#         args.append(pattern)
#     args.append(root)

#     stdout = await asyncio.to_thread(_run_subprocess, args)

#     files = []
#     for line in stdout.decode(errors="replace").splitlines():
#         if line.strip():
#             files.append(line.strip())
#     return files



import os
import re
import shutil
import json
import asyncio
import logging
import subprocess
from pathlib import Path
from dataclasses import dataclass
from codeengine.database.sqlite import get_db
from codeengine.models.search_models import Match, Symbol


@dataclass
class FunctionContext:
    file: str
    line_start: int
    line_end: int
    # Always present — just the def/signature line(s) + docstring
    signature: str
    # Only populated when include_body=True was requested
    body: str | None = None

logger = logging.getLogger(__name__)

RG_LANG_MAP = {
    "python": "py", "py": "py",
    "java": "java",
    "javascript": "js", "js": "js",
    "typescript": "ts", "ts": "ts",
    "go": "go",
    "rust": "rust",
}

SUBPROCESS_TIMEOUT = 30  # seconds


def _get_binary_path(name: str) -> str:
    """Resolve binary location, checking system PATH first, then WinGet Packages folders as fallback."""
    binary = shutil.which(name)
    if binary:
        return binary

    # WinGet AppData folder fallback (highly robust on Windows)
    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        packages_dir = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
        if packages_dir.is_dir():
            pattern = "rg.exe" if name == "rg" else "fd.exe"
            found_exes = list(packages_dir.rglob(pattern))
            if found_exes:
                return str(found_exes[0])

    return name


def _run_subprocess(args: list[str]) -> bytes:
    """
    Run a subprocess synchronously and return stdout bytes.
    Returns b"" and logs a warning if the binary is not found or times out.
    """
    # FIX #6: Safely build creationflags only on Windows to avoid
    # referencing the Windows-only constant on other platforms.
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        # FIX #7: Added timeout so a runaway rg/fd process doesn't block forever.
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=SUBPROCESS_TIMEOUT,
            **kwargs,
        )
        return result.stdout
    except FileNotFoundError:
        # FIX #2: Log clearly instead of silently swallowing the error.
        logger.warning("Binary not found: %s. Is it installed and on PATH?", args[0])
        return b""
    except subprocess.TimeoutExpired:
        logger.warning("Subprocess timed out after %ds: %s", SUBPROCESS_TIMEOUT, args[0])
        return b""


def _escape_regex(pattern: str) -> str:
    # FIX #1: Use re.escape instead of a hand-rolled, incomplete implementation.
    return re.escape(pattern)


async def search_code(query: str, root: str, lang: str | None, limit: int) -> list[Match]:
    """Search for query in code files using ripgrep subprocess."""
    if not query.strip():
        return []

    # FIX #8: Warn on unrecognised languages so callers know the filter was ignored.
    if lang:
        rg_type = RG_LANG_MAP.get(lang.lower())
        if rg_type is None:
            logger.warning(
                "Language %r is not in RG_LANG_MAP; language filter will be ignored.", lang
            )
    else:
        rg_type = None

    rg_path = _get_binary_path("rg")

    # NOTE: --max-count limits per file, not globally (see post-processing trim below).
    args = [rg_path, "--json", f"--max-count={limit}", "--multiline"]

    if rg_type:
        args.extend(["--type", rg_type])

    escaped_query = _escape_regex(query)
    normalized_query = escaped_query.replace("\r\n", "\n").replace("\n", r"\r?\n")
    args.extend(["-e", normalized_query, root])

    stdout = await asyncio.to_thread(_run_subprocess, args)

    # FIX #2: Distinguish "binary missing" from "no results".
    if not stdout:
        return []

    matches: list[Match] = []
    for line in stdout.decode(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") == "match":
                data = obj["data"]
                file_path = data["path"]["text"]
                line_num = data["line_number"]
                submatches = data["submatches"]
                col = submatches[0]["start"] if submatches else 0
                text = data["lines"]["text"].rstrip()
                matches.append(Match(file=file_path, line=line_num, col=col, text=text))
        except (json.JSONDecodeError, KeyError, IndexError):
            continue

    # FIX #3: --max-count is per-file in ripgrep, so enforce the true global limit here.
    return matches[:limit]


async def search_symbol(name: str, kind: str | None, limit: int = 100) -> list[Symbol]:
    """Search for symbols stored in SQLite by name match and optional kind filter."""
    # FIX #5: Guard against empty/very-short names causing expensive full-table scans.
    if not name or len(name.strip()) < 2:
        raise ValueError("Symbol name must be at least 2 characters to avoid full-table scans.")

    query_str = (
        "SELECT s.name, s.kind, f.path as file, s.line_start, s.line_end "
        "FROM symbols s "
        "JOIN files f ON s.file_id = f.id "
        "WHERE s.name LIKE ?"
    )
    params: list = [f"%{name}%"]

    if kind:
        query_str += " AND s.kind = ?"
        params.append(kind)

    query_str += " LIMIT ?"
    params.append(limit)

    symbols: list[Symbol] = []
    async with get_db() as db:
        async with db.execute(query_str, params) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                symbols.append(Symbol(
                    name=r["name"],
                    kind=r["kind"],
                    file=r["file"],
                    line_start=r["line_start"],
                    line_end=r["line_end"],
                ))
    return symbols


async def find_file(pattern: str, root: str) -> list[str]:
    """
    Find files matching the pattern in the root directory using fd.
    Raises ValueError if pattern is empty to prevent accidental full-tree dumps.
    """
    # FIX #4: Explicitly reject empty patterns instead of silently listing everything.
    if not pattern or not pattern.strip():
        raise ValueError(
            "pattern must be a non-empty string. "
            "Pass '*' explicitly if you intentionally want all files."
        )

    fd_path = _get_binary_path("fd")
    args = [fd_path, "--type", "f", pattern, root]

    stdout = await asyncio.to_thread(_run_subprocess, args)

    files: list[str] = []
    for line in stdout.decode(errors="replace").splitlines():
        if line.strip():
            files.append(line.strip())
    return files


# ---------------------------------------------------------------------------
# Precision context helpers — avoids reading whole files into agent context
# ---------------------------------------------------------------------------

def _read_lines(file: str, line_start: int, line_end: int) -> list[str]:
    """
    Read exactly the lines [line_start, line_end] from a file (1-indexed, inclusive).
    Raises FileNotFoundError if the file doesn't exist.
    Raises ValueError if line range is invalid.
    """
    if line_start < 1:
        raise ValueError(f"line_start must be >= 1, got {line_start}")
    if line_end < line_start:
        raise ValueError(f"line_end ({line_end}) must be >= line_start ({line_start})")

    path = Path(file)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file}")

    # Read only up to line_end — no need to load the entire file into memory
    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for current_num, raw_line in enumerate(fh, start=1):
            if current_num < line_start:
                continue
            if current_num > line_end:
                break
            lines.append(raw_line.rstrip("\n"))
    return lines


def _extract_signature_and_docstring(lines: list[str]) -> str:
    """
    Given the lines of a function/method, return only the def line(s)
    plus the inline docstring (if present). Everything else is dropped.

    Handles:
    - Single-line def
    - Multi-line def (args span multiple lines, closed by ':')
    - Immediately following triple-quoted docstring
    """
    sig_lines: list[str] = []
    docstring_lines: list[str] = []
    in_def = False
    def_closed = False
    in_docstring = False
    docstring_quote: str = ""
    docstring_done = False

    for line in lines:
        stripped = line.strip()

        # --- Collect def signature (potentially multi-line) ---
        if not def_closed:
            if stripped.startswith("def ") or stripped.startswith("async def "):
                in_def = True
            if in_def:
                sig_lines.append(line)
                # def is closed once we hit the colon that ends the signature
                if stripped.endswith(":") or "):".endswith(stripped[-2:] if len(stripped) >= 2 else ""):
                    def_closed = True
                continue

        # --- Collect docstring immediately after def ---
        if def_closed and not docstring_done:
            if not in_docstring:
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    docstring_quote = stripped[:3]
                    in_docstring = True
                    docstring_lines.append(line)
                    # Single-line docstring: opens and closes on same line
                    rest = stripped[3:]
                    if rest.endswith(docstring_quote) and len(rest) >= 3:
                        docstring_done = True
                        in_docstring = False
                    continue
                elif stripped == "":
                    # Allow one blank line between def and docstring
                    continue
                else:
                    # No docstring — body starts immediately
                    docstring_done = True
            else:
                docstring_lines.append(line)
                if stripped.endswith(docstring_quote) and stripped != docstring_quote:
                    docstring_done = True
                    in_docstring = False
                continue

        # Stop once we have sig + docstring
        if def_closed and docstring_done:
            break

    result = "\n".join(sig_lines)
    if docstring_lines:
        result += "\n" + "\n".join(docstring_lines)
    return result


async def get_function_signature(file: str, line_start: int, line_end: int) -> FunctionContext:
    """
    Return only the function signature + docstring for a symbol.

    Token cost: ~5-15 tokens regardless of function size.
    Use this first so the agent can decide whether it needs the full body.

    Args:
        file:       Absolute or relative path to the source file.
        line_start: First line of the function (from symbols table).
        line_end:   Last line of the function (from symbols table).

    Returns:
        FunctionContext with `signature` populated and `body=None`.
    """
    lines = await asyncio.to_thread(_read_lines, file, line_start, line_end)
    signature = _extract_signature_and_docstring(lines)
    return FunctionContext(
        file=file,
        line_start=line_start,
        line_end=line_end,
        signature=signature,
        body=None,
    )


async def get_function_body(file: str, line_start: int, line_end: int) -> FunctionContext:
    """
    Return the full function source — signature + complete body — with no
    surrounding file context (no imports above, no next function below).

    Token cost: exactly (line_end - line_start + 1) lines, nothing more.
    Call this only after get_function_signature confirms you need the implementation.

    Args:
        file:       Absolute or relative path to the source file.
        line_start: First line of the function (from symbols table).
        line_end:   Last line of the function (from symbols table).

    Returns:
        FunctionContext with both `signature` and `body` populated.
    """
    lines = await asyncio.to_thread(_read_lines, file, line_start, line_end)
    full_source = "\n".join(lines)
    signature = _extract_signature_and_docstring(lines)
    return FunctionContext(
        file=file,
        line_start=line_start,
        line_end=line_end,
        signature=signature,
        body=full_source,
    )


# ---------------------------------------------------------------------------
# Repo / file index — cheapest possible context for agent orientation
# ---------------------------------------------------------------------------

from dataclasses import field


@dataclass
class SymbolEntry:
    """Minimal symbol descriptor — name, kind, and line boundaries only."""
    name: str
    kind: str
    line_start: int
    line_end: int


@dataclass
class FileIndex:
    """All symbols belonging to one file."""
    file: str
    symbols: list[SymbolEntry] = field(default_factory=list)


async def _query_index(file_filter: list[str] | None) -> list[FileIndex]:
    """
    Core DB query shared by all index functions.
    Pulls (file, name, kind, line_start, line_end) grouped by file.
    If file_filter is given, restricts to those exact paths.
    """
    if file_filter:
        placeholders = ", ".join("?" * len(file_filter))
        query_str = (
            "SELECT f.path, s.name, s.kind, s.line_start, s.line_end "
            "FROM symbols s "
            "JOIN files f ON s.file_id = f.id "
            f"WHERE f.path IN ({placeholders}) "
            "ORDER BY f.path, s.line_start"
        )
        params: list = file_filter
    else:
        query_str = (
            "SELECT f.path, s.name, s.kind, s.line_start, s.line_end "
            "FROM symbols s "
            "JOIN files f ON s.file_id = f.id "
            "ORDER BY f.path, s.line_start"
        )
        params = []

    index_map: dict[str, FileIndex] = {}
    async with get_db() as db:
        async with db.execute(query_str, params) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                path = r["path"]
                if path not in index_map:
                    index_map[path] = FileIndex(file=path)
                index_map[path].symbols.append(SymbolEntry(
                    name=r["name"],
                    kind=r["kind"],
                    line_start=r["line_start"],
                    line_end=r["line_end"],
                ))

    return list(index_map.values())


async def get_repo_index() -> list[FileIndex]:
    """
    Return every file in the repo with its symbol names, kinds, and line ranges.
    No file I/O — pure SQLite read.

    Token cost: ~5-10k for a medium repo (200 files, 1000 symbols).
    Use as the agent's very first call to orient itself before touching any file.

    Returns:
        [
          FileIndex(file="payment_service.py", symbols=[
            SymbolEntry(name="validate_card",  kind="function", line_start=10, line_end=28),
            SymbolEntry(name="charge_customer", kind="function", line_start=30, line_end=67),
          ]),
          ...
        ]
    """
    return await _query_index(file_filter=None)


async def get_file_index(files: list[str]) -> list[FileIndex]:
    """
    Return symbols for one or more specific files only.
    Use after get_repo_index narrows down which files are relevant.

    Args:
        files: One or more file paths exactly as stored in the DB,
               e.g. ["src/payment_service.py", "src/auth_service.py"]

    Token cost: ~50-200 tokens per file.
    """
    if not files:
        raise ValueError("Provide at least one file path.")
    return await _query_index(file_filter=files)


async def get_index(files: list[str] | None = None) -> list[FileIndex]:
    """
    Combined entry point — the single function the agent needs to call.

    Behaviour based on what you pass:

        get_index()                           → full repo (all files + symbols)
        get_index(files=["foo.py"])           → index for foo.py only
        get_index(files=["foo.py","bar.py"])  → index for those two files

    Designed as the agent's primary orientation tool.

    Recommended agent flow:
        1. get_index()                        # understand the whole repo (~5-10k tokens)
        2. get_index(files=["payment.py"])    # zoom into one file (~100 tokens)
        3. get_function_signature(...)        # sig + docstring of relevant symbol (~10 tokens)
        4. get_function_body(...)             # full body only if needed (~300 tokens)

    Args:
        files: None for full repo, or a non-empty list of specific file paths.

    Returns:
        List of FileIndex, one per file, each with a list of SymbolEntry.
    """
    if files is not None and len(files) == 0:
        raise ValueError("Pass None for the full repo index, or a non-empty list of file paths.")

    return await _query_index(file_filter=files)


# ---------------------------------------------------------------------------
# Call graph — what calls what, without reading any file
# ---------------------------------------------------------------------------

@dataclass
class CallEdge:
    """A single caller → callee relationship."""
    caller_name: str
    caller_file: str
    caller_line: int
    callee_name: str
    callee_file: str | None  # None if callee is external / unresolved


@dataclass
class RepoOverview:
    """
    Complete mental model of the repo in one object.

    What the agent gets:
      - Every file and its symbols (names, kinds, line ranges)
      - Every internal function call relationship
      - Per-symbol: what it calls, what calls it

    No file I/O — everything sourced from SQLite.
    Token cost: ~10-30k for a medium repo (200 files, 1000 symbols, 3000 edges).
    This is still 10-50x cheaper than reading even a fraction of the actual files.
    """
    # All files and their symbols
    files: list[FileIndex]

    # All call edges in the repo
    edges: list[CallEdge]

    # Convenience lookup: symbol_name -> list of callee names it calls
    callees: dict[str, list[str]]

    # Convenience lookup: symbol_name -> list of caller names that call it
    callers: dict[str, list[str]]


async def _query_call_edges(symbol_filter: list[str] | None = None) -> list[CallEdge]:
    """
    Pull call edges from the SQLite call_edges table.

    Expected schema (add migration if not present):
        CREATE TABLE call_edges (
            caller_id   INTEGER REFERENCES symbols(id),
            callee_name TEXT NOT NULL,      -- raw name as it appears in source
            callee_id   INTEGER REFERENCES symbols(id) NULL  -- NULL if unresolved
        );

    symbol_filter: if given, only return edges where caller or callee name is in the list.
    """
    if symbol_filter:
        placeholders = ", ".join("?" * len(symbol_filter))
        query_str = (
            "SELECT "
            "  sc.name  AS caller_name, "
            "  fc.path  AS caller_file, "
            "  sc.line_start AS caller_line, "
            "  ce.callee_name, "
            "  fe.path  AS callee_file "
            "FROM call_edges ce "
            "JOIN symbols sc ON ce.caller_id = sc.id "
            "JOIN files   fc ON sc.file_id   = fc.id "
            "LEFT JOIN symbols se ON ce.callee_id  = se.id "
            "LEFT JOIN files   fe ON se.file_id    = fe.id "
            f"WHERE sc.name IN ({placeholders}) OR ce.callee_name IN ({placeholders})"
        )
        params: list = symbol_filter + symbol_filter
    else:
        query_str = (
            "SELECT "
            "  sc.name  AS caller_name, "
            "  fc.path  AS caller_file, "
            "  sc.line_start AS caller_line, "
            "  ce.callee_name, "
            "  fe.path  AS callee_file "
            "FROM call_edges ce "
            "JOIN symbols sc ON ce.caller_id = sc.id "
            "JOIN files   fc ON sc.file_id   = fc.id "
            "LEFT JOIN symbols se ON ce.callee_id  = se.id "
            "LEFT JOIN files   fe ON se.file_id    = fe.id "
            "ORDER BY fc.path, sc.line_start"
        )
        params = []

    edges: list[CallEdge] = []
    async with get_db() as db:
        async with db.execute(query_str, params) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                edges.append(CallEdge(
                    caller_name=r["caller_name"],
                    caller_file=r["caller_file"],
                    caller_line=r["caller_line"],
                    callee_name=r["callee_name"],
                    callee_file=r["callee_file"],  # None if external/unresolved
                ))
    return edges


def _build_lookup_maps(edges: list[CallEdge]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """
    Build callees and callers dicts from a list of edges.
    Returns (callees, callers):
      callees["charge_customer"] = ["validate_card", "run_fraud_check"]
      callers["validate_card"]   = ["charge_customer", "update_payment"]
    """
    callees: dict[str, list[str]] = {}
    callers: dict[str, list[str]] = {}

    for edge in edges:
        callees.setdefault(edge.caller_name, [])
        if edge.callee_name not in callees[edge.caller_name]:
            callees[edge.caller_name].append(edge.callee_name)

        callers.setdefault(edge.callee_name, [])
        if edge.caller_name not in callers[edge.callee_name]:
            callers[edge.callee_name].append(edge.caller_name)

    return callees, callers


async def get_callers(symbol_name: str) -> list[CallEdge]:
    """
    Return all functions that call the given symbol.
    Use for impact analysis — "if I change this, what breaks?"

    Example:
        get_callers("validate_card")
        → [CallEdge(caller_name="charge_customer", caller_file="payment.py", ...)]
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be a non-empty string.")

    edges = await _query_call_edges(symbol_filter=[symbol_name])
    return [e for e in edges if e.callee_name == symbol_name]


async def get_callees(symbol_name: str) -> list[CallEdge]:
    """
    Return all functions that the given symbol calls internally.
    Use to understand what a function depends on before reading its body.

    Example:
        get_callees("charge_customer")
        → [CallEdge(callee_name="validate_card", ...), CallEdge(callee_name="run_fraud_check", ...)]
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be a non-empty string.")

    edges = await _query_call_edges(symbol_filter=[symbol_name])
    return [e for e in edges if e.caller_name == symbol_name]


async def get_repo_overview(
    files: list[str] | None = None,
) -> RepoOverview:
    """
    Single call that gives the agent a complete mental model of the repo.

    Combines:
      - Full file + symbol index  (what exists, where)
      - Full call graph           (what calls what)
      - Caller/callee lookup maps (pre-built for zero-cost traversal)

    Behaviour:
        get_repo_overview()                          # entire repo
        get_repo_overview(files=["payment.py"])      # one file + its call relationships
        get_repo_overview(files=["a.py", "b.py"])    # multiple files

    When files is specified, edges are filtered to only those where
    caller OR callee lives in the requested files — so cross-file
    dependencies are still visible.

    Token cost (approximate):
        Full repo  (200 files, 1000 symbols, 3000 edges) → ~15-30k tokens
        Single file (20 symbols, 60 edges)               → ~500 tokens
        This is 10-50x cheaper than reading actual source files.

    Recommended agent flow:
        1. get_repo_overview()                        # full mental model, no file reads
           → agent now knows: files, symbols, who calls who
        2. get_index(files=["payment.py"])            # zoom in if needed
        3. get_function_signature(file, start, end)  # cheap sig+docstring
        4. get_function_body(file, start, end)        # only if implementation needed

    Returns:
        RepoOverview(
          files   = [FileIndex(file="payment.py", symbols=[...]), ...],
          edges   = [CallEdge(caller="charge_customer", callee="validate_card", ...), ...],
          callees = {"charge_customer": ["validate_card", "run_fraud_check"], ...},
          callers = {"validate_card":   ["charge_customer", "update_payment"], ...},
        )
    """
    if files is not None and len(files) == 0:
        raise ValueError("Pass None for full repo overview, or a non-empty list of file paths.")

    # Run index query and edge query concurrently — both are pure DB reads
    file_index, all_edges = await asyncio.gather(
        _query_index(file_filter=files),
        _query_call_edges(symbol_filter=None),
    )

    # If scoped to specific files, filter edges to those involving those files
    if files:
        file_set = set(files)
        all_edges = [
            e for e in all_edges
            if e.caller_file in file_set or (e.callee_file and e.callee_file in file_set)
        ]

    callees, callers = _build_lookup_maps(all_edges)

    return RepoOverview(
        files=file_index,
        edges=all_edges,
        callees=callees,
        callers=callers,
    )