import aiosqlite
from pathlib import Path
from contextlib import asynccontextmanager

DB_PATH = Path("data/index.db")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

async def _migrate_db(db) -> None:
    """Apply schema migrations to existing databases."""
    db.row_factory = aiosqlite.Row
    # Check which columns exist on call_edges
    async with db.execute("PRAGMA table_info(call_edges)") as cursor:
        cols = {row["name"] for row in await cursor.fetchall()}
    db.row_factory = None

    if "callee_file" not in cols:
        await db.execute("ALTER TABLE call_edges ADD COLUMN callee_file TEXT")
        # Backfill callee_file from resolved callee symbols
        await db.execute(
            "UPDATE call_edges SET callee_file = "
            "  (SELECT f.path FROM symbols s JOIN files f ON s.file_id = f.id "
            "   WHERE s.id = call_edges.callee_id) "
            "WHERE callee_id IS NOT NULL AND callee_file IS NULL"
        )

    # Ensure new tables exist (in case schema.sql wasn't re-run)
    await db.execute(
        "CREATE TABLE IF NOT EXISTS symbol_references ("
        "  symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,"
        "  file_id   INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,"
        "  line      INTEGER NOT NULL"
        ")"
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_references_symbol ON symbol_references(symbol_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_references_file ON symbol_references(file_id)")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS docstrings ("
        "  symbol_id  INTEGER PRIMARY KEY REFERENCES symbols(id) ON DELETE CASCADE,"
        "  content    TEXT NOT NULL,"
        "  line_start INTEGER NOT NULL,"
        "  line_end   INTEGER NOT NULL"
        ")")


async def init_db() -> None:
    """Create database and all tables from schema.sql."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = f.read()
        await db.executescript(schema)
        await _migrate_db(db)
        await db.commit()

@asynccontextmanager
async def get_db():
    """Yield an aiosqlite connection with row_factory set."""
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        db.row_factory = aiosqlite.Row
        # Enable WAL mode for better concurrent access
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        yield db
