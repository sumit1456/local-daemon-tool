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

CREATE TABLE IF NOT EXISTS embeddings (
    symbol_id   INTEGER PRIMARY KEY REFERENCES symbols(id) ON DELETE CASCADE,
    embedding   BLOB NOT NULL,  -- float32 vector (384 dims)
    model       TEXT NOT NULL DEFAULT 'BAAI/bge-small-en-v1.5',
    created_at  REAL NOT NULL
);

-- Precomputed transitive closure of the call graph.
-- For every symbol S, stores ALL symbols that transitively call S.
-- Rebuilt automatically after every /reindex.
CREATE TABLE IF NOT EXISTS transitive_callers (
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    caller_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    depth           INTEGER NOT NULL,   -- 1 = direct, 2 = grandparent, etc.
    PRIMARY KEY (symbol_id, caller_id)
);

CREATE INDEX IF NOT EXISTS idx_tc_symbol ON transitive_callers(symbol_id);
CREATE INDEX IF NOT EXISTS idx_tc_caller ON transitive_callers(caller_id);

-- Precomputed git change history per symbol.
-- Populated by POST /git-index and updated incrementally.
CREATE TABLE IF NOT EXISTS git_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id   INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
    file_path   TEXT NOT NULL,
    commit_hash TEXT NOT NULL,
    commit_date TEXT NOT NULL,       -- ISO-8601 string
    commit_msg  TEXT NOT NULL,
    change_type TEXT NOT NULL,       -- 'signature_change' | 'logic_edit' | 'new' | 'deleted'
    lines_added INTEGER DEFAULT 0,
    lines_removed INTEGER DEFAULT 0,
    UNIQUE(symbol_id, commit_hash)
);

CREATE INDEX IF NOT EXISTS idx_git_history_symbol ON git_history(symbol_id);
CREATE INDEX IF NOT EXISTS idx_git_history_file   ON git_history(file_path);
CREATE INDEX IF NOT EXISTS idx_git_history_date   ON git_history(commit_date DESC);

-- Tracks the state of sandbox containers per stack.
-- One row per stack (python, node, java, go, rust).
CREATE TABLE IF NOT EXISTS sandbox_state (
    stack           TEXT    PRIMARY KEY,   -- 'python' | 'node' | 'java' | 'go' | 'rust'
    container_id    TEXT,                  -- Docker container ID (null if not running)
    image           TEXT    NOT NULL,      -- Docker image used
    deps_installed  INTEGER DEFAULT 0,     -- 0 = pending, 1 = done
    created_at      REAL,
    last_used_at    REAL
);


