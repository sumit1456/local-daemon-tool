import hashlib
import asyncio
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from codeengine.database.sqlite import get_db
from codeengine.core.ast_engine import LANG_MAP, detect_language

_watched_root = None
_observer = None

async def resolve_callee_ids(db) -> None:
    """Resolve callee_id for any call_edges that have a matching symbol name."""
    await db.execute(
        "UPDATE call_edges "
        "SET callee_id = ( "
        "    SELECT id FROM symbols "
        "    WHERE symbols.name = call_edges.callee_name "
        "    LIMIT 1 "
        ") "
        "WHERE callee_id IS NULL"
    )


def get_file_metadata(path: Path) -> tuple[float, str]:
    """Return the modification time and MD5 hash of the file."""
    mtime = path.stat().st_mtime
    with open(path, "rb") as f:
        content = f.read()
    h = hashlib.md5(content).hexdigest()
    return mtime, h

import logging

logger = logging.getLogger("codeengine.index")


async def index_repo(root: str, on_progress=None) -> int:
    """
    Walk all files under root using pathlib.
    Compute mtime/hash and index any changed files into the database.

    Args:
        root: Repository root path.
        on_progress: Optional async callback(event_type: str, data: dict)
                     event_type: "start" | "file_indexed" | "file_skipped" | "done" | "error"
    """
    root_path = Path(root).resolve()
    indexed_count = 0
    skipped_count = 0
    error_count = 0

    supported_extensions = set(LANG_MAP.keys())
    skip_dirs = {
        # VCS
        ".git", ".svn", ".hg",
        # Node / JS / React
        "node_modules", ".next", ".nuxt", ".turbo", "coverage",
        # Python
        "__pycache__", ".venv", "venv", ".venv-mcp", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", ".tox", ".nox",
        # Java / JVM
        "target", "build", ".gradle", ".idea", "bin", "out",
        # Rust
        "target",
        # Go
        "vendor",
        # Python packaging
        "dist", ".eggs",
        # IDE / Editor
        ".vscode", ".vs", ".eclipse",
        # OS / General
        "tmp", "temp", "logs",
    }

    async def emit(event_type, data=None):
        if on_progress:
            try:
                await on_progress(event_type, data or {})
            except Exception:
                pass

    await emit("start", {"repo": str(root_path)})
    logger.info("Indexing started: %s", root_path)

    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")

        # Collect all candidate files first for progress tracking
        all_files = []
        for p in root_path.rglob("*"):
            try:
                if not p.is_file():
                    continue
            except Exception:
                continue
            try:
                rel_parts = p.relative_to(root_path).parts
                if any(part in skip_dirs for part in rel_parts):
                    continue
            except ValueError:
                continue
            if p.suffix.lower() not in supported_extensions:
                continue
            all_files.append(p)

        total = len(all_files)
        logger.info("Found %d candidate files to index", total)
        await emit("start", {"repo": str(root_path), "total": total})

        for idx, p in enumerate(all_files, 1):
            rel_path = ""
            try:
                try:
                    mtime, h = get_file_metadata(p)
                except Exception:
                    error_count += 1
                    continue

                rel_path = str(p.relative_to(root_path).as_posix())
                lang = detect_language(str(p)) or ""

                async with db.execute("SELECT id, hash FROM files WHERE path = ?", (rel_path,)) as cursor:
                    row = await cursor.fetchone()

                if row:
                    if row["hash"] == h:
                        skipped_count += 1
                        logger.info("[%d/%d] SKIP (unchanged): %s", idx, total, rel_path)
                        await emit("file_skipped", {"file": rel_path, "index": idx, "total": total})
                        continue
                    await db.execute("DELETE FROM files WHERE id = ?", (row["id"],))

                from codeengine.core.ast_engine import parse_file, extract_calls
                symbols = parse_file(str(p))

                cursor = await db.execute(
                    "INSERT INTO files (path, lang, mtime, hash) VALUES (?, ?, ?, ?)",
                    (rel_path, lang, mtime, h)
                )
                file_id = cursor.lastrowid

                inserted_symbols = []
                for sym in symbols:
                    sym_cursor = await db.execute(
                        "INSERT INTO symbols (file_id, name, kind, line_start, line_end) VALUES (?, ?, ?, ?, ?)",
                        (file_id, sym.name, sym.kind, sym.line_start, sym.line_end)
                    )
                    inserted_symbols.append({
                        "id": sym_cursor.lastrowid,
                        "name": sym.name,
                        "kind": sym.kind,
                        "line_start": sym.line_start,
                        "line_end": sym.line_end
                    })

                calls = extract_calls(str(p))
                for line, callee_name in calls:
                    enclosing = [
                        s for s in inserted_symbols
                        if s["line_start"] <= line <= s["line_end"]
                    ]
                    if enclosing:
                        enclosing.sort(key=lambda s: s["line_end"] - s["line_start"])
                        caller = enclosing[0]
                        await db.execute(
                            "INSERT INTO call_edges (caller_id, callee_name, callee_file) VALUES (?, ?, ?)",
                            (caller["id"], callee_name, rel_path)
                        )

                # Extract and store references
                from codeengine.core.ast_engine import extract_references
                symbol_names = {s["name"] for s in inserted_symbols}
                refs = extract_references(str(p), symbol_names)
                for ref_name, ref_line in refs:
                    # Find the symbol_id for this reference
                    ref_symbol = next((s for s in inserted_symbols if s["name"] == ref_name), None)
                    if ref_symbol:
                        await db.execute(
                            "INSERT INTO symbol_references (symbol_id, file_id, line) VALUES (?, ?, ?)",
                            (ref_symbol["id"], file_id, ref_line)
                        )

                # Extract and store docstrings
                from codeengine.core.ast_engine import extract_docstrings
                docstrings = extract_docstrings(str(p))
                for ds_name, ds_content, ds_line_start, ds_line_end in docstrings:
                    ds_symbol = next((s for s in inserted_symbols if s["name"] == ds_name), None)
                    if ds_symbol:
                        await db.execute(
                            "INSERT OR REPLACE INTO docstrings (symbol_id, content, line_start, line_end) VALUES (?, ?, ?, ?)",
                            (ds_symbol["id"], ds_content, ds_line_start, ds_line_end)
                        )

                # Extract and store imports
                from codeengine.core.ast_engine import extract_imports_structured
                imports = extract_imports_structured(str(p))
                for module, level, is_star in imports:
                    await db.execute(
                        "INSERT INTO imports (file_id, module, level, is_star) VALUES (?, ?, ?, ?)",
                        (file_id, module, level, is_star)
                    )

                indexed_count += 1
                sym_names = [s["name"] for s in inserted_symbols]
                logger.info("[%d/%d] INDEXED (%s, %d symbols): %s — %s",
                            idx, total, lang or "unknown", len(symbols), rel_path,
                            ", ".join(sym_names[:5]) + ("…" if len(sym_names) > 5 else ""))
                await emit("file_indexed", {
                    "file": rel_path, "lang": lang,
                    "symbols": len(symbols), "calls": len(calls),
                    "index": idx, "total": total
                })

            except Exception as exc:
                error_count += 1
                logger.error("[%d/%d] ERROR indexing %s: %s", idx, total, rel_path or p, exc)
                await emit("error", {"file": rel_path or str(p), "message": str(exc),
                                     "index": idx, "total": total})
                continue

        await resolve_callee_ids(db)
        await db.commit()

    summary = {"indexed": indexed_count, "skipped": skipped_count,
               "errors": error_count, "total": total, "repo": str(root_path)}
    logger.info("Indexing complete: %d indexed, %d skipped, %d errors (of %d files)",
                indexed_count, skipped_count, error_count, total)
    await emit("done", summary)
    return indexed_count

async def reindex_file(path: str) -> None:
    """Re-index a single file when it's created or modified."""
    global _watched_root
    p = Path(path).resolve()
    if not p.is_file():
        return
        
    if _watched_root:
        root_path = Path(_watched_root).resolve()
        try:
            rel_parts = p.relative_to(root_path).parts
            skip_dirs = {
                # VCS
                ".git", ".svn", ".hg",
                # Node / JS / React
                "node_modules", ".next", ".nuxt", ".turbo", "coverage",
                # Python
                "__pycache__", ".venv", "venv", ".venv-mcp", ".pytest_cache",
                ".mypy_cache", ".ruff_cache", ".tox", ".nox",
                # Java / JVM
                "target", "build", ".gradle", ".idea", "bin", "out",
                # Rust
                "target",
                # Go
                "vendor",
                # Python packaging
                "dist", ".eggs",
                # IDE / Editor
                ".vscode", ".vs", ".eclipse",
                # OS / General
                "tmp", "temp", "logs",
            }
            if any(part in skip_dirs for part in rel_parts):
                return
        except ValueError:
            return
    else:
        root_path = p.parent
        
    supported_extensions = set(LANG_MAP.keys())
    if p.suffix.lower() not in supported_extensions:
        return
        
    try:
        mtime, h = get_file_metadata(p)
    except Exception:
        return
        
    rel_path = str(p.relative_to(root_path).as_posix())
    lang = detect_language(str(p)) or ""
    
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        # CASCADE deletion of symbols happens automatically
        await db.execute("DELETE FROM files WHERE path = ?", (rel_path,))
        
        from codeengine.core.ast_engine import parse_file, extract_calls
        symbols = parse_file(str(p))
        
        cursor = await db.execute(
            "INSERT INTO files (path, lang, mtime, hash) VALUES (?, ?, ?, ?)",
            (rel_path, lang, mtime, h)
        )
        file_id = cursor.lastrowid
        
        inserted_symbols = []
        for sym in symbols:
            sym_cursor = await db.execute(
                "INSERT INTO symbols (file_id, name, kind, line_start, line_end) VALUES (?, ?, ?, ?, ?)",
                (file_id, sym.name, sym.kind, sym.line_start, sym.line_end)
            )
            inserted_symbols.append({
                "id": sym_cursor.lastrowid,
                "name": sym.name,
                "kind": sym.kind,
                "line_start": sym.line_start,
                "line_end": sym.line_end
            })
            
        calls = extract_calls(str(p))
        for line, callee_name in calls:
            enclosing = [
                s for s in inserted_symbols
                if s["line_start"] <= line <= s["line_end"]
            ]
            if enclosing:
                enclosing.sort(key=lambda s: s["line_end"] - s["line_start"])
                caller = enclosing[0]
                await db.execute(
                    "INSERT INTO call_edges (caller_id, callee_name, callee_file) VALUES (?, ?, ?)",
                    (caller["id"], callee_name, rel_path)
                )

        # Extract and store references
        from codeengine.core.ast_engine import extract_references
        symbol_names = {s["name"] for s in inserted_symbols}
        refs = extract_references(str(p), symbol_names)
        for ref_name, ref_line in refs:
            ref_symbol = next((s for s in inserted_symbols if s["name"] == ref_name), None)
            if ref_symbol:
                await db.execute(
                    "INSERT INTO symbol_references (symbol_id, file_id, line) VALUES (?, ?, ?)",
                    (ref_symbol["id"], file_id, ref_line)
                )

        # Extract and store docstrings
        from codeengine.core.ast_engine import extract_docstrings
        docstrings = extract_docstrings(str(p))
        for ds_name, ds_content, ds_line_start, ds_line_end in docstrings:
            ds_symbol = next((s for s in inserted_symbols if s["name"] == ds_name), None)
            if ds_symbol:
                await db.execute(
                    "INSERT OR REPLACE INTO docstrings (symbol_id, content, line_start, line_end) VALUES (?, ?, ?, ?)",
                    (ds_symbol["id"], ds_content, ds_line_start, ds_line_end)
                )

        # Extract and store imports
        from codeengine.core.ast_engine import extract_imports_structured
        imports = extract_imports_structured(str(p))
        for module, level, is_star in imports:
            await db.execute(
                "INSERT INTO imports (file_id, module, level, is_star) VALUES (?, ?, ?, ?)",
                (file_id, module, level, is_star)
            )

        await resolve_callee_ids(db)
        await db.commit()

class IndexHandler(FileSystemEventHandler):
    """Event handler for filesystem modification events."""
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        
    def on_modified(self, event):
        if not event.is_directory:
            asyncio.run_coroutine_threadsafe(reindex_file(event.src_path), self.loop)
            
    def on_created(self, event):
        if not event.is_directory:
            asyncio.run_coroutine_threadsafe(reindex_file(event.src_path), self.loop)

async def clear_index() -> None:
    """Wipe all files and symbols from the DB."""
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("DELETE FROM files")  # CASCADE deletes symbols
        await db.commit()

def stop_watcher() -> None:
    """Stop the active watchdog observer."""
    global _observer
    if _observer and _observer.is_alive():
        try:
            _observer.stop()
            _observer.join()
        except Exception:
            pass
        _observer = None

def start_watcher(root: str) -> None:
    """Start the watchdog observer on a background thread."""
    global _watched_root, _observer
    
    stop_watcher()
    _watched_root = root
    
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
        
    event_handler = IndexHandler(loop)
    observer = Observer()
    observer.schedule(event_handler, path=root, recursive=True)
    observer.daemon = True
    observer.start()
    _observer = observer
