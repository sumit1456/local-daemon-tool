# Code Search Engine — Agent Instruction Manual

> **Audience**: AI agents (Claude, GPT, Gemini, etc.) operating in a
> local coding environment on Windows.
>
> **CRITICAL PERFORMANCE RULE (Token Budget)**:
> * **DO NOT** use `search_code` for broad queries (e.g. "bbox", "config"). It returns raw JSON which consumes 10x-15x more tokens than native `grep_search`.
> * **DO** use MCP tools for targeted AST extraction (`extract_function`, `extract_class`) and safe editing (`preview_smart_edit`/`apply_smart_edit`).
>
> **`get_index` — SAFE WITHOUT FILTERS**:
> * Calling `get_index()` **without filters** returns a **compact summary** (~200 tokens): total files, symbols, languages, top dirs, top files.
> * Use filters (`dir`, `package`, `files`) to zoom into a specific area for detailed results (~500-3000 tokens).
> * Good: `get_index(package="codeengine/core")` — detailed file list for that package
> * Good: `get_index()` — quick repo summary, safe to call freely
>
> **`get_overview` — REQUIRES FILTER**:
> * `get_overview()` **without filters raises an error**. Always pass `dir`, `package`, `query`, or `files`.
> * Returns compact format: flattened symbols per file + grouped call edges (~3KB for 10 files).
> * Good: `get_overview(dir="codeengine/core")` — compact file listing + call graph
> * Good: `get_overview(package="codeengine.api")` — zoom into a package

---

## 1. Setup

### Option A: Combined Launcher (Recommended)

Double-click `CodeEngine_v2.bat` or run:
```powershell
pythonw launcher_v2.pyw
```
Starts both FastAPI daemon (port 8000) and MCP server automatically.

### Option B: MCP Client Configuration

Add to your MCP client config (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "CodeSearchEngine": {
      "command": ".venv-mcp\\Scripts\\python.exe",
      "args": ["mcp_server.py"],
      "cwd": "C:\\Users\\SUMIT\\Downloads\\dev-tool\\local-daemon-tool"
    }
  }
}
```

---

## 2. Tool Selection Strategy

| Task | Best Tool | Token Cost | Why? |
|:-----|:----------|:-----------|:-----|
| **Broad Keyword Search** | Native `grep_search` | ~200 tokens | Compact summary, no JSON overhead |
| **List Files by Pattern** | Native `glob` | ~50 tokens | Fast, built-in |
| **Read a Specific Function** | MCP `extract_function` | ~50-150 tokens | AST extraction, only the function body |
| **Read a Specific Class** | MCP `extract_class` | ~100-300 tokens | Only the class block |
| **Quick Function Overview** | MCP `get_signature` | ~30-50 tokens | Signature + docstring only |
| **File Dependencies** | MCP `get_file_deps` | ~100-150 tokens | Both directions at once |
| **Impact Before Change** | MCP `impact_analysis` | ~200-400 tokens | Full blast radius |
| **Propose / Apply Edits** | MCP `preview_smart_edit`/`apply_smart_edit` | ~200-500 tokens | Auto git commit, safe diffs |
| **Get Context to Edit a Symbol** | MCP `get_edit_context` | ~150-300 tokens | Get exact source, callers, callees, and imports of target symbol |

---

## 3. MCP Tool Reference

### Utility
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `ping` | Check if daemon is online | ~20 |

### Code Search
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `search_code(query, path?, lang?, limit?)` | Ripgrep search. Use sparingly. | ~500+ |
| `search_symbol(name, kind?)` | Find function/class definitions by name. Returns "name:kind:file:line_start-line_end" | ~50-100 |
| `find_file(pattern, root?)` | Find files by name pattern | ~50-100 |
| `search_usages(symbol_name, limit?)` | Find all references including imports, type annotations | ~200-500 |

### AST Extraction (Preferred for reading code)
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `extract_function(file, name)` | Extract a single function body via tree-sitter | ~50-150 |
| `extract_class(file, name)` | Extract a single class block via tree-sitter | ~100-300 |
| `get_signature(file, line_start, line_end)` | Get only signature + docstring (cheapest) | ~30-50 |
| `get_body(file, line_start, line_end)` | Get full function body by line range | ~200-500 |

### Code Intelligence
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `get_index(dir?, package?, limit?, offset?)` | File + symbol index. No filters = compact summary (~200 tokens). | ~200-3000 |
| `get_overview(dir?, package?, query?, files?, limit?, offset?)` | Compact file listing + call graph. **Requires filter.** Returns flattened symbols and grouped edges (~3KB for 10 files). | ~200-3000 |
| `get_callers(symbol_name)` | Who calls this function? | ~200-500 |
| `get_callees(symbol_name)` | What does this function call? | ~200-500 |
| `trace_execution(symbol_name, max_depth?)` | Trace call chain through the application | ~500-1000 |
| `trace_endpoint_flow(entry_point, max_depth?)` | Trace complete execution path from entry point | ~200-400 |

### Dependency Intelligence
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `get_imports(file)` | Show all imports used by a file | ~50-100 |
| `get_importers(module)` | Reverse dependency — who imports this module | ~100-200 |
| `get_file_deps(file)` | Full dependency picture (both directions) | ~100-150 |

### Type & Symbol Intelligence
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `get_type_info(symbol_name, file?)` | Parameter types and return type | ~30-50 |
| `get_defined_symbols(file)` | What's defined in a file (functions, classes, etc.) | ~50-80 |
| `count_references(symbol_name)` | How many times is this symbol used? | ~100-300 |
| `get_blast_radius(symbol_name)` | Precomputed transitive blast radius | ~100-300 |
| `get_error_context(error, file, line)` | Diagnostic bundle for compiler/linter errors | ~200-500 |

### Impact Analysis
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `impact_analysis(symbol_name)` | Full impact — callers, references, affected files | ~500-1000 |

### Editing (Smart block-based)
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `get_edit_context(symbol, file?, dir?, package?)` | Get exact source, callers, callees, and imports for editing | ~150-300 |
| `preview_smart_edit(file, new_code)` | Smart edit — engine detects what to replace, returns diff + edit_id | ~200-500 |
| `apply_smart_edit(edit_id)` | Apply smart edit to disk + auto git commit | ~50-100 |

### Code Analysis
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `detect_snippet(code, file_hint?, lang_hint?)` | Locate a code snippet's origin | ~100-200 |
| `parse_blocks(code, file_hint?, lang_hint?)` | Parse code into structural blocks | ~100-200 |
| `read_file(file)` | Read full file content | ~100-500 |
| `list_workspace` | List available repos in workspace | ~50-100 |

---

## 4. Workflows

### Workflow A: Read a targeted method
1. Use native `grep_search` to find where the method is defined.
2. Read *only* that method with `extract_function`.

### Workflow B: Safe Code Modifications
1. Read the method using `extract_function`.
2. Get edit context using `get_edit_context` to understand callers/callees.
3. Generate the smart edit preview using `preview_smart_edit`.
4. Verify the diff, then apply using `apply_smart_edit`.

### Workflow C: Explore a module (scoped)
1. Get module overview: `get_overview(package="codeengine/core")`
2. Find callers: `get_callers("search_code")`
3. Extract a function: `extract_function("codeengine/core/search_engine.py", "search_code")`

### Workflow C2: Quick repo orientation
1. Get repo summary: `get_index()` — returns total files, languages, top dirs, top files (~200 tokens)
2. Zoom into an area: `get_index(dir="codeengine/core")` — paginated file list
3. Get call graph: `get_overview(dir="codeengine/core")` — compact file listing + call edges
4. Zoom into a file: `get_index(files=["search_engine.py"])` — file symbols

### Workflow D: Full impact analysis before refactoring
1. Count references: `count_references("create_user")`
2. Get full impact: `impact_analysis("create_user")`
3. Trace execution flow: `trace_execution("create_user")`
4. Check imports: `get_importers("utils.auth")`

### Workflow E: Understand a file's role
1. See what it defines: `get_defined_symbols("services/user_service.py")`
2. Check its dependencies: `get_file_deps("services/user_service.py")`
3. Check type signatures: `get_type_info("create_user")`

### Workflow F: Get minimal context for editing a symbol
1. Call `get_edit_context(symbol="process_payment")` to fetch only the source, preamble, callers, callees, and imports of that symbol.
2. If multiple candidates exist, repeat the call with the `file` param (e.g., `file="gateways/stripe.py"`).
3. Construct replacement code.
4. Preview using `preview_smart_edit` and apply with `apply_smart_edit`.

---

## 5. Native Tools (Use When MCP Is Slower)

> **WARNING**: These MCP tools are **slower and more token-heavy** than your platform's native equivalents. Use native tools first for broad searches — only fall back to MCP when you need AST-level precision or editing capabilities.

### When to Use Native Tools (NOT MCP)
| Task | Use Native Tool | Why Native Is Better |
|:-----|:----------------|:---------------------|
| **Search for a keyword** | `grep_search` | ~200 tokens vs ~500+ for `search_code` |
| **Find files by pattern** | `glob` | ~50 tokens vs ~100 for `find_file` |
| **Read a full file** | `read` (native) | Direct, no HTTP overhead |

### When to Use MCP Instead
| Task | Use MCP Tool | Why MCP Is Better |
|:-----|:-------------|:-------------------|
| **Read one function** | `extract_function` | ~50 tokens vs ~2000+ for full file read |
| **Read one class** | `extract_class` | Only the class block, not the whole file |
| **Check dependencies** | `get_file_deps` | Both directions in one call |
| **Impact before change** | `impact_analysis` | Full blast radius in one call |
| **Apply safe edits** | `preview_smart_edit` + `apply_smart_edit` | Auto git commit |

### MCP Search Tools (Use Sparingly)
| Tool | Token Cost | When to Use |
|:-----|:-----------|:------------|
| `search_code` | ~500+ | When you need language filtering or context lines |
| `search_symbol` | ~100-300 | When you need AST-precise symbol lookup |
| `find_file` | ~50-100 | When you need recursive file search |

> **Rule of thumb**: If native `grep_search` can do it, use native. Only use MCP search tools when you need something native can't do (AST extraction, dependency analysis, safe editing).

---

*Code Search Engine v2.0.0 — MCP Server + FastAPI Daemon*
