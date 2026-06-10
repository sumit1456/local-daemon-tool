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
    file_filter: list[str] | None = None,
    dir_filter: str | None = None,
    package_filter: str | None = None,
) -> list[Symbol]:
    """
    Search symbols in SQLite by name, ranked: exact → prefix → substring.

    Args:
        name:  Symbol name to search (min 2 chars).
        kind:  Optional kind filter (e.g. "function", "class").
        limit: Max results (default 50).
        file_filter: Optional list of file paths to restrict search.
        dir_filter:  Optional directory prefix filter.
        package_filter: Optional package path filter.
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

    if file_filter:
        placeholders = ", ".join("?" * len(file_filter))
        query_str += f" AND f.path IN ({placeholders})"
        params.extend(file_filter)

    if dir_filter:
        prefix = dir_filter.rstrip("/").replace("\\", "/") + "/"
        query_str += " AND f.path LIKE ?"
        params.append(prefix + "%")

    if package_filter:
        pkg = package_filter.rstrip("/").replace("\\", "/")
        query_str += " AND (f.path LIKE ? OR f.path LIKE ?)"
        params.append(pkg + "/%")
        params.append("%/" + pkg + "/%")

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

async def _query_index(
    file_filter: list[str] | None = None,
    dir_filter: str | None = None,
    package_filter: str | None = None,
    query_filter: str | None = None,
) -> list[FileIndex]:
    """
    Core DB query shared by all index functions.
    Pulls (file, name, kind, line_start, line_end) grouped by file.

    Filters (all optional, combined with AND):
        file_filter:    Exact file paths (IN clause).
        dir_filter:     Directory prefix — files whose path starts with this.
        package_filter: Package path — files under this package directory.
        query_filter:   Substring match on file path.
    """
    conditions: list[str] = []
    params: list = []

    if file_filter:
        placeholders = ", ".join("?" * len(file_filter))
        conditions.append(f"f.path IN ({placeholders})")
        params.extend(file_filter)

    if dir_filter:
        # Normalize: ensure trailing slash for prefix match
        prefix = dir_filter.rstrip("/").replace("\\", "/") + "/"
        conditions.append("f.path LIKE ?")
        params.append(prefix + "%")

    if package_filter:
        # Match files under the package dir (with or without leading path)
        pkg = package_filter.rstrip("/").replace("\\", "/")
        conditions.append("(f.path LIKE ? OR f.path LIKE ?)")
        params.append(pkg + "/%")
        params.append("%/" + pkg + "/%")

    if query_filter:
        conditions.append("f.path LIKE ?")
        params.append("%" + query_filter + "%")

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    query_str = (
        "SELECT f.path, s.name, s.kind, s.line_start, s.line_end "
        "FROM symbols s "
        "JOIN files f ON s.file_id = f.id "
        f"{where_clause} "
        "ORDER BY f.path, s.line_start"
    )

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


async def _query_call_edges(
    symbol_filter: list[str] | None = None,
    file_filter: list[str] | None = None,
    dir_filter: str | None = None,
    package_filter: str | None = None,
) -> list[CallEdge]:
    """
    Pull call edges from the SQLite call_edges table.
    Supports optional file/dir/package filters on the caller side.
    """
    conditions: list[str] = []
    params: list = []

    if symbol_filter:
        placeholders = ", ".join("?" * len(symbol_filter))
        conditions.append(f"(sc.name IN ({placeholders}) OR ce.callee_name IN ({placeholders}))")
        params.extend(symbol_filter + symbol_filter)

    if file_filter:
        placeholders = ", ".join("?" * len(file_filter))
        conditions.append(f"fc.path IN ({placeholders})")
        params.extend(file_filter)

    if dir_filter:
        prefix = dir_filter.rstrip("/").replace("\\", "/") + "/"
        conditions.append("fc.path LIKE ?")
        params.append(prefix + "%")

    if package_filter:
        pkg = package_filter.rstrip("/").replace("\\", "/")
        conditions.append("(fc.path LIKE ? OR fc.path LIKE ?)")
        params.append(pkg + "/%")
        params.append("%/" + pkg + "/%")

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    query_str = (
        "SELECT "
        "  sc.name  AS caller_name, "
        "  fc.path  AS caller_file, "
        "  sc.line_start AS caller_line, "
        "  ce.callee_name, "
        "  ce.callee_file "
        "FROM call_edges ce "
        "JOIN symbols sc ON ce.caller_id = sc.id "
        "JOIN files   fc ON sc.file_id   = fc.id "
        f"{where_clause} "
        "ORDER BY fc.path, sc.line_start"
    )

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


async def get_index(
    files: list[str] | None = None,
    dir_filter: str | None = None,
    package_filter: str | None = None,
    query_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    Get file and symbol index for the repository.
    - get_index() → full repo (all files + symbols)
    - get_index(files=["foo.py"]) → index for foo.py only
    - get_index(dir_filter="src/core") → all files under src/core/
    - get_index(package_filter="codeengine.core") → all files in that package

    Recommended agent flow:
        1. get_index() - understand whole repo (~5-10k tokens)
        2. get_index(files=["payment.py"]) - zoom into file (~100 tokens)
        3. get_function_signature(...) - sig + docstring (~10 tokens)
        4. get_function_body(...) - full body if needed (~300 tokens)
    """
    if files is not None and len(files) == 0:
        raise ValueError("Pass None for full repo index, or non-empty list of file paths.")
    all_files = await _query_index(
        file_filter=files,
        dir_filter=dir_filter,
        package_filter=package_filter,
        query_filter=query_filter,
    )
    total = len(all_files)
    sliced = all_files[offset:offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "files": sliced,
    }


async def get_callers(
    symbol_name: str,
    file_filter: list[str] | None = None,
    dir_filter: str | None = None,
    package_filter: str | None = None,
) -> list[CallEdge]:
    """
    Return all functions that call the given symbol.
    Use for impact analysis: "if I change this, what breaks?"
    Supports optional file/dir/package filters on the caller side.
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be non-empty.")
    edges = await _query_call_edges(
        symbol_filter=[symbol_name],
        file_filter=file_filter,
        dir_filter=dir_filter,
        package_filter=package_filter,
    )
    return [e for e in edges if e.callee_name == symbol_name]


async def get_callees(
    symbol_name: str,
    file_filter: list[str] | None = None,
    dir_filter: str | None = None,
    package_filter: str | None = None,
) -> list[CallEdge]:
    """
    Return all functions that the given symbol calls internally.
    Use to understand dependencies before reading body.
    Supports optional file/dir/package filters on the caller side.
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be non-empty.")
    edges = await _query_call_edges(
        symbol_filter=[symbol_name],
        file_filter=file_filter,
        dir_filter=dir_filter,
        package_filter=package_filter,
    )
    return [e for e in edges if e.caller_name == symbol_name]


# ---------------------------------------------------------------------------
# Symbol usages (references table)
# ---------------------------------------------------------------------------

@dataclass
class SymbolUsage:
    """A single usage/reference of a symbol in the codebase."""
    symbol_name: str
    kind: str
    file: str
    line: int


async def find_symbol_usages(symbol_name: str, limit: int = 50) -> list[SymbolUsage]:
    """
    Find all places where a symbol is referenced (used) in the codebase.

    This goes beyond call_edges — it finds assignments, imports, attribute access,
    type annotations, and any other identifier references.

    Args:
        symbol_name: Name of the symbol to find usages for.
        limit:       Max results to return (default 50).
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be a non-empty string.")

    query_str = (
        "SELECT s.name AS symbol_name, s.kind, f.path AS file, r.line "
        "FROM symbol_references r "
        "JOIN symbols s ON r.symbol_id = s.id "
        "JOIN files   f ON r.file_id   = f.id "
        "WHERE s.name = ? "
        "ORDER BY f.path, r.line "
        "LIMIT ?"
    )
    usages: list[SymbolUsage] = []
    async with get_db() as db:
        async with db.execute(query_str, [symbol_name, limit]) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                usages.append(SymbolUsage(
                    symbol_name=r["symbol_name"],
                    kind=r["kind"],
                    file=r["file"],
                    line=r["line"],
                ))
    return usages


# ---------------------------------------------------------------------------
# Docstrings (docstrings table)
# ---------------------------------------------------------------------------

@dataclass
class DocstringResult:
    """Docstring content for a symbol."""
    symbol_name: str
    kind: str
    file: str
    content: str
    line_start: int
    line_end: int


async def get_docstring(symbol_name: str, file: str | None = None) -> list[DocstringResult]:
    """
    Retrieve docstrings for a symbol, optionally filtered by file.

    Args:
        symbol_name: Name of the symbol.
        file:        Optional file path to narrow results.
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be a non-empty string.")

    if file:
        query_str = (
            "SELECT s.name AS symbol_name, s.kind, f.path AS file, "
            "       d.content, d.line_start, d.line_end "
            "FROM docstrings d "
            "JOIN symbols s ON d.symbol_id = s.id "
            "JOIN files   f ON s.file_id   = f.id "
            "WHERE s.name = ? AND f.path = ?"
        )
        params: list = [symbol_name, file]
    else:
        query_str = (
            "SELECT s.name AS symbol_name, s.kind, f.path AS file, "
            "       d.content, d.line_start, d.line_end "
            "FROM docstrings d "
            "JOIN symbols s ON d.symbol_id = s.id "
            "JOIN files   f ON s.file_id   = f.id "
            "WHERE s.name = ?"
        )
        params = [symbol_name]

    results: list[DocstringResult] = []
    async with get_db() as db:
        async with db.execute(query_str, params) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                results.append(DocstringResult(
                    symbol_name=r["symbol_name"],
                    kind=r["kind"],
                    file=r["file"],
                    content=r["content"],
                    line_start=r["line_start"],
                    line_end=r["line_end"],
                ))
    return results


# ---------------------------------------------------------------------------
# Import dependency queries (imports table)
# ---------------------------------------------------------------------------

@dataclass
class ImportInfo:
    """A single import entry from a file."""
    module: str
    level: int
    is_star: bool


@dataclass
class FileImports:
    """All imports for a single file."""
    file: str
    imports: list[ImportInfo]


@dataclass
class ImporterInfo:
    """A file that imports a given module."""
    file: str
    module: str
    level: int
    is_star: bool


async def get_file_imports(file: str) -> FileImports:
    """
    Return all imports used by a file.

    Use case: "What does this file depend on?"
    Token cost: ~50-100 tokens
    """
    if not file or not file.strip():
        raise ValueError("file must be non-empty.")

    query_str = (
        "SELECT i.module, i.level, i.is_star "
        "FROM imports i "
        "JOIN files f ON i.file_id = f.id "
        "WHERE f.path = ? "
        "ORDER BY i.module"
    )

    imports: list[ImportInfo] = []
    async with get_db() as db:
        async with db.execute(query_str, [file]) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                imports.append(ImportInfo(
                    module=r["module"],
                    level=r["level"],
                    is_star=bool(r["is_star"]),
                ))

    return FileImports(file=file, imports=imports)


async def get_importers(module: str) -> list[ImporterInfo]:
    """
    Return all files that import a given module (reverse dependency lookup).

    Use case: "Who uses this module?" / "What breaks if I change this?"
    Token cost: ~100-200 tokens

    Args:
        module: Module name to search for (exact match or prefix).
    """
    if not module or not module.strip():
        raise ValueError("module must be non-empty.")

    # Use LIKE with prefix match to catch submodules
    # e.g. searching "models" will also match "models.user", "models.task"
    query_str = (
        "SELECT f.path AS file, i.module, i.level, i.is_star "
        "FROM imports i "
        "JOIN files f ON i.file_id = f.id "
        "WHERE i.module = ? OR i.module LIKE ? "
        "ORDER BY f.path"
    )

    results: list[ImporterInfo] = []
    async with get_db() as db:
        async with db.execute(query_str, [module, module + ".%"]) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                results.append(ImporterInfo(
                    file=r["file"],
                    module=r["module"],
                    level=r["level"],
                    is_star=bool(r["is_star"]),
                ))

    return results


async def get_file_deps(file: str) -> dict:
    """
    Complete dependency picture for a file — both what it imports and what imports it.

    Use case: Understand file dependencies in both directions.
    Token cost: ~100-150 tokens
    """
    file_imports, _ = await asyncio.gather(
        get_file_imports(file),
        asyncio.sleep(0),  # placeholder to keep gather happy
    )

    # Get reverse dependencies: files that import modules defined in this file
    # First, find what this file exports (symbols defined here)
    query_str = (
        "SELECT i.module "
        "FROM imports i "
        "JOIN files f ON i.file_id = f.id "
        "WHERE f.path = ? "
        "ORDER BY i.module"
    )
    imported_modules = []
    async with get_db() as db:
        async with db.execute(query_str, [file]) as cursor:
            rows = await cursor.fetchall()
            imported_modules = [r["module"] for r in rows]

    # Find files that import any of the modules imported by this file
    imported_by: list[ImporterInfo] = []
    if imported_modules:
        # Build a query to find reverse dependencies
        # This is a simplified version - find files that share the same imports
        reverse_query = (
            "SELECT DISTINCT f.path AS file, i.module, i.level, i.is_star "
            "FROM imports i "
            "JOIN files f ON i.file_id = f.id "
            "WHERE f.path != ? AND i.module IN ("
            + ",".join("?" * len(imported_modules))
            + ") "
            "ORDER BY f.path"
        )
        params = [file] + imported_modules
        async with get_db() as db:
            async with db.execute(reverse_query, params) as cursor:
                rows = await cursor.fetchall()
                for r in rows:
                    imported_by.append(ImporterInfo(
                        file=r["file"],
                        module=r["module"],
                        level=r["level"],
                        is_star=bool(r["is_star"]),
                    ))

    return {
        "file": file,
        "imports": [
            {"module": imp.module, "level": imp.level, "is_star": imp.is_star}
            for imp in file_imports.imports
        ],
        "imported_by": [
            {"file": imp.file, "module": imp.module, "level": imp.level, "is_star": imp.is_star}
            for imp in imported_by
        ],
    }


async def get_type_info(symbol_name: str, file: str | None = None) -> dict:
    """
    Return parameter types and return type for a symbol.

    Use case: "What type does this return?" — prevents API misuse.
    Token cost: ~30-50 tokens
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be non-empty.")

    if file:
        query_str = (
            "SELECT s.name, t.param_name, t.annotation, t.is_return "
            "FROM type_hints t "
            "JOIN symbols s ON t.symbol_id = s.id "
            "JOIN files f ON s.file_id = f.id "
            "WHERE s.name = ? AND f.path = ? "
            "ORDER BY t.param_name"
        )
        params: list = [symbol_name, file]
    else:
        query_str = (
            "SELECT s.name, t.param_name, t.annotation, t.is_return "
            "FROM type_hints t "
            "JOIN symbols s ON t.symbol_id = s.id "
            "WHERE s.name = ? "
            "ORDER BY t.param_name"
        )
        params = [symbol_name]

    params_dict: dict[str, str] = {}
    returns: str | None = None
    async with get_db() as db:
        async with db.execute(query_str, params) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                if r["is_return"]:
                    returns = r["annotation"]
                elif r["param_name"]:
                    params_dict[r["param_name"]] = r["annotation"]

    return {
        "name": symbol_name,
        "params": params_dict,
        "returns": returns,
    }


async def get_defined_symbols(file: str) -> dict:
    """
    Quick file overview — what's defined in this file without full parse.

    Use case: "What's defined in this file?"
    Token cost: ~50-80 tokens
    """
    if not file or not file.strip():
        raise ValueError("file must be non-empty.")

    query_str = (
        "SELECT s.name, s.kind "
        "FROM symbols s "
        "JOIN files f ON s.file_id = f.id "
        "WHERE f.path = ? "
        "ORDER BY s.kind, s.name"
    )

    functions: list[str] = []
    classes: list[str] = []
    methods: list[str] = []
    constants: list[str] = []

    async with get_db() as db:
        async with db.execute(query_str, [file]) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                name = r["name"]
                kind = r["kind"]
                if kind == "function":
                    functions.append(name)
                elif kind == "class":
                    classes.append(name)
                elif kind == "method":
                    methods.append(name)
                elif kind == "constant":
                    constants.append(name)

    return {
        "file": file,
        "functions": functions,
        "classes": classes,
        "methods": methods,
        "constants": constants,
    }


async def count_references(symbol_name: str) -> dict:
    """
    Count how many times a symbol is referenced across the codebase.

    Use case: Risk assessment before changes — "How widely is this used?"
    Token cost: ~20-50 tokens
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be non-empty.")

    query_str = (
        "SELECT COUNT(*) as cnt "
        "FROM symbol_references r "
        "JOIN symbols s ON r.symbol_id = s.id "
        "WHERE s.name = ?"
    )

    count = 0
    async with get_db() as db:
        async with db.execute(query_str, [symbol_name]) as cursor:
            row = await cursor.fetchone()
            if row:
                count = row["cnt"]

    return {
        "symbol": symbol_name,
        "references": count,
    }


async def impact_analysis(symbol_name: str) -> dict:
    """
    Full impact assessment before changing a symbol.

    Combines direct callers, symbol references, and affected files.
    Use case: "If I change this, what breaks?"
    Token cost: ~200-400 tokens
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be non-empty.")

    callers_query = (
        "SELECT DISTINCT sc.name AS caller_name, fc.path AS caller_file "
        "FROM call_edges ce "
        "JOIN symbols sc ON ce.caller_id = sc.id "
        "JOIN files fc ON sc.file_id = fc.id "
        "WHERE ce.callee_name = ?"
    )

    refs_query = (
        "SELECT DISTINCT f.path AS ref_file "
        "FROM symbol_references r "
        "JOIN symbols s ON r.symbol_id = s.id "
        "JOIN files f ON r.file_id = f.id "
        "WHERE s.name = ?"
    )

    direct_callers: list[dict] = []
    affected_files: list[str] = []

    async with get_db() as db:
        async with db.execute(callers_query, [symbol_name]) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                direct_callers.append({
                    "name": r["caller_name"],
                    "file": r["caller_file"],
                })

        async with db.execute(refs_query, [symbol_name]) as cursor:
            rows = await cursor.fetchall()
            affected_files = [r["ref_file"] for r in rows]

    # Deduplicate files
    affected_files = sorted(set(affected_files))

    return {
        "symbol": symbol_name,
        "direct_callers": len(direct_callers),
        "callers": direct_callers,
        "affected_files": affected_files,
    }


async def trace_execution(symbol_name: str, max_depth: int = 5) -> dict:
    """
    Trace execution flow through the application from a given symbol.

    Shows the call chain: who calls this, who calls those callers, etc.
    Use case: "How does a request flow through the system?"
    Token cost: ~200-500 tokens
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be non-empty.")

    visited: set[str] = set()
    flow: list[dict] = []

    async def _trace(name: str, depth: int, path: list[str]) -> None:
        if depth > max_depth or name in visited:
            return
        visited.add(name)

        query_str = (
            "SELECT DISTINCT sc.name AS caller_name, fc.path AS caller_file, sc.line_start AS caller_line "
            "FROM call_edges ce "
            "JOIN symbols sc ON ce.caller_id = sc.id "
            "JOIN files fc ON sc.file_id = fc.id "
            "WHERE ce.callee_name = ?"
        )

        async with get_db() as db:
            async with db.execute(query_str, [name]) as cursor:
                rows = await cursor.fetchall()
                for r in rows:
                    caller_name = r["caller_name"]
                    if caller_name not in visited:
                        new_path = path + [f"{caller_name}() -> {name}()"]
                        flow.append({
                            "caller": caller_name,
                            "callee": name,
                            "caller_file": r["caller_file"],
                            "caller_line": r["caller_line"],
                            "depth": depth,
                            "chain": " -> ".join(new_path),
                        })
                        await _trace(caller_name, depth + 1, new_path)

    await _trace(symbol_name, 1, [f"{symbol_name}()"])

    return {
        "symbol": symbol_name,
        "max_depth": max_depth,
        "flow": flow,
    }


async def get_repo_overview(
    files: list[str] | None = None,
    dir_filter: str | None = None,
    package_filter: str | None = None,
    query_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    Single call that gives complete mental model of repo.

    Combines:
    - Full file + symbol index (what exists, where)
    - Full call graph (what calls what)
    - Caller/callee lookup maps (pre-built)

    Filters (all optional, combined with AND):
        files:          Exact file paths.
        dir_filter:     Directory prefix — files under this dir.
        package_filter: Package path — files in this package.
        query_filter:   Substring match on file path.

    Pagination:
        limit:  Max number of files to return (default: 50).
        offset: Number of files to skip (default: 0).

    Token cost: ~15-30k for full repo (200 files, 1000 symbols, 3000 edges)
              or ~500 tokens for single file
    """
    if files is not None and len(files) == 0:
        raise ValueError("Pass None for full repo, or non-empty list of file paths.")

    # Run index query concurrently with call edges
    all_files, all_edges = await asyncio.gather(
        _query_index(
            file_filter=files,
            dir_filter=dir_filter,
            package_filter=package_filter,
            query_filter=query_filter,
        ),
        _query_call_edges(symbol_filter=None),
    )

    total_files = len(all_files)
    sliced_files = all_files[offset:offset + limit]
    sliced_file_set = {fi.file for fi in sliced_files}

    # Filter edges to only include those touching files in the result set
    has_filters = any([files, dir_filter, package_filter, query_filter])
    if has_filters:
        if sliced_file_set:
            all_edges = [
                e for e in all_edges
                if e.caller_file in sliced_file_set or (e.callee_file and e.callee_file in sliced_file_set)
            ]
        else:
            all_edges = []

    callees, callers = _build_lookup_maps(all_edges)

    return {
        "total_files": total_files,
        "offset": offset,
        "limit": limit,
        "files": sliced_files,
        "edges": all_edges,
        "callees": callees,
        "callers": callers,
    }


@dataclass
class EditContext:
    file: str
    symbol_name: str
    kind: str
    line_start: int
    line_end: int
    total_file_lines: int
    preamble: str
    source: str
    signature: str
    callers: list[str]
    callees: list[str]
    imports: list[str]


async def get_edit_context(
    symbol_name: str,
    file: str | None = None,
    dir_filter: str | None = None,
    package_filter: str | None = None,
) -> EditContext | list[dict]:
    """
    Get all structured context required to edit a symbol without reading the whole file.
    If multiple symbols match, returns a list of candidate details for disambiguation.
    """
    if not symbol_name or not symbol_name.strip():
        raise ValueError("symbol_name must be non-empty.")

    # Search for the symbol using filters
    matching_symbols = await search_symbol(
        name=symbol_name,
        file_filter=[file] if file else None,
        dir_filter=dir_filter,
        package_filter=package_filter,
    )

    # Filter to exact name matches first to avoid prefix/substring matches if an exact match exists
    exact_matches = [s for s in matching_symbols if s.name == symbol_name]
    candidates = exact_matches if exact_matches else matching_symbols

    if not candidates:
        raise ValueError(f"Symbol '{symbol_name}' not found with the specified filters.")

    if len(candidates) > 1:
        # Return candidates to let the client disambiguate
        return [
            {
                "file": c.file,
                "kind": c.kind,
                "line_start": c.line_start,
                "line_end": c.line_end,
            }
            for c in candidates
        ]

    target = candidates[0]
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    target_file = str((repo_root / target.file).resolve())

    # 1. Total lines in file
    total_lines = await asyncio.to_thread(_count_file_lines, target_file)

    # 2. Read actual source lines of the symbol
    source_lines = await asyncio.to_thread(_read_lines, target_file, target.line_start, target.line_end)
    source = "\n".join(source_lines)

    # 3. Read preamble (decorators/comments up to 3 lines above start line)
    preamble = ""
    if target.line_start > 1:
        preamble_start = max(1, target.line_start - 3)
        preamble_end = target.line_start - 1
        preamble_lines = await asyncio.to_thread(_read_lines, target_file, preamble_start, preamble_end)
        preamble = "\n".join(preamble_lines)

    # 4. Signature + Docstring
    signature = _extract_signature_and_docstring(source_lines)

    # 5. Callers
    callers_data = await get_callers(symbol_name, file_filter=[target_file])
    callers = sorted(list({c.caller_name for c in callers_data}))

    # 6. Callees
    callees_data = await get_callees(symbol_name, file_filter=[target_file])
    callees = sorted(list({c.callee_name for c in callees_data}))

    # 7. File imports
    try:
        imports_data = await get_file_imports(target_file)
        # Reconstruct simple import strings or return module names
        imports = [imp.module for imp in imports_data.imports]
    except Exception:
        imports = []

    return EditContext(
        file=target_file,
        symbol_name=target.name,
        kind=target.kind,
        line_start=target.line_start,
        line_end=target.line_end,
        total_file_lines=total_lines,
        preamble=preamble,
        source=source,
        signature=signature,
        callers=callers,
        callees=callees,
        imports=imports,
    )