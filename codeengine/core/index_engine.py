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

async def index_repo(root: str) -> int:
    """
    Walk all files under root using pathlib.
    Compute mtime/hash and index any changed files into the database.
    """
    root_path = Path(root).resolve()
    indexed_count = 0
    
    supported_extensions = set(LANG_MAP.keys())
    skip_dirs = {".git", "node_modules", "__pycache__", "vendor", "target"}
    
    async with get_db() as db:
        # Enforce foreign key constraints
        await db.execute("PRAGMA foreign_keys = ON")
        
        for p in root_path.rglob("*"):
            try:
                if not p.is_file():
                    continue
            except Exception:
                continue
                
            # Check skip directories
            try:
                rel_parts = p.relative_to(root_path).parts
                if any(part in skip_dirs for part in rel_parts):
                    continue
            except ValueError:
                continue
                
            if p.suffix.lower() not in supported_extensions:
                continue
                
            try:
                mtime, h = get_file_metadata(p)
            except Exception:
                continue
                
            rel_path = str(p.relative_to(root_path).as_posix())
            lang = detect_language(str(p)) or ""
            
            # Check if file is unchanged
            async with db.execute("SELECT id, hash FROM files WHERE path = ?", (rel_path,)) as cursor:
                row = await cursor.fetchone()
                
            if row:
                if row["hash"] == h:
                    continue
                # If hash changed, delete old file to trigger CASCADE delete of old symbols
                await db.execute("DELETE FROM files WHERE id = ?", (row["id"],))
                
            # Index the file
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
                        "INSERT INTO call_edges (caller_id, callee_name) VALUES (?, ?)",
                        (caller["id"], callee_name)
                    )
            indexed_count += 1
            
        await resolve_callee_ids(db)
        await db.commit()
        
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
            skip_dirs = {".git", "node_modules", "__pycache__", "vendor", "target"}
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
                    "INSERT INTO call_edges (caller_id, callee_name) VALUES (?, ?)",
                    (caller["id"], callee_name)
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
