# Code Search Engine — Agent Instruction Manual

> **Audience**: AI agents (Claude, GPT, Gemini, etc.) operating in a
> local coding environment on Windows.

> **CRITICAL: Native vs MCP — Use the Right Tool**:
> * **Native tools are FASTER and CHEAPER** for: keyword search (`grep`), file finding (`glob`), reading files (`read`).
> * **MCP tools are REQUIRED** for: AST extraction, call graph, dependency tracing, semantic search, safe editing.
> * **Rule of thumb**: If native can do it, use native. Only use MCP when you need AST-level precision or editing capabilities.
>
> **`get_index` AND `get_overview` — SAFE WITHOUT FILTERS**:
> * Calling `get_index()` or `get_overview()` **without filters** returns a **compact summary** (~200 tokens): total files, symbols, languages, top dirs, top files.
> * Use filters (`dir`, `package`, `files`) to zoom into a specific area for detailed results (~500-3000 tokens).
> * Good: `get_index(package="codeengine/core")` — detailed file list for that package
> * Good: `get_index()` — quick repo summary, safe to call freely

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

### Option C: Get All Tool Docs via API

```bash
curl http://127.0.0.1:8000/tools
```
Returns full documentation for all MCP tools, including token costs, tradeoffs, and recommended workflows.

---

## 2. Tool Selection Strategy

### Native vs MCP — Decision Table

| Task | Use | Token Cost | Why? |
|:-----|:----|:-----------|:-----|
| **Search for a keyword** | Native `grep_search` | ~200 tokens | Compact, no JSON overhead |
| **Find files by pattern** | Native `glob` | ~50 tokens | Fast, built-in |
| **Read a full file** | Native `read` | Direct | No HTTP overhead |
| **Read one function** | MCP `extract_function` | ~50-150 tokens | Only the function body |
| **Read one class** | MCP `extract_class` | ~100-300 tokens | Only the class block |
| **Quick function overview** | MCP `get_signature` | ~30-50 tokens | Signature + docstring only |
| **Find by meaning (semantic)** | MCP `semantic_search` | ~200-500 tokens | Natural language query |
| **Find similar functions** | MCP `find_similar_functions` | ~150-300 tokens | By embedding distance |
| **File dependencies** | MCP `get_file_deps` | ~100-150 tokens | Both directions at once |
| **Impact before change** | MCP `impact_analysis` | ~200-400 tokens | Full blast radius |
| **Propose / Apply edits** | MCP `preview_edit`/`apply_edit` | ~200-500 tokens | Auto git commit, safe diffs |
| **Get context to edit** | MCP `get_edit_context` | ~150-300 tokens | Source, callers, callees, imports |

---

## 3. MCP Tool Reference

### Utility
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `ping` | Check if daemon is online | ~20 |
| `get_tools_docs` | Full documentation for all tools | ~500 (cached) |

### Code Search
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `search_code(query, path?, lang?, limit?)` | Ripgrep search. Use sparingly — native grep is faster. | ~500+ |
| `search_symbol(name, kind?)` | Find function/class definitions by name | ~100-300 |
| `find_file(pattern, root?)` | Find files by name pattern — native glob is faster | ~50-100 |

### Semantic Search (Embeddings)
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `embedding_status()` | Check if embeddings are enabled, progress, model info | ~50 |
| `toggle_embeddings(enabled)` | Enable or disable embedding generation | ~20 |
| `semantic_search(query, limit?)` | Find code by natural language meaning | ~200-500 |
| `find_similar_functions(symbol_name, file?, limit?)` | Find functions with similar behavior | ~150-300 |

> **Note**: Semantic search requires embeddings to be enabled (toggle ON in UI or via `toggle_embeddings(true)`). First use downloads the model (~67MB). Embeddings auto-start after indexing if toggle is ON.

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
| `get_overview(dir?, package?, limit?, offset?)` | Full overview with call graph. No filters = compact summary (~200 tokens). | ~200-5000 |
| `get_callers(symbol_name)` | Who calls this function? | ~200-500 |
| `get_callees(symbol_name)` | What does this function call? | ~200-500 |

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
| `count_references(symbol_name)` | How many times is this symbol used? | ~20-50 |

### Impact Analysis & Tracing
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `impact_analysis(symbol_name)` | Full impact — callers, references, affected files | ~200-400 |
| `trace_execution(symbol_name, max_depth?)` | Trace call chain through the application | ~200-500 |

### Editing (Always preview before applying)
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `get_edit_context(symbol, file?, dir?, package?)` | Get exact source, callers, callees, and imports for editing | ~150-300 |
| `preview_edit(file, old_code, new_code)` | Stage an edit, returns diff + edit_id | ~200-500 |
| `apply_edit(edit_id)` | Write edit to disk + auto git commit | ~50 |
| `preview_smart_edit(file, new_code)` | Smart edit — engine detects what to replace | ~200-500 |
| `apply_smart_edit(edit_id)` | Apply smart edit to disk + auto git commit | ~50 |
| `undo_edit()` | Revert last edit (`git revert HEAD`) | ~50 |

> **Note on undo**: `undo_edit` uses `git revert`. If an edit was the first commit for a new file, reverting deletes the file. The engine now auto-commits untracked files before the first edit to prevent this.

### Code Analysis
| Tool | Description | Token Cost |
|:-----|:------------|:-----------|
| `detect_snippet(code, file_hint?, lang_hint?)` | Locate a code snippet's origin | ~100-200 |
| `parse_blocks(code, file_hint?, lang_hint?)` | Parse code into structural blocks | ~100-200 |

---

## 4. Workflows

### Workflow A: Read a targeted method
1. Use native `grep_search` to find where the method is defined.
2. Read *only* that method with `extract_function`.

### Workflow B: Safe Code Modifications
1. Read the method using `extract_function`.
2. Generate the edit preview using `preview_edit`.
3. Verify the diff, then apply using `apply_edit`.
4. If tests fail, immediately call `undo_edit`.

### Workflow C: Explore a module (scoped)
1. Get module overview: `get_overview(package="codeengine/core")`
2. Find callers: `get_callers("search_code")`
3. Extract a function: `extract_function("codeengine/core/search_engine.py", "search_code")`

### Workflow C2: Quick repo orientation (unfiltered)
1. Get repo summary: `get_index()` — returns total files, languages, top dirs, top files (~200 tokens)
2. Zoom into an area: `get_index(dir="codeengine/core")` — paginated file list
3. Zoom into a file: `get_index(files=["search_engine.py"])` — file symbols

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
4. Preview using `preview_edit` or write edits as needed.

### Workflow G: Semantic search for code by meaning
1. Ensure embeddings are enabled: `toggle_embeddings(true)` or UI toggle ON.
2. Index a repo (embeddings auto-start after indexing).
3. Search by meaning: `semantic_search("handle user authentication")`.
4. Click result to view code in code panel.

### Workflow H: Find similar functions
1. Find a function: `search_symbol(name="search_code")`.
2. Find similar: `find_similar_functions("search_code")`.
3. Extract to compare: `extract_function(file, name)`.

---

## 5. Native vs MCP — Detailed Guide

### ALWAYS Use Native Tools For
| Task | Native Tool | Token Cost | MCP Equivalent (Slower) |
|:-----|:------------|:-----------|:------------------------|
| **Keyword search** | `grep_search` | ~200 tokens | `search_code` (~500+) |
| **Find files** | `glob` | ~50 tokens | `find_file` (~50-100) |
| **Read a file** | `read` | Direct | N/A |
| **List directory** | `ls` / `read` dir | Direct | N/A |

### ALWAYS Use MCP Tools For
| Task | MCP Tool | Why Native Can't Do It |
|:-----|:---------|:----------------------|
| **Extract one function** | `extract_function` | AST parsing, only returns the function |
| **Extract one class** | `extract_class` | AST parsing, only returns the class |
| **Get function signature** | `get_signature` | Cheapest way to understand a function |
| **Semantic search** | `semantic_search` | Embedding-based meaning search |
| **Find similar functions** | `find_similar_functions` | Embedding distance comparison |
| **Call graph** | `get_callers` / `get_callees` | Static analysis of call relationships |
| **Impact analysis** | `impact_analysis` | Full blast radius before changes |
| **Safe editing** | `preview_edit` + `apply_edit` | Auto git commit, undo support |
| **Dependency tracing** | `get_file_deps` / `get_importers` | Both directions in one call |

### Decision Flowchart
```
Need to search for a keyword?
  → YES → Use native grep_search (faster, cheaper)
  → NO ↓

Need to find files by name?
  → YES → Use native glob (faster, cheaper)
  → NO ↓

Need to read a whole file?
  → YES → Use native read (direct, no overhead)
  → NO ↓

Need to extract one function/class?
  → YES → Use MCP extract_function/extract_class
  → NO ↓

Need to search by meaning (not keywords)?
  → YES → Use MCP semantic_search
  → NO ↓

Need call graph, dependencies, or impact analysis?
  → YES → Use MCP get_callers/get_callees/impact_analysis
  → NO ↓

Need to edit code safely?
  → YES → Use MCP preview_edit + apply_edit
  → NO → Use native tools
```

---

*Code Search Engine v2.1.0 — MCP Server + FastAPI Daemon + Semantic Embeddings*
