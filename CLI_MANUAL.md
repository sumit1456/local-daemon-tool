# Code Search Engine — CLI Manual

> **For AI agents** that cannot use MCP tools directly.
> Call these via `bash` / PowerShell `run_command`..

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
| `index` | `[--files a.py b.py]` | File + symbol index. No filters = compact summary. |
| `overview` | `[--files a.py b.py]` | Full overview with call graph. |

### Dependency Intelligence

| Command | Args | Description |
|:--------|:-----|:------------|
| `callers` | `"symbol_name"` | Who calls this function? |
| `callees` | `"symbol_name"` | What does this function call? |

### Type & Symbol Intelligence

| Command | Args | Description |
|:--------|:-----|:------------|

### Impact Analysis & Tracing

| Command | Args | Description |
|:--------|:-----|:------------|

### Editing

| Command | Args | Description |
|:--------|:-----|:------------|
| `preview-smart` | `"file.py" "new_code"` | Smart edit — engine detects what to replace |
| `apply-smart` | `"edit_id"` | Apply smart edit + git commit |

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

# Check what calls search_code
.venv\Scripts\python.exe ce_cli.py callers search_code

# Check what search_code calls
.venv\Scripts\python.exe ce_cli.py callees search_code

# Preview a smart edit
.venv\Scripts\python.exe ce_cli.py preview-smart "codeengine/app.py" "new code here"

# Apply the edit
.venv\Scripts\python.exe ce_cli.py apply-smart "edit_id_here"

# Detect code snippet origin
.venv\Scripts\python.exe ce_cli.py detect "def search_code(query: str):"

# Parse code into blocks
.venv\Scripts\python.exe ce_cli.py parse-blocks "def hello(): pass"
```

---

## Workflow: Safe Code Modification

```powershell
# 1. Find the function
.venv\Scripts\python.exe ce_cli.py symbol process_payment --kind function

# 2. Extract the function
.venv\Scripts\python.exe ce_cli.py function "gateways/stripe.py" process_payment

# 3. Preview the smart edit
.venv\Scripts\python.exe ce_cli.py preview-smart "gateways/stripe.py" "new code here"

# 4. Apply (auto git commit)
.venv\Scripts\python.exe ce_cli.py apply-smart "edit_id"
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
WARNING: SLOWER THAN NATIVE TOOLS
The following CLI commands go through HTTP → FastAPI → ripgrep/AST.
Use native tools first when possible — they are faster and cheaper.

| CLI Command | Native Alternative | Why Native Is Better |
|:------------|:-------------------|:---------------------|
| `search "pattern"` | `grep_search` / `rg` | ~200 tokens vs ~500+ via CLI |
| `file "pattern"` | `glob` / `fd` | ~50 tokens vs ~100+ via CLI |
| `symbol "name"` | `grep` for `def/class` | Faster for simple lookups |

**Rule of thumb**: If `grep` or `glob` can do it, use native. Only use CLI
when you need AST-level precision (`function`, `class`, `signature`, `body`)
or editing capabilities (`preview-smart`, `apply-smart`).
======================================================================
