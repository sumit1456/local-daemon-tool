# Code Search Engine — Agent Instruction Manual

> **Audience**: AI agents (Antigravity, Claude, GPT, Gemini, etc.) operating in a
> local coding environment on Windows.
>
> **CRITICAL PERFORMANCE RULE (Token Budget)**: 
> * **DO NOT** use `ce_cli.py search` for broad queries (e.g. searching "bbox" or common variables). It returns raw JSON matches which consume 10x-15x more tokens than your platform's native `grep_search` tool.
> * **DO** use `ce_cli.py` for target AST extraction (`function` or `class`) and safe editing (`preview`/`apply`/`undo`).

---

## 1. Tool Selection Strategy (The Hybrid Approach)

To maximize token efficiency, divide your search and retrieval tasks as follows:

| Task | Best Tool | Token Cost | Why? |
| :--- | :--- | :--- | :--- |
| **Broad Keyword Search** | Native `grep_search` | 🟢 Very Low (~200 tokens) | Native tool summarizes matches compactly. |
| **List Files by Pattern** | Native file finder | 🟢 Very Low | Fast, built-in directory navigation. |
| **Read a Specific Function** | `ce_cli.py function` | 🟢 Very Low (~50 tokens) | **AST extraction** returns only the function body (saves reading the whole file). |
| **Read a Specific Class** | `ce_cli.py class` | 🟢 Low (~150 tokens) | AST extraction returns only the class block. |
| **Propose / Apply Edits** | `ce_cli.py preview`/`apply` | 🟡 Medium | Standardized diffs and automatic Git commits. |

---

## 2. Accessing the Daemon via `run_command`

The local daemon runs on `http://127.0.0.1:8000`. Because `read_url_content` blocks localhost domains, you must call the CLI bridge via terminal commands.

### Base Command Prefix
```powershell
# Run from C:\Users\SUMIT\Downloads\dev-tool\local-daemon-tool
.venv\Scripts\python.exe ce_cli.py <command> [args]
```

### Health Check (Ping)
```powershell
.venv\Scripts\python.exe ce_cli.py ping
# Returns: { "status": "ok", "url": "http://127.0.0.1:8000" }
```

---

## 3. High-Value Command Reference (AST & Edits)

### 3.1 `function` — Extract Function Source (AST)
Retrieves the exact body of a single function using tree-sitter. Use this instead of reading the entire file.

```powershell
.venv\Scripts\python.exe ce_cli.py function "relative/path/to/file.py" "FunctionName"
```
**Response:**
```json
{
  "name": "apply_edit",
  "file": "codeengine/core/edit_engine.py",
  "line_start": 79,
  "line_end": 123,
  "source": "async def apply_edit(edit_id: str) -> ApplyResult:\n    ..."
}
```

### 3.2 `class` — Extract Class Source (AST)
Retrieves the exact body of a class block.

```powershell
.venv\Scripts\python.exe ce_cli.py class "relative/path/to/file.py" "ClassName"
```

---

### 3.3 `preview` — Stage an Edit (Diff)
Always call this before modifying files. It checks if the `old_code` matches the file contents verbatim and outputs a unified diff.

```powershell
.venv\Scripts\python.exe ce_cli.py preview "file.py" "old_code_block" "new_code_block"
```
**Response:**
```json
{
  "edit_id": "01J3XY...",
  "file": "codeengine/app.py",
  "diff": "--- codeengine/app.py\n+++ codeengine/app.py\n@@...",
  "lines_changed": 2
}
```

### 3.4 `apply` — Write to Disk & Commit
Writes the staged edit to the file and automatically creates a git commit (`edit: <edit_id>`).

```powershell
.venv\Scripts\python.exe ce_cli.py apply "EDIT_ID_FROM_PREVIEW"
```

### 3.5 `undo` — Revert Last Edit
Runs `git revert HEAD` to immediately undo the last applied change.

```powershell
.venv\Scripts\python.exe ce_cli.py undo
```

---

## 4. Workflows

### Workflow A: Read a targeted method
1. Search the codebase using your native `grep_search` to find where the method or file is defined.
2. Read *only* that method using `ce_cli.py function` to save tokens.
   ```powershell
   .venv\Scripts\python.exe ce_cli.py function "src/components/PDFEditor/PDFRenderer.jsx" "LineRenderer"
   ```

### Workflow B: Safe Code Modifications
1. Read the method using `ce_cli.py function`.
2. Generate the edit preview:
   ```powershell
   .venv\Scripts\python.exe ce_cli.py preview "src/components/PDFEditor/PDFRenderer.jsx" "old code block" "new code block"
   ```
3. Verify the diff, then apply:
   ```powershell
   .venv\Scripts\python.exe ce_cli.py apply "EDIT_ID"
   ```
4. If tests fail, run:
   ```powershell
   .venv\Scripts\python.exe ce_cli.py undo
   ```

---

## 5. Quick Reference Card

```
Cwd for commands: C:\Users\SUMIT\Downloads\dev-tool\local-daemon-tool
Prefix:           .venv\Scripts\python.exe ce_cli.py

ping                                      → Check if local server is online
function "file" "name"                    → AST extract function (cheap read)
class    "file" "name"                    → AST extract class (cheap read)
preview  "file" "old" "new"               → Stage edit & get EDIT_ID
apply    "EDIT_ID"                        → Write edit to disk & git commit
undo                                      → Revert last edit (git revert HEAD)
```

---
*Code Search Engine v1.0.0 — Updated for Token-Efficiency*
