from __future__ import annotations

import os
import re
import shutil
import json
import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from codeengine.database.sqlite import get_db
from codeengine.models.search_models import Match, Symbol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RG_LANG_MAP = {
    "python": "py", "py": "py",
    "java": "java",
    "javascript": "js", "js": "js",
    "typescript": "ts", "ts": "ts",
    "go": "go",
    "rust": "rust",
}

SUBPROCESS_TIMEOUT = 30
DEFAULT_BODY_MAX_LINES = 100


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class FileStats:
    """One row in RepoSummary — path, symbol count, line count. No symbol names."""
    file: str
    symbol_count: int
    line_count: int


@dataclass
class RepoSummary:
    """Tier-1 repo view: counts only, no symbol names, no edges."""
    total_files: int
    total_symbols: int
    files: list[FileStats]


@dataclass
class SymbolEntry:
    """Minimal symbol descriptor — name, kind, line boundaries only."""
    name: str
    kind: str
    line_start: int
    line_end: int


@dataclass
class FileOverview:
    """Tier-2 file view: symbol names + line ranges, no bodies, no edges."""
    file: str
    total_lines: int
    total_symbols: int
    symbols: list[SymbolEntry]


@dataclass
class FunctionContext:
    """Tier-3 function view: signature always present; body chunked on demand."""
    file: str
    line_start: int
    line_end: int
    signature: str
    body: str | None = None
    total_lines: int = 0
    returned_lines: int = 0
    has_more: bool = False
    next_window_start: int | None = None


@dataclass
class CallEdge:
    """A single caller → callee relationship."""
    caller_name: str
    caller_file: str
    caller_line: int
    callee_name: str
    callee_file: str | None  # None if callee is external / unresolved


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def _get_binary_path(name: str) -> str:
    binary = shutil.which(name)
    if binary:
        return binary
    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        packages_dir = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
        if packages_dir.is_dir():
            pattern = "rg.exe" if name == "rg" else "fd.exe"
            found = list(packages_dir.rglob(pattern))
            if found:
                return str(found[0])
    return name


def _run_subprocess(args: list[str]) -> bytes:
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=SUBPROCESS_TIMEOUT,
            **kwargs,
        )
        return result.stdout
    except FileNotFoundError:
        logger.warning("Binary not found: %s. Is it installed and on PATH?", args[0])
        return b""
    except subprocess.TimeoutExpired:
        logger.warning("Subprocess timed out after %ds: %s", SUBPROCESS_TIMEOUT, args[0])
        return b""


def _escape_regex(pattern: str) -> str:
    return re.escape(pattern)


# ---------------------------------------------------------------------------
# File reading helpers
# ---------------------------------------------------------------------------

def _count_file_lines(file: str) -> int:
    path = Path(file)
    if not path.is_file():
        return 0
    with path.open("rb") as fh:
        return sum(1 for _ in fh)


def _read_lines(file: str, line_start: int, line_end: int) -> list[str]:
    if line_start < 1:
        raise ValueError(f"line_start must be >= 1, got {line_start}")
    if line_end < line_start:
        raise ValueError(f"line_end ({line_end}) must be >= line_start ({line_start})")
    path = Path(file)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file}")
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
    sig_lines: list[str] = []
    docstring_lines: list[str] = []
    in_def = False
    def_closed = False
    in_docstring = False
    docstring_quote: str = ""
    docstring_done = False

    for line in lines:
        stripped = line.strip()

        if not def_closed:
            if stripped.startswith("def ") or stripped.startswith("async def "):
                in_def = True
            if in_def:
                sig_lines.append(line)
                if stripped.endswith(":"):
                    def_closed = True
                continue

        if def_closed and not docstring_done:
            if not in_docstring:
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    docstring_quote = stripped[:3]
                    in_docstring = True
                    docstring_lines.append(line)
                    rest = stripped[3:]
                    if rest.endswith(docstring_quote) and len(rest) >= 3:
                        docstring_done = True
                        in_docstring = False
                    continue
                elif stripped == "":
                    continue
                else:
                    docstring_done = True
            else:
                docstring_lines.append(line)
                if stripped.endswith(docstring_quote) and stripped != docstring_quote:
                    docstring_done = True
                    in_docstring = False
                continue

        if def_closed and docstring_done:
            break

    result = "\n".join(sig_lines)
    if docstring_lines:
        result += "\n" + "\n".join(docstring_lines)
    return result


# ---------------------------------------------------------------------------
# Search functions
# ---------------------------------------------------------------------------

async def search_code(
    query: str,
    root: str,
    lang: str | None,
    limit: int,
    context_lines: int = 0,
) -> list[Match]:
    """
    Search for query in code files using ripgrep.

    Args:
        query:         Literal string to search for.
        root:          Directory to search under.
        lang:          Optional language filter (see RG_LANG_MAP).
        limit:         Max total matches to return (enforced globally).
        context_lines: Lines of surrounding context above/below each match.
                       0 = match line only (default). Pass e.g. 3 when you
                       need to see the call site in context.
    """
    if not query.strip():
        return []

    rg_type = None
    if lang:
        rg_type = RG_LANG_MAP.get(lang.lower())
        if rg_type is None:
            logger.warning("Language %r not in RG_LANG_MAP; filter ignored.", lang)

    rg_path = _get_binary_path("rg")
    args = [rg_path, "--json", f"--max-count={limit}", "--multiline"]

    if rg_type:
        args.extend(["--type", rg_type])

    if context_lines > 0:
        args.extend(["-C", str(context_lines)])

    normalized = _escape_regex(query).replace("\r\n", "\n").replace("\n", r"\r?\n")
    args.extend(["-e", normalized, root])

    stdout = await asyncio.to_thread(_run_subprocess, args)
    if not stdout:
        return []

    # Collect context lines per match keyed by (file, match_line)
    pending_before: list[str] = []
    last_match: Match | None = None
    matches: list[Match] = []

    for raw in stdout.decode(errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
            kind = obj.get("type")

            if kind == "context":
                data = obj["data"]
                ctx_line = data["lines"]["text"].rstrip()
                if last_match is None:
                    pending_before.append(ctx_line)
                else:
                    last_match.context_after.append(ctx_line)

            elif kind == "match":
                data = obj["data"]
                submatches = data["submatches"]
                m = Match(
                    file=data["path"]["text"],
                    line=data["line_number"],
                    col=submatches[0]["start"] if submatches else 0,
                    text=data["lines"]["text"].rstrip(),
                    context_before=list(pending_before),
                    context_after=[],
                )
                pending_before = []
                last_match = m
                matches.append(m)

            elif kind == "begin":
                pending_before = []
                last_match = None

        except (json.JSONDecodeError, KeyError, IndexError):
            continue

    return matches[:limit]


async def search_symbol(
    name: str,
    kind: str | None = None,
    limit: int = 50,
) -> list[Symbol]:
    """
    Search symbols in SQLite by name, ranked: exact → prefix → substring.

    Args:
        name:  Symbol name to search (min 2 chars).
        kind:  Optional kind filter (e.g. "function", "class").
        limit: Max results (default 50).
    """
    if not name or len(name.strip()) < 2:
        raise ValueError("Symbol name must be at least 2 characters.")

    # Three-tier ranking: exact=0, prefix=1, substring=2
    query_str = (
        "SELECT s.name, s.kind, f.path as file, s.line_start, s.line_end, "
        "  CASE "
        "    WHEN s.name = ?              THEN 0 "
        "    WHEN s.name LIKE ? || '%'    THEN 1 "
        "    ELSE                              2 "
        "  END AS rank "
        "FROM symbols s "
        "JOIN files f ON s.file_id = f.id "
        "WHERE s.name LIKE ?"
    )
    params: list = [name, name, f"%{name}%"]

    if kind:
        query_str += " AND s.kind = ?"
        params.append(kind)

    query_str += " ORDER BY rank, s.name LIMIT ?"
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
    Find files matching pattern under root using fd.
    Pass '*' explicitly if you want all files.
    """
    if not pattern or not pattern.strip():
        raise ValueError(
            "pattern must be non-empty. Pass '*' to list all files."
        )
    fd_path = _get_binary_path("fd")
    args = [fd_path, "--type", "f", pattern, root]
    stdout = await asyncio.to_thread(_run_subprocess, args)
    return [l.strip() for l in stdout.decode(errors="replace").splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# Tier 1 — repo summary (counts only, no symbol names)
# ---------------------------------------------------------------------------

async def get_repo_summary() -> RepoSummary:
    """
    Cheapest possible repo orientation — file paths + counts only.

    Token cost: ~20 tokens/file → ~4k tokens for a 200-file project.
    No symbol names, no edges, no line ranges.

    Flow:
        1. get_repo_summary()          # what files exist, rough sizes
        2. get_file_overview("x.py")   # symbol names + line ranges for one file
        3. get_function_signature(...) # sig + docstring
        4. get_function_body(...)      # chunked body, only if needed
    """
    query_str = (
        "SELECT f.path, COUNT(s.id) AS symbol_count "
        "FROM files f "
        "LEFT JOIN symbols s ON s.file_id = f.id "
        "GROUP BY f.id "
        "ORDER BY f.path"
    )
    files: list[FileStats] = []
    total_symbols = 0
    async with get_db() as db:
        async with db.execute(query_str) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                line_count = await asyncio.to_thread(_count_file_lines, r["path"])
                sc = r["symbol_count"]
                total_symbols += sc
                files.append(FileStats(file=r["path"], symbol_count=sc, line_count=line_count))
    return RepoSummary(total_files=len(files), total_symbols=total_symbols, files=files)


# ---------------------------------------------------------------------------
# Tier 2 — file overview (symbol names + line ranges, no bodies)
# ---------------------------------------------------------------------------

async def get_file_overview(file: str) -> FileOverview:
    """
    Symbol map for one file — names, kinds, line ranges only.

    Token cost: ~50–200 tokens regardless of file size.
    Call after get_repo_summary narrows down which file to investigate.
    """
    query_str = (
        "SELECT s.name, s.kind, s.line_start, s.line_end "
        "FROM symbols s "
        "JOIN files f ON s.file_id = f.id "
        "WHERE f.path = ? "
        "ORDER BY s.line_start"
    )
    symbols: list[SymbolEntry] = []
    async with get_db() as db:
        async with db.execute(query_str, [file]) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                symbols.append(SymbolEntry(
                    name=r["name"],
                    kind=r["kind"],
                    line_start=r["line_start"],
                    line_end=r["line_end"],
                ))
    total_lines = await asyncio.to_thread(_count_file_lines, file)
    return FileOverview(
        file=file,
        total_lines=total_lines,
        total_symbols=len(symbols),
        symbols=symbols,
    )


# ---------------------------------------------------------------------------
# Tier 3 — function signature + chunked body
# ---------------------------------------------------------------------------

async def get_function_signature(file: str, line_start: int, line_end: int) -> FunctionContext:
    """
    Return only the function signature + docstring.

    Token cost: ~5–15 tokens regardless of function size.
    Always call this before get_function_body.
    """
    lines = await asyncio.to_thread(_read_lines, file, line_start, line_end)
    signature = _extract_signature_and_docstring(lines)
    total = line_end - line_start + 1
    return FunctionContext(
        file=file,
        line_start=line_start,
        line_end=line_end,
        signature=signature,
        body=None,
        total_lines=total,
        returned_lines=0,
        has_more=total > 0,
        next_window_start=line_start,
    )


async def get_function_body(
    file: str,
    line_start: int,
    line_end: int,
    window_start: int | None = None,
    window_end: int | None = None,
    max_lines: int = DEFAULT_BODY_MAX_LINES,
) -> FunctionContext:
    """
    Return a chunk of a function body — never a full dump for large functions.

    Args:
        file:         Source file path.
        line_start:   First line of the function (from symbols table).
        line_end:     Last line of the function (from symbols table).
        window_start: Start of the reading window (default: line_start).
        window_end:   End of the reading window (default: window_start + max_lines).
        max_lines:    Hard cap per call (default: 100).

    Pagination example for a 400-line function:
        ctx = await get_function_body(file, 10, 410)
        # ctx.returned_lines=100, ctx.has_more=True, ctx.next_window_start=110
        ctx = await get_function_body(file, 10, 410, window_start=110)
    """
    effective_start = max(window_start or line_start, line_start)
    effective_end = min(
        window_end or (effective_start + max_lines - 1),
        effective_start + max_lines - 1,
        line_end,
    )

    body_lines, sig_lines = await asyncio.gather(
        asyncio.to_thread(_read_lines, file, effective_start, effective_end),
        asyncio.to_thread(_read_lines, file, line_start, line_end),
    )

    total = line_end - line_start + 1
    returned = effective_end - effective_start + 1
    has_more = effective_end < line_end

    return FunctionContext(
        file=file,
        line_start=line_start,
        line_end=line_end,
        signature=_extract_signature_and_docstring(sig_lines),
        body="\n".join(body_lines),
        total_lines=total,
        returned_lines=returned,
        has_more=has_more,
        next_window_start=effective_end + 1 if has_more else None,
    )


# ---------------------------------------------------------------------------
# Call graph helpers
# ---------------------------------------------------------------------------

async def _query_call_edges(symbol_filter: list[str] | None = None) -> list[CallEdge]:
    if symbol_filter:
        placeholders = ", ".join("?" * len(symbol_filter))
        query_str = (
            "SELECT sc.name AS caller_name, fc.path AS caller_file, "
            "       sc.line_start AS caller_line, ce.callee_name, fe.path AS callee_file "
            "FROM call_edges ce "
            "JOIN symbols sc ON ce.caller_id = sc.id "
            "JOIN files   fc ON sc.file_id   = fc.id "
            "LEFT JOIN symbols se ON ce.callee_id = se.id "
            "LEFT JOIN files   fe ON se.file_id   = fe.id "
            f"WHERE sc.name IN ({placeholders}) OR ce.callee_name IN ({placeholders})"
        )
        params: list = symbol_filter + symbol_filter
    else:
        query_str = (
            "SELECT sc.name AS caller_name, fc.path AS caller_file, "
            "       sc.line_start AS caller_line, ce.callee_name, fe.path AS callee_file "
            "FROM call_edges ce "
            "JOIN symbols sc ON ce.caller_id = sc.id "
            "JOIN files   fc ON sc.file_id   = fc.id "
            "LEFT JOIN symbols se ON ce.callee_id = se.id "
            "LEFT JOIN files   fe ON se.file_id   = fe.id "
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
                    callee_file=r["callee_file"],
                ))
    return edges


async def get_callers(symbol_name: str, limit: int = 20) -> list[CallEdge]:
    """
    Return functions that call the given symbol, capped at limit.

    Use for impact analysis — "if I change this, what breaks?"
    Popular functions can have hundreds of callers; limit prevents floods.
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be a non-empty string.")
    edges = await _query_call_edges(symbol_filter=[symbol_name])
    return [e for e in edges if e.callee_name == symbol_name][:limit]


async def get_callees(symbol_name: str, limit: int = 20) -> list[CallEdge]:
    """
    Return functions that the given symbol calls, capped at limit.

    Use to understand dependencies before reading a function body.
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be a non-empty string.")
    edges = await _query_call_edges(symbol_filter=[symbol_name])
    return [e for e in edges if e.caller_name == symbol_name][:limit]




# ---------------------------------------------------------------------------
# FileIndex (for get_index)
# ---------------------------------------------------------------------------

@dataclass
class FileIndex:
    """All symbols belonging to one file."""
    file: str
    symbols: list[SymbolEntry] = field(default_factory=list)


@dataclass
class RepoOverview:
    """
    Complete mental model of the repo in one object.
    - Every file and its symbols (names, kinds, line ranges)
    - Every internal function call relationship
    - Per-symbol: what it calls, what calls it
    
    Token cost: ~10-30k for medium repo (200 files, 1000 symbols, 3000 edges).
    10-50x cheaper than reading actual files.
    """
    files: list[FileIndex]
    edges: list[CallEdge]
    callees: dict[str, list[str]]
    callers: dict[str, list[str]]


# ---------------------------------------------------------------------------
# Index queries
# ---------------------------------------------------------------------------

async def _query_index(file_filter: list[str] | None) -> list[FileIndex]:
    """
    Core DB query shared by all index functions.
    Pulls (file, name, kind, line_start, line_end) grouped by file.
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


async def _query_call_edges(symbol_filter: list[str] | None = None) -> list[CallEdge]:
    """
    Pull call edges from the SQLite call_edges table.
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
                    callee_file=r["callee_file"],
                ))
    return edges


def _build_lookup_maps(edges: list[CallEdge]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """
    Build callees and callers dicts from edges.
    Returns (callees, callers)
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


async def get_index(files: list[str] | None = None) -> list[FileIndex]:
    """
    Get file and symbol index for the repository.
    - get_index() → full repo (all files + symbols)
    - get_index(files=["foo.py"]) → index for foo.py only
    
    Recommended agent flow:
        1. get_index() - understand whole repo (~5-10k tokens)
        2. get_index(files=["payment.py"]) - zoom into file (~100 tokens)
        3. get_function_signature(...) - sig + docstring (~10 tokens)
        4. get_function_body(...) - full body if needed (~300 tokens)
    """
    if files is not None and len(files) == 0:
        raise ValueError("Pass None for full repo index, or non-empty list of file paths.")
    return await _query_index(file_filter=files)


async def get_callers(symbol_name: str) -> list[CallEdge]:
    """
    Return all functions that call the given symbol.
    Use for impact analysis: "if I change this, what breaks?"
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be non-empty.")
    edges = await _query_call_edges(symbol_filter=[symbol_name])
    return [e for e in edges if e.callee_name == symbol_name]


async def get_callees(symbol_name: str) -> list[CallEdge]:
    """
    Return all functions that the given symbol calls internally.
    Use to understand dependencies before reading body.
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be nonexistent.")
    edges = await _query_call_edges(symbol_filter=[symbol_name])
    return [e for e in edges if e.caller_name == symbol_name]


async def get_repo_overview(files: list[str] | None = None) -> RepoOverview:
    """
    Single call that gives complete mental model of repo.
    
    Combines:
    - Full file + symbol index (what exists, where)
    - Full call graph (what calls what)
    - Caller/callee lookup maps (pre-built)
    
    Token cost: ~15-30k for full repo (200 files, 1000 symbols, 3000 edges)
              or ~500 tokens for single file
    """
    if files is not None and len(files) == 0:
        raise ValueError("Pass None for full repo, or non-empty list of file paths.")

    # Run queries concurrently
    file_index, all_edges = await asyncio.gather(
        _query_index(file_filter=files),
        _query_call_edges(symbol_filter=None),
    )

    # If scoped to specific files, filter edges
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