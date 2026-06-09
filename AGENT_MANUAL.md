# Code Search Engine — Agent Instruction Manual

> **Audience**: AI agents (Antigravity, Claude, GPT, Gemini, etc.) operating in a
> local coding environment on Windows.
>
> **CRITICAL PERFORMANCE RULE (Token Budget)**:
> * **DO NOT** use `search_code` (or `ce_cli.py search`) for broad queries (e.g. searching "bbox" or common variables). It returns raw JSON matches which consume 10x-15x more tokens than your platform's native `grep_search` tool.
> * **DO** use the MCP tools / `ce_cli.py` for target AST extraction (`extract_function`, `extract_class`) and safe editing (`preview_edit`/`apply_edit`/`undo_edit`).

---

## 1. Connecting via MCP (Recommended)

The Code Search Engine now exposes all tools as a native **MCP (Model Context Protocol) server**. This is the preferred method for agents that support MCP — no shell commands needed, tools are discovered automatically.

### Setup for Claude Desktop

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "CodeSearchEngine": {
      "command": "C:\\Users\\SUMIT\\Downloads\\dev-tool\\local-daemon-tool\\.venv-mcp\\Scripts\\python.exe",
      "args": ["C:\\Users\\SUMIT\\Downloads\\dev-tool\\local-daemon-tool\\mcp_server.py"]
    }
  }
}
```

### Setup for other agents (generic stdio MCP)

```
Command: .venv-mcp\Scripts\python.exe mcp_server.py
Cwd:     C:\Users\SUMIT\Downloads\dev-tool\local-daemon-tool
Transport: stdio
```

> **Note**: The local daemon must be running at `http://127.0.0.1:8000` first.
> Start it with: `.venv\Scripts\pythonw.exe launcher.pyw`

---

## 2. Tool Selection Strategy (The Hybrid Approach)

To maximize token efficiency, divide your search and retrieval tasks as follows:

| Task | Best Tool | Token Cost | Why? |
| :--- | :--- | :--- | :--- |
| **Broad Keyword Search** | Native `grep_search` | 🟢 Very Low (~200 tokens) | Native tool summarizes matches compactly. |
| **List Files by Pattern** | Native file finder | 🟢 Very Low | Fast, built-in directory navigation. |
| **Read a Specific Function** | MCP `extract_function` | 🟢 Very Low (~50 tokens) | **AST extraction** returns only the function body. |
| **Read a Specific Class** | MCP `extract_class` | 🟢 Low (~150 tokens) | AST extraction returns only the class block. |
| **Propose / Apply Edits** | MCP `preview_edit`/`apply_edit` | 🟡 Medium | Standardized diffs and automatic Git commits. |

---

## 3. MCP Tool Reference

### Utility
| Tool | Description |
| :--- | :--- |
| `ping` | Check if the daemon is online. |

### Code Search
| Tool | Description |
| :--- | :--- |
| `search_code(query, path, lang, limit)` | Ripgrep search. Use sparingly (token-heavy). |
| `search_symbol(name, kind)` | Find function/class definitions by name in the AST index. |
| `find_file(pattern, root)` | Find files by name pattern. |

### AST Extraction (Preferred for reading code)
| Tool | Description |
| :--- | :--- |
| `extract_function(file, name)` | Extract a single function body via tree-sitter. |
| `extract_class(file, name)` | Extract a single class block via tree-sitter. |
| `get_signature(file, line_start, line_end)` | Get only signature + docstring (cheapest). |
| `get_body(file, line_start, line_end)` | Get full function body by line range. |

### Code Intelligence
| Tool | Description |
| :--- | :--- |
| `get_index(files?)` | Get file + symbol index for the repo. |
| `get_overview(files?)` | Full repo overview with call graph. |
| `get_callers(symbol_name)` | Who calls this function? |
| `get_callees(symbol_name)` | What does this function call? |

### Editing (Always preview before applying)
| Tool | Description |
| :--- | :--- |
| `preview_edit(file, old_code, new_code)` | Stage an edit, returns a diff + edit_id. |
| `apply_edit(edit_id)` | Write the edit to disk + auto git commit. |
| `preview_smart_edit(file, new_code)` | Smart edit — engine detects what to replace. |
| `apply_smart_edit(edit_id)` | Apply a smart edit to disk + auto git commit. |
| `undo_edit()` | Revert last edit (`git revert HEAD`). |

### Code Analysis
| Tool | Description |
| :--- | :--- |
| `detect_snippet(code, file_hint?, lang_hint?)` | Locate a code snippet's origin in the codebase. |
| `parse_blocks(code, file_hint?, lang_hint?)` | Parse code into top-level structural blocks. |

---

## 4. Fallback: CLI via `run_command` (for agents without MCP support)

If your agent cannot use MCP, fall back to the CLI bridge.

### Base Command Prefix
```powershell
# Run from C:\Users\SUMIT\Downloads\dev-tool\local-daemon-tool
.venv\Scripts\python.exe ce_cli.py <command> [args]
```

### Quick Reference Card
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

## 5. Workflows

### Workflow A: Read a targeted method
1. Search the codebase using your native `grep_search` to find where the method is defined.
2. Read *only* that method using `extract_function` (MCP) or `ce_cli.py function` (CLI).

### Workflow B: Safe Code Modifications
1. Read the method using `extract_function`.
2. Generate the edit preview using `preview_edit`.
3. Verify the diff, then apply using `apply_edit`.
4. If tests fail, immediately call `undo_edit`.

---
*Code Search Engine v2.0.0 — MCP Server + CLI Bridge*
