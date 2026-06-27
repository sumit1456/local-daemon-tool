# Code Search Engine

Local-first developer tool that acts as an intelligent repository engine for humans and AI models. Combines a FastAPI backend, MCP server, and web UI for code search, editing, and analysis.

## Features

- **Code Search** — Ripgrep-powered search with language filtering
- **Semantic Search** — Find code by meaning using embeddings (BAAI/bge-small-en-v1.5)
- **AST Extraction** — Extract functions, classes, signatures via tree-sitter
- **Call Graph** — Get callers, callees, impact analysis, execution tracing
- **Dependency Analysis** — Imports, importers, file dependencies
- **Safe Code Editing** — Smart block-based editing with auto git commit
- **MCP Server** — Tool suite for AI agents (search, analysis, semantic, editing)
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
ce_cli.py body "path/to/file.py" 42 89

# Analysis
ce_cli.py index
ce_cli.py overview
ce_cli.py callers "function_name"
ce_cli.py callees "function_name"

# Code analysis
ce_cli.py detect "code_snippet"
ce_cli.py parse-blocks "code_snippet"

# Editing
ce_cli.py preview-smart "file.py" "new code"
ce_cli.py apply-smart "edit_id"
```

Full list: `ce_cli.py --help`

### MCP Server

#### For OpenCode
Configure in OpenCode's MCP settings:
```json
{
  "mcpServers": {
    "CodeSearchEngine": {
      "command": "C:\\path\\to\\local-daemon-tool\\.venv-mcp\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\local-daemon-tool\\mcp_server.py"]
    }
  }
}
```

#### For Claude Desktop
Configure in your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "CodeSearchEngine": {
      "command": "C:\\path\\to\\local-daemon-tool\\.venv-mcp\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\local-daemon-tool\\mcp_server.py"]
    }
  }
}
```

#### For Antigravity (Gemini IDE)
Antigravity automatically discovers MCP tools by placing tool schemas (`<toolName>.json`) inside the `~/.gemini/antigravity-ide/mcp/CodeSearchEngine/` directory.

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

### Currently Tested & Working (12 tools)

| Category | Tools |
|:---------|:------|
| **Search** | `search_symbol`, `semantic_search` |
| **AST** | `extract_function`, `extract_class` |
| **Intelligence** | `get_overview`, `get_callers`, `get_callees` |
| **Dependencies** | `get_imports`, `get_importers`, `get_file_deps` |
| **Analysis** | `get_edit_context` |
| **Utility** | `ping` |

### Upcoming (vNext) — Not Yet Exposed via MCP (14 tools)

| Category | Tools |
|:---------|:------|
| **Search** | `search_code`, `find_file`, `search_usages` |
| **Semantic** | `find_similar_functions`, `toggle_embeddings`, `embedding_status` |
| **AST** | `extract_by_name`, `get_signature`, `get_body` |
| **Intelligence** | `get_index`, `trace_execution`, `trace_endpoint_flow` |
| **Analysis** | `get_type_info`, `get_defined_symbols`, `count_references`, `impact_analysis`, `get_blast_radius`, `get_error_context` |
| **Editing** | `preview_smart_edit`, `apply_smart_edit` |
| **Utility** | `get_tools_docs`, `detect_snippet`, `parse_blocks`, `read_file`, `list_workspace` |

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
| Safe editing | MCP `preview_smart_edit` + `apply_smart_edit` | Auto git commit |

## License

Internal tool — not for distribution.
