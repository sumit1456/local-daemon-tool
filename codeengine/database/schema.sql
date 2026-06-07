CREATE TABLE IF NOT EXISTS files (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    path    TEXT    NOT NULL UNIQUE,
    lang    TEXT    NOT NULL,
    mtime   REAL    NOT NULL,
    hash    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    kind        TEXT    NOT NULL CHECK(kind IN ('function','class','method','interface')),
    line_start  INTEGER NOT NULL,
    line_end    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS edits (
    id          TEXT    PRIMARY KEY,   -- ULID
    file_path   TEXT    NOT NULL,
    old_code    TEXT    NOT NULL,
    new_code    TEXT    NOT NULL,
    diff        TEXT    NOT NULL,
    applied     INTEGER NOT NULL DEFAULT 0,  -- 0=pending, 1=applied
    created_at  REAL    NOT NULL,
    applied_at  REAL
);

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);

CREATE TABLE IF NOT EXISTS call_edges (
    caller_id   INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    callee_name TEXT NOT NULL,
    callee_id   INTEGER REFERENCES symbols(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_call_edges_caller ON call_edges(caller_id);
CREATE INDEX IF NOT EXISTS idx_call_edges_callee ON call_edges(callee_id);

