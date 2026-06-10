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
    .venv\Scripts\python.exe ce_cli.py ping
    .venv\Scripts\python.exe ce_cli.py search "pattern" [--path .] [--lang python] [--limit 50]
    .venv\Scripts\python.exe ce_cli.py symbol "name"   [--kind function|class|method|interface]
    .venv\Scripts\python.exe ce_cli.py file   "pattern" [--root .]
    .venv\Scripts\python.exe ce_cli.py function "rel/path/to/file.py" "FunctionName"
    .venv\Scripts\python.exe ce_cli.py class    "rel/path/to/file.py" "ClassName"
    .venv\Scripts\python.exe ce_cli.py index    [--files foo.py bar.py] [--dir src] [--package codeengine.core]
    .venv\Scripts\python.exe ce_cli.py overview [--files foo.py bar.py] [--dir src] [--package codeengine.core]
    .venv\Scripts\python.exe ce_cli.py callers  "symbol_name" [--dir src] [--package codeengine.core]
    .venv\Scripts\python.exe ce_cli.py callees  "symbol_name" [--dir src] [--package codeengine.core]
    .venv\Scripts\python.exe ce_cli.py signature "rel/path/to/file.py" 42 89
    .venv\Scripts\python.exe ce_cli.py body      "rel/path/to/file.py" 42 89
    .venv\Scripts\python.exe ce_cli.py detect    "def foo(): pass" [--file_hint x.py] [--lang_hint python]
    .venv\Scripts\python.exe ce_cli.py preview-smart "rel/path/to/file.py" "new_code"
    .venv\Scripts\python.exe ce_cli.py apply-smart "edit_id"
    .venv\Scripts\python.exe ce_cli.py parse-blocks "def foo(): pass" [--file_hint x.py] [--lang_hint python]
    .venv\Scripts\python.exe ce_cli.py edit-context "symbol_name" [--file x.py] [--dir src] [--package codeengine.core]
    .venv\Scripts\python.exe ce_cli.py imports "rel/path/to/file.py"
    .venv\Scripts\python.exe ce_cli.py importers "module.name"
    .venv\Scripts\python.exe ce_cli.py file-deps "rel/path/to/file.py"
    .venv\Scripts\python.exe ce_cli.py type-info "symbol_name" [--file x.py]
    .venv\Scripts\python.exe ce_cli.py defined-symbols "rel/path/to/file.py"
    .venv\Scripts\python.exe ce_cli.py count-refs "symbol_name"
    .venv\Scripts\python.exe ce_cli.py impact "symbol_name"
    .venv\Scripts\python.exe ce_cli.py trace "symbol_name" [--depth 5]
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
    except urllib.error.HTTPError as e:
        if e.code == 300:
            return json.loads(e.read())
        err = json.loads(e.read()).get("detail", e.reason)
        _die(f"API error {e.code}: {err}")
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
                package=args.package,
                q=args.q,
                limit=args.limit,
                offset=args.offset)
    _out(data)


def cmd_overview(args) -> None:
    """Get complete repo overview including call graph. Pass --files/--dir/--package to scope."""
    data = _get("/search/overview",
                files=args.files if args.files else None,
                dir=args.dir,
                package=args.package,
                q=args.q,
                limit=args.limit,
                offset=args.offset)
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


def cmd_edit_context(args) -> None:
    """Get all structured context required to edit a symbol."""
    params = {"symbol": args.symbol}
    if args.file:
        params["file"] = args.file
    if args.dir:
        params["dir"] = args.dir
    if args.package:
        params["package"] = args.package
    data = _get("/search/edit-context", **params)
    _out(data)


def cmd_imports(args) -> None:
    """Get all imports used by a file."""
    data = _get("/search/imports", file=args.file)
    _out(data)


def cmd_importers(args) -> None:
    """Get all files that import a given module (reverse dependency)."""
    data = _get("/search/importers", module=args.module)
    _out(data)


def cmd_file_deps(args) -> None:
    """Get complete dependency picture for a file (both directions)."""
    data = _get("/search/file-deps", file=args.file)
    _out(data)


def cmd_type_info(args) -> None:
    """Get parameter types and return type for a symbol."""
    data = _get("/search/type-info", symbol_name=args.symbol_name, file=args.file)
    _out(data)


def cmd_defined_symbols(args) -> None:
    """Get all symbols defined in a file."""
    data = _get("/search/defined-symbols", file=args.file)
    _out(data)


def cmd_count_refs(args) -> None:
    """Count how many times a symbol is referenced."""
    data = _get("/search/count-references", symbol_name=args.symbol_name)
    _out(data)


def cmd_impact(args) -> None:
    """Full impact assessment — callers, references, affected files."""
    data = _get("/search/impact-analysis", symbol_name=args.symbol_name)
    _out(data)


def cmd_trace(args) -> None:
    """Trace execution flow through the application."""
    data = _get("/search/trace-execution", symbol_name=args.symbol_name, max_depth=args.max_depth)
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

    # search
    s = sub.add_parser("search", help="Search code with ripgrep")
    s.add_argument("query",               help="Search pattern or text")
    s.add_argument("--path",  default=".", help="Root directory (default: .)")
    s.add_argument("--lang",  default=None,
                   help="Language filter: python|javascript|typescript|java|go|rust")
    s.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")

    # symbol
    s = sub.add_parser("symbol", help="Search AST symbol index")
    s.add_argument("name",               help="Symbol name (partial match)")
    s.add_argument("--kind", default=None,
                   help="Kind filter: function|class|method|interface")

    # file
    s = sub.add_parser("file", help="Find files by name pattern (fd)")
    s.add_argument("pattern",             help="Filename pattern")
    s.add_argument("--root", default=".", help="Root directory (default: .)")

    # function
    s = sub.add_parser("function", help="Extract function source (tree-sitter)")
    s.add_argument("file", help="Relative file path (e.g. codeengine/app.py)")
    s.add_argument("name", help="Exact function name")

    # class
    s = sub.add_parser("class", help="Extract class source (tree-sitter)")
    s.add_argument("file", help="Relative file path")
    s.add_argument("name", help="Exact class name")

    # preview-edit
    s = sub.add_parser("preview", help="Preview a code edit (unified diff)")
    s.add_argument("file",     help="Relative file path")
    s.add_argument("old_code", help="Exact code block to replace")
    s.add_argument("new_code", help="Replacement code")

    # apply-edit
    s = sub.add_parser("apply", help="Apply a previewed edit + git commit")
    s.add_argument("edit_id", help="edit_id from the preview response")

    # undo
    sub.add_parser("undo", help="Revert last applied edit (git revert HEAD)")

    # index
    s = sub.add_parser("index", help="Get file + symbol index (no file reads)")
    s.add_argument("--files", nargs="*", default=None,
                   metavar="FILE",
                   help="Scope to specific files (omit for full repo)")
    s.add_argument("--dir", default=None,
                   help="Directory prefix filter (e.g. src/core)")
    s.add_argument("--package", default=None,
                   help="Package path filter (e.g. codeengine.core)")
    s.add_argument("--q", default=None,
                   help="Substring match on file path")
    s.add_argument("--limit", type=int, default=50,
                   help="Max files to return (default: 50)")
    s.add_argument("--offset", type=int, default=0,
                   help="Number of files to skip (default: 0)")

    # overview
    s = sub.add_parser("overview", help="Full repo overview: symbols + call graph")
    s.add_argument("--files", nargs="*", default=None,
                   metavar="FILE",
                   help="Scope to specific files (omit for full repo)")
    s.add_argument("--dir", default=None,
                   help="Directory prefix filter (e.g. src/core)")
    s.add_argument("--package", default=None,
                   help="Package path filter (e.g. codeengine.core)")
    s.add_argument("--q", default=None,
                   help="Substring match on file path")
    s.add_argument("--limit", type=int, default=50,
                   help="Max files to return (default: 50)")
    s.add_argument("--offset", type=int, default=0,
                   help="Number of files to skip (default: 0)")

    # callers
    s = sub.add_parser("callers", help="Who calls a given symbol?")
    s.add_argument("symbol_name", help="Exact symbol name")

    # callees
    s = sub.add_parser("callees", help="What does a symbol call internally?")
    s.add_argument("symbol_name", help="Exact symbol name")

    # signature
    s = sub.add_parser("signature", help="Get function signature + docstring only")
    s.add_argument("file",       help="Relative file path")
    s.add_argument("line_start", type=int, help="First line of the function")
    s.add_argument("line_end",   type=int, help="Last line of the function")

    # body
    s = sub.add_parser("body", help="Get full function body (exact lines, no noise)")
    s.add_argument("file",       help="Relative file path")
    s.add_argument("line_start", type=int, help="First line of the function")
    s.add_argument("line_end",   type=int, help="Last line of the function")

    # detect
    s = sub.add_parser("detect", help="Detect original source block of a code snippet")
    s.add_argument("code", help="Code snippet")
    s.add_argument("--file_hint", default=None, help="Optional file path hint")
    s.add_argument("--lang_hint", default=None, help="Optional language hint")

    # preview-smart
    s = sub.add_parser("preview-smart", help="Preview a smart block-based code edit")
    s.add_argument("file", help="Relative file path")
    s.add_argument("new_code", help="New code blocks to apply")

    # apply-smart
    s = sub.add_parser("apply-smart", help="Apply a smart edit preview")
    s.add_argument("edit_id", help="edit_id from the preview-smart response")

    # parse-blocks
    s = sub.add_parser("parse-blocks", help="Parse pasted code into top-level blocks")
    s.add_argument("code", help="Code snippet")
    s.add_argument("--file_hint", default=None, help="Optional file path hint")
    s.add_argument("--lang_hint", default=None, help="Optional language hint")

    # edit-context
    s = sub.add_parser("edit-context", help="Get all context needed to edit a symbol")
    s.add_argument("symbol", help="Symbol name to get context for")
    s.add_argument("--file", default=None, help="Optional file path filter")
    s.add_argument("--dir", default=None, help="Optional directory prefix filter")
    s.add_argument("--package", default=None, help="Optional package path filter")

    # imports
    s = sub.add_parser("imports", help="Get all imports used by a file")
    s.add_argument("file", help="Relative file path")

    # importers
    s = sub.add_parser("importers", help="Get all files that import a module (reverse dependency)")
    s.add_argument("module", help="Module name (e.g. utils.auth)")

    # file-deps
    s = sub.add_parser("file-deps", help="Get full dependency picture for a file")
    s.add_argument("file", help="Relative file path")

    # type-info
    s = sub.add_parser("type-info", help="Get parameter types and return type for a symbol")
    s.add_argument("symbol_name", help="Symbol name")
    s.add_argument("--file", default=None, help="Optional file path filter")

    # defined-symbols
    s = sub.add_parser("defined-symbols", help="Get all symbols defined in a file")
    s.add_argument("file", help="Relative file path")

    # count-refs
    s = sub.add_parser("count-refs", help="Count how many times a symbol is referenced")
    s.add_argument("symbol_name", help="Symbol name")

    # impact
    s = sub.add_parser("impact", help="Full impact assessment for a symbol")
    s.add_argument("symbol_name", help="Symbol name")

    # trace
    s = sub.add_parser("trace", help="Trace execution flow through the application")
    s.add_argument("symbol_name", help="Symbol name")
    s.add_argument("--depth", type=int, default=5, help="Max call chain depth (default: 5)")

    return p


# ── Entry point ───────────────────────────────────────────────────────────────

HANDLERS = {
    "ping":             cmd_ping,
    "search":           cmd_search,
    "symbol":           cmd_symbol,
    "file":             cmd_file,
    "function":         cmd_function,
    "class":            cmd_class,
    "preview":          cmd_preview,
    "apply":            cmd_apply,
    "undo":             cmd_undo,
    "index":            cmd_index,
    "overview":         cmd_overview,
    "callers":          cmd_callers,
    "callees":          cmd_callees,
    "signature":        cmd_signature,
    "body":             cmd_body,
    "detect":           cmd_detect,
    "preview-smart":    cmd_preview_smart,
    "apply-smart":      cmd_apply_smart,
    "parse-blocks":     cmd_parse_blocks,
    "edit-context":     cmd_edit_context,
    "imports":          cmd_imports,
    "importers":        cmd_importers,
    "file-deps":        cmd_file_deps,
    "type-info":        cmd_type_info,
    "defined-symbols":  cmd_defined_symbols,
    "count-refs":       cmd_count_refs,
    "impact":           cmd_impact,
    "trace":            cmd_trace,
}

if __name__ == "__main__":
    parser = build_parser()
    args   = parser.parse_args()
    HANDLERS[args.command](args)