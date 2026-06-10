# Code Search Engine — CLI Manual

> **For AI agents** that cannot use MCP tools directly.
> Call these via `bash` / PowerShell `run_command`.

---

## Setup

```powershell
# From local-daemon-tool directory
$CLI = ".venv\Scripts\python.exe ce_cli.py"
```

Daemon must be running:
```powershell
.venv\Scripts\pythonw.exe launcher.pyw
```

---

## Command Reference

### Utility

| Command | Args | Description |
|:--------|:-----|:------------|
| `ping` | — | Check if daemon is online |

### Code Search

| Command | Args | Description |
|:--------|:-----|:------------|
| `search` | `"query"` `[--path .]` `[--lang python]` `[--limit 50]` | Ripgrep search |
| `symbol` | `"name"` `[--kind function]` `[--dir src]` `[--package codeengine.core]` | AST symbol lookup |
| `file` | `"pattern"` `[--root .]` | Find files by name pattern |

### AST Extraction

| Command | Args | Description |
|:--------|:-----|:------------|
| `function` | `"file.py" "FuncName"` | Extract single function body |
| `class` | `"file.py" "ClassName"` | Extract single class block |
| `signature` | `"file.py" 42 89` | Signature + docstring only (cheapest) |
| `body` | `"file.py" 42 89` | Full function body by line range |

### Code Intelligence

| Command | Args | Description |
|:--------|:-----|:------------|
| `index` | `[--files a.py b.py]` `[--dir src]` `[--package codeengine.core]` | File + symbol index |
| `overview` | `[--files a.py b.py]` `[--dir src]` `[--package codeengine.core]` | Full overview with call graph |
| `callers` | `"symbol_name"` `[--dir src]` `[--package codeengine.core]` | Who calls this function? |
| `callees` | `"symbol_name"` `[--dir src]` `[--package codeengine.core]` | What does this function call? |

### Dependency Intelligence

| Command | Args | Description |
|:--------|:-----|:------------|
| `imports` | `"file.py"` | All imports used by a file |
| `importers` | `"module.name"` | Reverse dependency — who imports this |
| `file-deps` | `"file.py"` | Full dependency picture (both directions) |

### Type & Symbol Intelligence

| Command | Args | Description |
|:--------|:-----|:------------|
| `type-info` | `"symbol_name"` `[--file x.py]` | Parameter types and return type |
| `defined-symbols` | `"file.py"` | What's defined in a file |
| `count-refs` | `"symbol_name"` | How many times is this symbol used? |

### Impact Analysis & Tracing

| Command | Args | Description |
|:--------|:-----|:------------|
| `impact` | `"symbol_name"` | Full impact — callers, references, affected files |
| `trace` | `"symbol_name"` `[--depth 5]` | Trace call chain through the application |

### Editing

| Command | Args | Description |
|:--------|:-----|:------------|
| `edit-context` | `"symbol"` `[--file x.py]` `[--dir src]` `[--package codeengine.core]` | Get all context needed to edit a symbol |
| `preview` | `"file.py" "old_code" "new_code"` | Preview edit as diff (no disk write) |
| `apply` | `"edit_id"` | Apply previewed edit + git commit |
| `preview-smart` | `"file.py" "new_code"` | Smart edit — engine detects what to replace |
| `apply-smart` | `"edit_id"` | Apply smart edit + git commit |
| `undo` | — | Revert last edit (`git revert HEAD`) |

### Code Analysis

| Command | Args | Description |
|:--------|:-----|:------------|
| `detect` | `"code_snippet"` `[--file_hint x.py]` `[--lang_hint python]` | Locate a code snippet's origin |
| `parse-blocks` | `"code_snippet"` `[--file_hint x.py]` `[--lang_hint python]` | Parse code into structural blocks |

---

## Examples

```powershell
# Check daemon
.venv\Scripts\python.exe ce_cli.py ping

# Find a function
.venv\Scripts\python.exe ce_cli.py symbol search_code --kind function

# Extract function source
.venv\Scripts\python.exe ce_cli.py function "codeengine/core/search_engine.py" search_code

# Get edit context for a symbol
.venv\Scripts\python.exe ce_cli.py edit-context search_code --package codeengine.core

# Check what calls search_code
.venv\Scripts\python.exe ce_cli.py callers search_code

# Get full impact before refactoring
.venv\Scripts\python.exe ce_cli.py impact search_code

# Preview an edit
.venv\Scripts\python.exe ce_cli.py preview "codeengine/app.py" "old code" "new code"

# Apply the edit
.venv\Scripts\python.exe ce_cli.py apply "edit_id_here"

# Undo if tests fail
.venv\Scripts\python.exe ce_cli.py undo

# Get file dependencies
.venv\Scripts\python.exe ce_cli.py file-deps "codeengine/core/search_engine.py"

# Count references
.venv\Scripts\python.exe ce_cli.py count-refs search_code

# Trace execution flow
.venv\Scripts\python.exe ce_cli.py trace search_code --depth 3
```

---

## Workflow: Safe Code Modification

```powershell
# 1. Get context for the symbol
.venv\Scripts\python.exe ce_cli.py edit-context "process_payment" --package gateways

# 2. Preview the edit
.venv\Scripts\python.exe ce_cli.py preview "gateways/stripe.py" "old code" "new code"

# 3. Apply (auto git commit)
.venv\Scripts\python.exe ce_cli.py apply "edit_id"

# 4. If tests fail, undo
.venv\Scripts\python.exe ce_cli.py undo
```

---

## Output Format

All commands return JSON to stdout. Errors go to stderr as JSON:
```json
{"error": "Description of what went wrong"}
```

---

*Code Search Engine CLI v2.0.0*

======================================================================
⚠ WARNING: SLOWER THAN NATIVE TOOLS
The following CLI commands go through HTTP → FastAPI → ripgrep/AST.
Use native tools first when possible — they are faster and cheaper.

| CLI Command | Native Alternative | Why Native Is Better |
|:------------|:-------------------|:---------------------|
| `search "pattern"` | `grep_search` / `rg` | ~200 tokens vs ~500+ via CLI |
| `file "pattern"` | `glob` / `fd` | ~50 tokens vs ~100+ via CLI |
| `symbol "name"` | `grep` for `def/class` | Faster for simple lookups |

**Rule of thumb**: If `grep` or `glob` can do it, use native. Only use CLI
when you need AST-level precision (`function`, `class`, `signature`, `body`)
or editing capabilities (`preview`, `apply`, `undo`, `edit-context`).
======================================================================
