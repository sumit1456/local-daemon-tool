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
    callee_file TEXT,
    callee_id   INTEGER REFERENCES symbols(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_call_edges_caller ON call_edges(caller_id);
CREATE INDEX IF NOT EXISTS idx_call_edges_callee ON call_edges(callee_id);

CREATE TABLE IF NOT EXISTS symbol_references (
    symbol_id   INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    line        INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_references_symbol ON symbol_references(symbol_id);
CREATE INDEX IF NOT EXISTS idx_references_file ON symbol_references(file_id);

CREATE TABLE IF NOT EXISTS docstrings (
    symbol_id   INTEGER PRIMARY KEY REFERENCES symbols(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    line_start  INTEGER NOT NULL,
    line_end    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS imports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    module      TEXT    NOT NULL,
    level       INTEGER DEFAULT 0,
    is_star     INTEGER DEFAULT 0,
    UNIQUE(file_id, module) ON CONFLICT REPLACE
);

CREATE INDEX IF NOT EXISTS idx_imports_file ON imports(file_id);
CREATE INDEX IF NOT EXISTS idx_imports_module ON imports(module);

CREATE TABLE IF NOT EXISTS type_hints (
    symbol_id   INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    param_name  TEXT,
    annotation  TEXT NOT NULL,
    is_return   INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_type_hints_symbol ON type_hints(symbol_id);

CREATE TABLE IF NOT EXISTS class_bases (
    class_id    INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    base_name   TEXT    NOT NULL,
    base_file   TEXT
);

CREATE INDEX IF NOT EXISTS idx_class_bases_class ON class_bases(class_id);
CREATE INDEX IF NOT EXISTS idx_class_bases_base ON class_bases(base_name);

