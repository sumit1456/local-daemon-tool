import aiosqlite
from pathlib import Path
from contextlib import asynccontextmanager

DB_PATH = Path("data/index.db")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

async def init_db() -> None:
    """Create database and all tables from schema.sql."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = f.read()
        await db.executescript(schema)
        await db.commit()

@asynccontextmanager
async def get_db():
    """Yield an aiosqlite connection with row_factory set."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db
