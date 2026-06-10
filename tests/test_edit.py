"""
test_edit.py — Stress tests for MCP edit engine.
Contains intentionally tricky Python code patterns that are hard to edit.
"""

import asyncio
import json
from functools import wraps
from typing import Optional, Callable


# ── 1. Multiline string with indentation-sensitive content ──────────────────
SQL_QUERY = """
SELECT
    u.id,
    u.name,
    COUNT(o.id) AS order_count,
    SUM(o.total) AS total_spent
FROM users u
LEFT JOIN orders o ON o.user_id = u.id
WHERE u.active = true
    AND u.created_at >= '2024-01-01'
GROUP BY u.id, u.name
HAVING COUNT(o.id) > 5
ORDER BY total_spent DESC
LIMIT 100;
""".strip()


# ── 2. Nested f-strings with braces ────────────────────────────────────────
def format_user_card(name: str, age: int, meta: dict) -> str:
    return f"""User Card
{'=' * 40}
Name: {name}
Age:  {age}
Meta: {json.dumps(meta, indent=2)}
{'=' * 40}
Active: {meta.get('active', False)!r}"""


# ── 3. Decorator with wrapper that has similar variable names ──────────────
def retry(max_attempts: int = 5, delay: float = 2.0):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            attempt = 0
            last_error = None
            while attempt < max_attempts:
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    attempt += 1
                    last_error = e
                    if attempt < max_attempts:
                        await asyncio.sleep(delay * attempt)
            raise last_error
        return wrapper
    return decorator


# ── 4. Deeply nested comprehension with same variable name reused ──────────
def build_matrix(n: int) -> list[list[int]]:
    return [[i * j + (i - j) for j in range(n)] for i in range(n)]


def flatten_with_condition(matrix: list[list[int]], threshold: int) -> list[int]:
    return [val for row in matrix for val in row if val > threshold]


# ── 5. Class with __init__ that has duplicate patterns ─────────────────────
class ConnectionPool:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "default",
        user: str = "admin",
        password: str = "",
        max_connections: int = 10,
        timeout: float = 30.0,
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.max_connections = max_connections
        self.timeout = timeout
        self._pool: list = []
        self._active: int = 0

    async def acquire(self) -> dict:
        if self._active >= self.max_connections:
            raise RuntimeError("Pool exhausted")
        conn = {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
        }
        self._active += 1
        return conn

    async def release(self, conn: dict) -> None:
        self._active -= 1
        conn.clear()


# ── 6. Tricky string with backslashes and escapes ──────────────────────────
REGEX_PATTERNS = {
    "email": r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
    "phone": r"^\+?1?\d{9,15}$",
    "url": r"^https?://(?:www\.)?[\w-]+(?:\.[\w-]+)+[\w.,@?^=%&:/~+#-]*$",
    "ipv4": r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$",
}


# ── 7. Async generator with complex control flow ──────────────────────────
async def stream_processor(chunks: list[str], *, skip_empty: bool = True):
    buffer = ""
    line_count = 0
    for chunk in chunks:
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            if skip_empty and not line.strip():
                continue
            line_count += 1
            processed = line.strip().upper()
            if processed.startswith("ERROR"):
                yield {"type": "error", "line": line_count, "text": processed}
            elif processed.startswith("WARN"):
                yield {"type": "warning", "line": line_count, "text": processed}
            else:
                yield {"type": "info", "line": line_count, "text": processed}
    if buffer.strip():
        yield {"type": "info", "line": line_count + 1, "text": buffer.strip().upper()}


# ── 8. Lambda chain and higher-order function with same param names ────────
transform = lambda x: lambda y: lambda z: x + y + z
apply_all = lambda funcs, val: reduce(lambda v, f: f(v), funcs, val)


# ── 9. Context manager with yield and complex cleanup ─────────────────────
class Transaction:
    def __init__(self, connection):
        self.connection = connection
        self.changes: list = []
        self._committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None or not self._committed:
            self.rollback()
        return False

    def record(self, operation: str, data: dict) -> None:
        self.changes.append({"op": operation, "data": data})

    def commit(self) -> None:
        for change in self.changes:
            self.connection.execute(change["op"], change["data"])
        self._committed = True
        self.changes.clear()

    def rollback(self) -> None:
        self.changes.clear()


# ── 10. Module-level code with tricky indentation ──────────────────────────
CONFIG = {
    "debug": True,
    "log_level": "INFO",
    "services": {
        "auth": {"enabled": True, "timeout": 5},
        "payment": {"enabled": True, "timeout": 30},
        "notification": {"enabled": False, "timeout": 10},
    },
}

ACTIVE_SERVICES = [
    name
    for name, cfg in CONFIG["services"].items()
    if cfg.get("enabled", False)
]
