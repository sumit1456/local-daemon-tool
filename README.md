# Code Search Engine

Local-first developer tool that acts as an intelligent repository engine for humans and AI models. Combines a FastAPI backend, MCP server, and web UI for code search, editing, and analysis.

## Features

- **Code Search** — Ripgrep-powered search with language filtering
- **Semantic Search** — Find code by meaning using embeddings (BAAI/bge-small-en-v1.5)
- **AST Extraction** — Extract functions, classes, signatures via tree-sitter
- **Call Graph** — Get callers, callees, impact analysis, execution tracing
- **Dependency Analysis** — Imports, importers, file dependencies
- **Safe Code Editing** — Preview diffs before applying, auto git commit, undo support
- **MCP Server** — Full tool suite for AI agents
- **CLI Interface** — `ce_cli.py` for agent use via run_command
- **Web UI** — Desktop app with pywebview, browser also works

## Installation

### Prerequisites

- Python 3.10+ (3.11 recommended)
- Git

### Setup (One-time)

**Windows:**
```powershell
setup.bat
```

**Linux/Mac:**
```bash
bash setup.sh
```

This creates two virtual environments and installs all dependencies:
- `.venv` — Main server (FastAPI, uvicorn, fastembed, sqlite-vec)
- `.venv-mcp` — MCP server (mcp, httpx)

### Launch

**Windows:**
```powershell
CodeEngine.bat
```

**Linux/Mac:**
```bash
./CodeEngine.sh
```

Or directly:
```powershell
# Windows
.venv\Scripts\pythonw.exe launcher.pyw

# Linux/Mac
.venv/bin/python launcher.pyw
```

The launcher starts both the FastAPI daemon (port 8000) and MCP server. A splash screen shows startup progress, then opens the desktop app.

## Usage

### Web UI

After launching, the app opens automatically. Select a repository folder to index, then use the sidebar to navigate between search, edit, and analysis tools.

### CLI (for AI Agents)

```powershell
.venv\Scripts\python.exe ce_cli.py <command> [args]
```

Key commands:
```powershell
# Search
ce_cli.py search "pattern" --lang python
ce_cli.py symbol "function_name"
ce_cli.py file "*.py"

# Extract code
ce_cli.py function "path/to/file.py" "FunctionName"
ce_cli.py class "path/to/file.py" "ClassName"
ce_cli.py signature "path/to/file.py" 42 89

# Semantic search
ce_cli.py toggle-embeddings true
ce_cli.py semantic-search "handle user authentication"
ce_cli.py find-similar "search_code"

# Analysis
ce_cli.py index
ce_cli.py callers "function_name"
ce_cli.py impact "function_name"
ce_cli.py trace "function_name"

# Editing
ce_cli.py preview "file.py" "old code" "new code"
ce_cli.py apply "edit_id"
ce_cli.py undo
```

Full list: `ce_cli.py --help`

### MCP Server

Configure in your MCP client:
```json
{
  "mcpServers": {
    "CodeSearchEngine": {
      "command": ".venv-mcp\\Scripts\\python.exe",
      "args": ["mcp_server.py"],
      "cwd": "C:\\path\\to\\local-daemon-tool"
    }
  }
}
```

Or get tool docs via API:
```bash
curl http://127.0.0.1:8000/tools
```

## Architecture

```
local-daemon-tool/
├── launcher.pyw          # Combined launcher (splash + starts both servers)
├── CodeEngine.bat/.sh    # Double-click to launch
├── setup.bat/.sh         # One-time setup (creates venvs, installs deps)
├── ce_cli.py             # CLI for AI agents
├── mcp_server.py         # MCP server (stdio transport)
├── codeengine/
│   ├── app.py            # FastAPI application
│   ├── api/
│   │   ├── search.py     # Search, semantic, embedding endpoints
│   │   └── edit.py       # Edit endpoints
│   ├── core/
│   │   ├── search_engine.py      # Search logic
│   │   ├── ast_engine.py         # Tree-sitter AST parsing
│   │   ├── index_engine.py       # Repository indexing
│   │   ├── embedding_engine.py   # Fastembed vector embeddings
│   │   └── edit_engine.py        # Edit/merge logic
│   ├── database/
│   │   ├── schema.sql    # Database schema
│   │   └── sqlite.py     # Database access
│   ├── models/           # Pydantic models
│   └── static/
│       ├── index.html    # Web UI
│       └── static.js     # Frontend JS
├── data/
│   └── index.db          # SQLite database (auto-created)
└── logs/
    └── launcher.log      # Launcher logs
```

## MCP Tools Reference

| Category | Tools |
|:---------|:------|
| **Search** | `search_code`, `search_symbol`, `find_file` |
| **Semantic** | `semantic_search`, `find_similar_functions`, `toggle_embeddings`, `embedding_status` |
| **AST** | `extract_function`, `extract_class`, `get_signature`, `get_body` |
| **Intelligence** | `get_index`, `get_overview`, `get_callers`, `get_callees` |
| **Dependencies** | `get_imports`, `get_importers`, `get_file_deps` |
| **Analysis** | `get_type_info`, `get_defined_symbols`, `count_references`, `impact_analysis`, `trace_execution` |
| **Editing** | `preview_edit`, `apply_edit`, `preview_smart_edit`, `apply_smart_edit`, `undo_edit`, `get_edit_context` |
| **Utility** | `ping`, `get_tools_docs`, `detect_snippet`, `parse_blocks` |

See `AGENT_MANUAL.md` for detailed usage and token costs.

## Native vs MCP Tools

Use native tools when possible — they're faster and cheaper:

| Task | Use | Why |
|:-----|:----|:----|
| Keyword search | Native `grep_search` | ~200 tokens vs ~500+ for MCP |
| Find files | Native `glob` | ~50 tokens vs ~100 for MCP |
| Read file | Native `read` | Direct, no overhead |
| Extract function | MCP `extract_function` | AST parsing, only returns function |
| Semantic search | MCP `semantic_search` | Embedding-based meaning search |
| Safe editing | MCP `preview_edit` + `apply_edit` | Auto git commit, undo support |

## License

Internal tool — not for distribution.
