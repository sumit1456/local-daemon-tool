# """
# ce_cli.py — Code Search Engine command-line interface for agents.

# AI agents cannot call http://127.0.0.1 via read_url_content (blocked).
# This CLI bridges the gap: agents call it via run_command/PowerShell,
# and it talks to the local server on their behalf.

# Usage (from the local-daemon-tool directory):
#     .venv\Scripts\python.exe ce_cli.py search "pattern" [--path .] [--lang python] [--limit 50]
#     .venv\Scripts\python.exe ce_cli.py symbol "name"   [--kind function|class|method|interface]
#     .venv\Scripts\python.exe ce_cli.py file   "pattern" [--root .]
#     .venv\Scripts\python.exe ce_cli.py function "rel/path/to/file.py" "FunctionName"
#     .venv\Scripts\python.exe ce_cli.py class    "rel/path/to/file.py" "ClassName"
#     .venv\Scripts\python.exe ce_cli.py ping
# """

# import sys
# import json
# import argparse
# import urllib.request
# import urllib.parse
# import urllib.error

# BASE = "http://127.0.0.1:8000"


# # ── HTTP helpers ─────────────────────────────────────────────────────────────

# def _get(endpoint: str, **params) -> object:
#     url = endpoint
#     if params:
#         url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
#     try:
#         with urllib.request.urlopen(BASE + url, timeout=15) as r:
#             return json.loads(r.read())
#     except urllib.error.URLError as e:
#         _die(f"Cannot reach the Code Search Engine at {BASE}.\n"
#              f"Start it first: .venv\\Scripts\\pythonw.exe launcher.pyw\n"
#              f"Error: {e}")


# def _post(path: str, body: dict) -> object:
#     data = json.dumps(body).encode()
#     req  = urllib.request.Request(
#         BASE + path, data=data,
#         headers={"Content-Type": "application/json"}
#     )
#     try:
#         with urllib.request.urlopen(req, timeout=30) as r:
#             return json.loads(r.read())
#     except urllib.error.HTTPError as e:
#         err = json.loads(e.read()).get("detail", e.reason)
#         _die(f"API error {e.code}: {err}")
#     except urllib.error.URLError as e:
#         _die(f"Cannot reach the Code Search Engine at {BASE}.\n"
#              f"Start it first: .venv\\Scripts\\pythonw.exe launcher.pyw\n"
#              f"Error: {e}")


# def _out(data: object) -> None:
#     """Print clean JSON to stdout for the agent to parse."""
#     print(json.dumps(data, indent=2, ensure_ascii=False))


# def _die(msg: str) -> None:
#     print(json.dumps({"error": msg}), file=sys.stderr)
#     sys.exit(1)


# # ── Sub-commands ─────────────────────────────────────────────────────────────

# def cmd_ping(_args) -> None:
#     """Check if the service is running."""
#     try:
#         urllib.request.urlopen(BASE + "/docs", timeout=3)
#         _out({"status": "ok", "url": BASE})
#     except urllib.error.URLError:
#         _out({"status": "offline",
#               "message": "Service not running. Start: .venv\\Scripts\\pythonw.exe launcher.pyw"})


# def cmd_search(args) -> None:
#     """Search code with ripgrep. Returns matching lines."""
#     data = _get("/search/code",
#                 q=args.query,
#                 path=args.path,
#                 lang=args.lang,
#                 limit=args.limit)
#     # Flatten to a compact, agent-friendly format
#     out = {
#         "query": data["query"],
#         "total": data["total"],
#         "matches": [
#             {
#                 "file":  m["file"],
#                 "line":  m["line"],
#                 "col":   m["col"],
#                 "text":  m["text"].strip(),
#             }
#             for m in data["matches"]
#         ]
#     }
#     _out(out)


# def cmd_symbol(args) -> None:
#     """Search the AST symbol index (functions, classes, methods)."""
#     data = _get("/search/symbol", name=args.name, kind=args.kind)
#     _out(data)


# def cmd_file(args) -> None:
#     """Find files by name pattern using fd."""
#     data = _get("/search/file", pattern=args.pattern, root=args.root)
#     _out(data)


# def cmd_function(args) -> None:
#     """Extract source code of a single function using tree-sitter AST."""
#     data = _get("/search/function", file=args.file, name=args.name)
#     _out(data)


# def cmd_class(args) -> None:
#     """Extract source code of a single class using tree-sitter AST."""
#     data = _get("/search/class", file=args.file, name=args.name)
#     _out(data)


# def cmd_preview(args) -> None:
#     """Preview a code edit as a unified diff (does NOT write to disk)."""
#     data = _post("/preview-edit", {
#         "file":     args.file,
#         "old_code": args.old_code,
#         "new_code": args.new_code,
#     })
#     _out(data)


# def cmd_apply(args) -> None:
#     """Apply a previewed edit to disk and commit to git."""
#     data = _post("/apply-edit", {"edit_id": args.edit_id})
#     _out(data)


# def cmd_undo(_args) -> None:
#     """Revert the last applied edit (git revert HEAD)."""
#     data = _post("/undo", {})
#     _out(data)


# def cmd_index(args) -> None:
#     """Get file and symbol index for the repository."""
#     data = _get("/search/index", files=args.files)
#     _out(data)


# def cmd_overview(args) -> None:
#     """Get a complete overview of the repository including call edges."""
#     data = _get("/search/overview", files=args.files)
#     _out(data)


# def cmd_callers(args) -> None:
#     """Get all functions that call the given symbol."""
#     data = _get("/search/callers", symbol_name=args.symbol_name)
#     _out(data)


# def cmd_callees(args) -> None:
#     """Get all functions called by the given symbol."""
#     data = _get("/search/callees", symbol_name=args.symbol_name)
#     _out(data)


# def cmd_signature(args) -> None:
#     """Get signature and docstring for a function."""
#     data = _get("/search/function-signature", file=args.file, line_start=args.line_start, line_end=args.line_end)
#     _out(data)


# def cmd_body(args) -> None:
#     """Get full function body."""
#     data = _get("/search/function-body", file=args.file, line_start=args.line_start, line_end=args.line_end)
#     _out(data)



# # ── Argument parser ───────────────────────────────────────────────────────────

# def build_parser() -> argparse.ArgumentParser:
#     p = argparse.ArgumentParser(
#         prog="ce_cli.py",
#         description="Code Search Engine CLI — for agent use via run_command",
#     )
#     sub = p.add_subparsers(dest="command", required=True)

#     # ping
#     sub.add_parser("ping", help="Check if the service is running")

#     # search
#     s = sub.add_parser("search", help="Search code with ripgrep")
#     s.add_argument("query",               help="Search pattern or text")
#     s.add_argument("--path",  default=".", help="Root directory (default: .)")
#     s.add_argument("--lang",  default=None,
#                    help="Language filter: python|javascript|typescript|java|go|rust")
#     s.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")

#     # symbol
#     s = sub.add_parser("symbol", help="Search AST symbol index")
#     s.add_argument("name",              help="Symbol name (partial match)")
#     s.add_argument("--kind", default=None,
#                    help="Kind filter: function|class|method|interface")

#     # file
#     s = sub.add_parser("file", help="Find files by name pattern (fd)")
#     s.add_argument("pattern",            help="Filename pattern (empty = all files)")
#     s.add_argument("--root", default=".", help="Root directory (default: .)")

#     # function
#     s = sub.add_parser("function", help="Extract function source (tree-sitter)")
#     s.add_argument("file", help="Relative file path (e.g. codeengine/app.py)")
#     s.add_argument("name", help="Exact function name")

#     # class
#     s = sub.add_parser("class", help="Extract class source (tree-sitter)")
#     s.add_argument("file", help="Relative file path")
#     s.add_argument("name", help="Exact class name")

#     # preview-edit
#     s = sub.add_parser("preview", help="Preview a code edit (unified diff)")
#     s.add_argument("file",     help="Relative file path")
#     s.add_argument("old_code", help="Exact code block to replace")
#     s.add_argument("new_code", help="Replacement code")

#     # apply-edit
#     s = sub.add_parser("apply", help="Apply a previewed edit + git commit")
#     s.add_argument("edit_id", help="edit_id from the preview response")

#     # undo
#     sub.add_parser("undo", help="Revert last applied edit (git revert HEAD)")

#     return p


# # ── Entry point ───────────────────────────────────────────────────────────────

# HANDLERS = {
#     "ping":     cmd_ping,
#     "search":   cmd_search,
#     "symbol":   cmd_symbol,
#     "file":     cmd_file,
#     "function": cmd_function,
#     "class":    cmd_class,
#     "preview":  cmd_preview,
#     "apply":    cmd_apply,
#     "undo":     cmd_undo,
# }

# if __name__ == "__main__":
#     parser = build_parser()
#     args   = parser.parse_args()
#     HANDLERS[args.command](args)



"""
ce_cli.py — Code Search Engine command-line interface for agents.

AI agents cannot call http://127.0.0.1 via read_url_content (blocked).
This CLI bridges the gap: agents call it via run_command/PowerShell,
and it talks to the local server on their behalf.

Usage (from the local-daemon-tool directory):
    .venv\Scripts\python.exe ce_cli.py search "pattern" [--path .] [--lang python] [--limit 50]
    .venv\Scripts\python.exe ce_cli.py symbol "name"   [--kind function|class|method|interface]
    .venv\Scripts\python.exe ce_cli.py file   "pattern" [--root .]
    .venv\Scripts\python.exe ce_cli.py function "rel/path/to/file.py" "FunctionName"
    .venv\Scripts\python.exe ce_cli.py class    "rel/path/to/file.py" "ClassName"
    .venv\Scripts\python.exe ce_cli.py index    [--files foo.py bar.py]
    .venv\Scripts\python.exe ce_cli.py overview [--files foo.py bar.py]
    .venv\Scripts\python.exe ce_cli.py callers  "symbol_name"
    .venv\Scripts\python.exe ce_cli.py callees  "symbol_name"
    .venv\Scripts\python.exe ce_cli.py signature "rel/path/to/file.py" 42 89
    .venv\Scripts\python.exe ce_cli.py body      "rel/path/to/file.py" 42 89
    .venv\Scripts\python.exe ce_cli.py detect    "def foo(): pass"
    .venv\Scripts\python.exe ce_cli.py preview-smart "rel/path/to/file.py" "new_code"
    .venv\Scripts\python.exe ce_cli.py apply-smart "edit_id"
    .venv\Scripts\python.exe ce_cli.py parse-blocks "def foo(): pass"
    .venv\Scripts\python.exe ce_cli.py ping
"""

import sys
import json
import argparse
import urllib.request
import urllib.parse
import urllib.error

BASE = "http://127.0.0.1:8000"


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _get(endpoint: str, **params) -> object:
    url = endpoint
    if params:
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}, doseq=True
        )
    try:
        with urllib.request.urlopen(BASE + url, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        _die(f"Cannot reach the Code Search Engine at {BASE}.\n"
             f"Start it first: .venv\\Scripts\\pythonw.exe launcher.pyw\n"
             f"Error: {e}")


def _post(path: str, body: dict) -> object:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = json.loads(e.read()).get("detail", e.reason)
        _die(f"API error {e.code}: {err}")
    except urllib.error.URLError as e:
        _die(f"Cannot reach the Code Search Engine at {BASE}.\n"
             f"Start it first: .venv\\Scripts\\pythonw.exe launcher.pyw\n"
             f"Error: {e}")


def _out(data: object) -> None:
    """Print clean JSON to stdout for the agent to parse."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _die(msg: str) -> None:
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(1)


# ── Sub-commands ─────────────────────────────────────────────────────────────

def cmd_ping(_args) -> None:
    """Check if the service is running."""
    try:
        urllib.request.urlopen(BASE + "/docs", timeout=3)
        _out({"status": "ok", "url": BASE})
    except urllib.error.URLError:
        _out({"status": "offline",
              "message": "Service not running. Start: .venv\\Scripts\\pythonw.exe launcher.pyw"})


def cmd_search(args) -> None:
    """Search code with ripgrep. Returns matching lines."""
    data = _get("/search/code",
                q=args.query,
                path=args.path,
                lang=args.lang,
                limit=args.limit)
    out = {
        "query":   data["query"],
        "total":   data["total"],
        "matches": [
            {"file": m["file"], "line": m["line"], "col": m["col"], "text": m["text"].strip()}
            for m in data["matches"]
        ]
    }
    _out(out)


def cmd_symbol(args) -> None:
    """Search the AST symbol index (functions, classes, methods)."""
    data = _get("/search/symbol",
                name=args.name,
                kind=args.kind,
                dir=args.dir,
                package=args.package)
    _out(data)


def cmd_file(args) -> None:
    """Find files by name pattern using fd."""
    data = _get("/search/file", pattern=args.pattern, root=args.root)
    _out(data)


def cmd_function(args) -> None:
    """Extract source code of a single function using tree-sitter AST."""
    data = _get("/search/function", file=args.file, name=args.name)
    _out(data)


def cmd_class(args) -> None:
    """Extract source code of a single class using tree-sitter AST."""
    data = _get("/search/class", file=args.file, name=args.name)
    _out(data)


def cmd_preview(args) -> None:
    """Preview a code edit as a unified diff (does NOT write to disk)."""
    data = _post("/preview-edit", {
        "file":     args.file,
        "old_code": args.old_code,
        "new_code": args.new_code,
    })
    _out(data)


def cmd_apply(args) -> None:
    """Apply a previewed edit to disk and commit to git."""
    data = _post("/apply-edit", {"edit_id": args.edit_id})
    _out(data)


def cmd_undo(_args) -> None:
    """Revert the last applied edit (git revert HEAD)."""
    data = _post("/undo", {})
    _out(data)


def cmd_index(args) -> None:
    """Get file and symbol index. Pass --files/--dir/--package to scope."""
    data = _get("/search/index",
                files=args.files if args.files else None,
                dir=args.dir,
                package=args.package)
    _out(data)


def cmd_overview(args) -> None:
    """Get complete repo overview including call graph. Pass --files/--dir/--package to scope."""
    data = _get("/search/overview",
                files=args.files if args.files else None,
                dir=args.dir,
                package=args.package)
    _out(data)


def cmd_callers(args) -> None:
    """Get all functions that call the given symbol."""
    data = _get("/search/callers",
                symbol_name=args.symbol_name,
                dir=args.dir,
                package=args.package)
    _out(data)


def cmd_callees(args) -> None:
    """Get all functions called by the given symbol."""
    data = _get("/search/callees",
                symbol_name=args.symbol_name,
                dir=args.dir,
                package=args.package)
    _out(data)


def cmd_signature(args) -> None:
    """Get signature and docstring only — no body. Cheapest context fetch."""
    data = _get("/search/function-signature",
                file=args.file,
                line_start=args.line_start,
                line_end=args.line_end)
    _out(data)


def cmd_body(args) -> None:
    """Get full function body (exact lines, no noise)."""
    data = _get("/search/function-body",
                file=args.file,
                line_start=args.line_start,
                line_end=args.line_end)
    _out(data)


def cmd_detect(args) -> None:
    """Detect original source block of a code snippet."""
    data = _post("/search/detect-original", {
        "code": args.code,
        "file_path_hint": args.file_hint,
        "lang_hint": args.lang_hint,
    })
    _out(data)


def cmd_preview_smart(args) -> None:
    """Preview a smart block-based code edit (unified diff)."""
    data = _post("/preview-smart-edit", {
        "file": args.file,
        "new_code": args.new_code,
    })
    _out(data)


def cmd_apply_smart(args) -> None:
    """Apply a smart edit preview to disk and commit."""
    data = _post("/apply-smart-edit", {"edit_id": args.edit_id})
    _out(data)


def cmd_parse_blocks(args) -> None:
    """Parse pasted code into top-level blocks."""
    data = _post("/parse-blocks", {
        "code": args.code,
        "file_path_hint": args.file_hint,
        "lang_hint": args.lang_hint,
    })
    _out(data)


def cmd_imports(args) -> None:
    """Get all imports used by a file."""
    data = _get("/search/imports", file=args.file)
    _out(data)


def cmd_importers(args) -> None:
    """Find all files that import a given module."""
    data = _get("/search/importers", module=args.module)
    _out(data)


def cmd_file_deps(args) -> None:
    """Get complete dependency picture for a file — both directions."""
    data = _get("/search/file-deps", file=args.file)
    _out(data)


def cmd_edit_context(args) -> None:
    """Get all structured context required to edit a symbol."""
    data = _get("/search/edit-context",
                symbol=args.symbol,
                file=args.file,
                dir=args.dir,
                package=args.package)
    _out(data)


def cmd_semantic(args) -> None:
    """Find code by natural language description using embeddings."""
    data = _get("/search/semantic", q=args.query, limit=args.limit)
    _out(data)


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ce_cli.py",
        description="Code Search Engine CLI — for agent use via run_command",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ping
    sub.add_parser("ping", help="Check if the service is running")

    # symbol / search_symbol
    for cmd in ["symbol", "search_symbol"]:
        s = sub.add_parser(cmd, help="Search AST symbol index")
        s.add_argument("name",               help="Symbol name (partial match)")
        s.add_argument("--kind", default=None, help="Kind filter: function|class|method|interface")
        s.add_argument("--dir", default=None, help="Directory prefix filter")
        s.add_argument("--package", default=None, help="Package path filter")

    # overview / get_overview
    for cmd in ["overview", "get_overview"]:
        s = sub.add_parser(cmd, help="Full repo overview: symbols + call graph")
        s.add_argument("--files", nargs="*", default=None, metavar="FILE", help="Scope to specific files")
        s.add_argument("--dir", default=None, help="Directory prefix filter")
        s.add_argument("--package", default=None, help="Package path filter")

    # class / extract_class
    for cmd in ["class", "extract_class"]:
        s = sub.add_parser(cmd, help="Extract class source (tree-sitter)")
        s.add_argument("file", help="Relative file path")
        s.add_argument("name", help="Exact class name")

    # function / extract_function
    for cmd in ["function", "extract_function"]:
        s = sub.add_parser(cmd, help="Extract function source (tree-sitter)")
        s.add_argument("file", help="Relative file path (e.g. codeengine/app.py)")
        s.add_argument("name", help="Exact function name")

    # imports / get_imports
    for cmd in ["imports", "get_imports"]:
        s = sub.add_parser(cmd, help="Get all imports used by a file")
        s.add_argument("file", help="Relative file path")

    # callers / get_callers
    for cmd in ["callers", "get_callers"]:
        s = sub.add_parser(cmd, help="Who calls a given symbol?")
        s.add_argument("symbol_name", help="Exact symbol name")
        s.add_argument("--dir", default=None, help="Directory filter")
        s.add_argument("--package", default=None, help="Package filter")

    # callees / get_callees
    for cmd in ["callees", "get_callees"]:
        s = sub.add_parser(cmd, help="What does a symbol call internally?")
        s.add_argument("symbol_name", help="Exact symbol name")
        s.add_argument("--dir", default=None, help="Directory filter")
        s.add_argument("--package", default=None, help="Package filter")

    # importers / get_importers
    for cmd in ["importers", "get_importers"]:
        s = sub.add_parser(cmd, help="Find all files that import a given module")
        s.add_argument("module", help="Module name (e.g. utils.auth)")

    # file_deps / get_file_deps
    for cmd in ["file_deps", "get_file_deps"]:
        s = sub.add_parser(cmd, help="Get complete dependency picture for a file")
        s.add_argument("file", help="Relative file path")

    # edit_context / get_edit_context
    for cmd in ["edit_context", "get_edit_context"]:
        s = sub.add_parser(cmd, help="Get all structured context required to edit a symbol")
        s.add_argument("symbol", help="Name of symbol to edit")
        s.add_argument("--file", default=None, help="Optional relative file path filter")
        s.add_argument("--dir", default=None, help="Optional directory prefix filter")
        s.add_argument("--package", default=None, help="Optional package path filter")

    # semantic / semantic_search
    for cmd in ["semantic", "semantic_search"]:
        s = sub.add_parser(cmd, help="Find code by natural language description using embeddings")
        s.add_argument("query", help="Natural language description")
        s.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")

    return p


# ── Entry point ───────────────────────────────────────────────────────────────

HANDLERS = {
    "ping":             cmd_ping,
    "symbol":           cmd_symbol,
    "search_symbol":    cmd_symbol,
    "overview":         cmd_overview,
    "get_overview":     cmd_overview,
    "class":            cmd_class,
    "extract_class":    cmd_class,
    "function":         cmd_function,
    "extract_function": cmd_function,
    "imports":          cmd_imports,
    "get_imports":      cmd_imports,
    "callers":          cmd_callers,
    "get_callers":      cmd_callers,
    "callees":          cmd_callees,
    "get_callees":      cmd_callees,
    "importers":        cmd_importers,
    "get_importers":    cmd_importers,
    "file_deps":        cmd_file_deps,
    "get_file_deps":    cmd_file_deps,
    "edit_context":     cmd_edit_context,
    "get_edit_context": cmd_edit_context,
    "semantic":         cmd_semantic,
    "semantic_search":  cmd_semantic,
}

if __name__ == "__main__":
    parser = build_parser()
    args   = parser.parse_args()
    HANDLERS[args.command](args)