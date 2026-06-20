from fastapi import APIRouter, Query, HTTPException, status
from fastapi.responses import JSONResponse
from codeengine.core.search_engine import (
    search_code, search_symbol, find_file,
    get_index, get_callers, get_callees, get_repo_overview,
    get_function_signature, get_function_body,
    find_symbol_usages, get_docstring,
    get_file_imports, get_importers, get_file_deps,
    get_type_info, get_defined_symbols, count_references,
    impact_analysis, trace_execution, get_edit_context,
    get_blast_radius, get_error_context, trace_endpoint_flow,
)
from codeengine.core.git_engine import get_function_history
from codeengine.core.ast_engine import get_function, get_class, parse_code_string
from codeengine.models.search_models import SearchResponse, Symbol, FunctionResult
from pydantic import BaseModel
import os
import time
import asyncio
from pathlib import Path

router = APIRouter(prefix="/search", tags=["search"])

@router.get("/code", response_model=SearchResponse)
async def search_code_route(
    q: str = Query(..., description="search query"),
    path: str = Query(".", description="root path"),
    lang: str | None = Query(None),
    limit: int = Query(50)
):
    """Search for matching patterns in files using ripgrep."""
    matches = await search_code(q, path, lang, limit)
    return SearchResponse(matches=matches, total=len(matches), query=q)

@router.get("/symbol", response_model=list[Symbol])
async def search_symbol_route(
    name: str,
    kind: str | None = None,
    file: str | None = Query(None, description="File path filter"),
    dir: str | None = Query(None, description="Directory prefix filter"),
    package: str | None = Query(None, description="Package path filter"),
):
    """Search for matching symbols in the SQLite DB."""
    file_filter = [file] if file else None
    return await search_symbol(name, kind, file_filter=file_filter, dir_filter=dir, package_filter=package)

@router.get("/file", response_model=list[str])
async def find_file_route(pattern: str = Query("", description="file pattern"), root: str = Query(".", description="root path")):
    """Find files using the fd CLI."""
    return await find_file(pattern, root)

@router.get("/function", response_model=FunctionResult)
async def get_function_route(file: str, name: str):
    """Extract code block and source for a specific function/method by name."""
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    full_path = str((repo_root / file).resolve())
    result = get_function(full_path, name)
    if not result:
        raise HTTPException(status_code=404, detail="Function not found")
    result.file = file
    return result

@router.get("/class", response_model=FunctionResult)
async def get_class_route(file: str, name: str):
    """Extract code block and source for a specific class by name."""
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    full_path = str((repo_root / file).resolve())
    result = get_class(full_path, name)
    if not result:
        raise HTTPException(status_code=404, detail="Class not found")
    result.file = file
    return result

@router.get("/file-read")
async def read_file_content(file: str):
    """Read full content of a file relative to REPO_PATH."""
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    file_path = (repo_root / file).resolve()
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File '{file}' not found.")
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return {"file": file, "content": f.read()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/index")
async def get_index_route(
    files: list[str] = Query(None),
    dir: str | None = Query(None, description="Directory prefix filter"),
    package: str | None = Query(None, description="Package path filter"),
    q: str | None = Query(None, description="Substring match on file path"),
    limit: int = Query(50, description="Max number of files to return"),
    offset: int = Query(0, description="Number of files to skip"),
):
    """Get file and symbol index for the repository."""
    try:
        return await get_index(
            files=files,
            dir_filter=dir,
            package_filter=package,
            query_filter=q,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
@router.get("/callers")
async def get_callers_route(
    symbol_name: str = Query(...),
    file: str | None = Query(None, description="File path filter"),
    dir: str | None = Query(None, description="Directory prefix filter"),
    package: str | None = Query(None, description="Package path filter"),
):
    """Get all functions that call the given symbol."""
    try:
        file_filter = [file] if file else None
        return await get_callers(symbol_name, file_filter=file_filter, dir_filter=dir, package_filter=package)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/callees")
async def get_callees_route(
    symbol_name: str = Query(...),
    file: str | None = Query(None, description="File path filter"),
    dir: str | None = Query(None, description="Directory prefix filter"),
    package: str | None = Query(None, description="Package path filter"),
):
    """Get all functions called by the given symbol."""
    try:
        file_filter = [file] if file else None
        return await get_callees(symbol_name, file_filter=file_filter, dir_filter=dir, package_filter=package)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/overview")
async def get_overview_route(
    files: list[str] = Query(None),
    dir: str | None = Query(None, description="Directory prefix filter (e.g. 'src/core')"),
    package: str | None = Query(None, description="Package path filter (e.g. 'codeengine.core')"),
    q: str | None = Query(None, description="Substring match on file path"),
    limit: int = Query(50, description="Max number of files to return"),
    offset: int = Query(0, description="Number of files to skip"),
):
    """Get compact file listing + call graph edges. Requires at least one filter."""
    try:
        return await get_repo_overview(
            files=files,
            dir_filter=dir,
            package_filter=package,
            query_filter=q,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/function-signature")
async def get_function_signature_route(file: str = Query(...), line_start: int = Query(...), line_end: int = Query(...)):
    """Get signature and docstring for a function without reading the full body."""
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    full_path = str((repo_root / file).resolve())
    try:
        return await get_function_signature(full_path, line_start, line_end)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404 if isinstance(e, FileNotFoundError) else 400, detail=str(e))

@router.get("/function-body")
async def get_function_body_route(file: str = Query(...), line_start: int = Query(...), line_end: int = Query(...)):
    """Get full function body."""
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    full_path = str((repo_root / file).resolve())
    try:
        return await get_function_body(full_path, line_start, line_end)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404 if isinstance(e, FileNotFoundError) else 400, detail=str(e))


@router.get("/usages")
async def find_symbol_usages_route(symbol_name: str = Query(...), limit: int = Query(50)):
    """Find all places where a symbol is referenced (used) in the codebase."""
    try:
        return await find_symbol_usages(symbol_name, limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/docstring")
async def get_docstring_route(symbol_name: str = Query(...), file: str | None = Query(None)):
    """Retrieve docstrings for a symbol, optionally filtered by file."""
    try:
        return await get_docstring(symbol_name, file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/imports")
async def get_imports_route(file: str = Query(..., description="Relative file path")):
    """Get all imports used by a file."""
    try:
        return await get_file_imports(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/importers")
async def get_importers_route(module: str = Query(..., description="Module name to search for")):
    """Get all files that import a given module (reverse dependency lookup)."""
    try:
        return await get_importers(module)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/file-deps")
async def get_file_deps_route(file: str = Query(..., description="Relative file path")):
    """Get complete dependency picture for a file — both directions."""
    try:
        return await get_file_deps(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/type-info")
async def get_type_info_route(
    symbol_name: str = Query(..., description="Symbol name to get type info for"),
    file: str | None = Query(None, description="Optional file path filter"),
):
    """Get parameter types and return type for a symbol."""
    try:
        return await get_type_info(symbol_name, file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/defined-symbols")
async def get_defined_symbols_route(file: str = Query(..., description="Relative file path")):
    """Get all symbols defined in a file (functions, classes, methods, constants)."""
    try:
        return await get_defined_symbols(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/count-references")
async def count_references_route(symbol_name: str = Query(..., description="Symbol name")):
    """Count how many times a symbol is referenced across the codebase."""
    try:
        return await count_references(symbol_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/impact-analysis")
async def impact_analysis_route(symbol_name: str = Query(..., description="Symbol name")):
    """Full impact assessment — direct callers, references, and affected files."""
    try:
        return await impact_analysis(symbol_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/trace-execution")
async def trace_execution_route(
    symbol_name: str = Query(..., description="Symbol name to trace"),
    max_depth: int = Query(5, description="Maximum call chain depth"),
):
    """Trace execution flow through the application from a given symbol."""
    try:
        return await trace_execution(symbol_name, max_depth)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/edit-context")
async def get_edit_context_route(
    symbol: str = Query(..., description="Symbol name to get context for"),
    file: str | None = Query(None, description="Optional relative file path filter"),
    dir: str | None = Query(None, description="Optional directory prefix filter"),
    package: str | None = Query(None, description="Optional package path filter"),
):
    """Get all structured context required to edit a symbol without reading the whole file."""
    try:
        res = await get_edit_context(
            symbol_name=symbol,
            file=file,
            dir_filter=dir,
            package_filter=package,
        )
        if isinstance(res, list):
            # Multiple candidates found - return 300 Multiple Choices
            return JSONResponse(
                status_code=status.HTTP_300_MULTIPLE_CHOICES,
                content={
                    "detail": f"Multiple symbols found matching '{symbol}'. Please specify a file.",
                    "candidates": res
                }
            )
        return res
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e) else 400, detail=str(e))



class DetectOriginalRequest(BaseModel):
    code: str
    file_path_hint: str | None = None
    lang_hint: str | None = None

class DetectOriginalResponse(BaseModel):
    found: bool
    file: str | None = None
    name: str | None = None
    kind: str | None = None
    source: str | None = None

@router.post("/detect-original", response_model=DetectOriginalResponse)
async def detect_original_route(body: DetectOriginalRequest):
    """
    Parse a pasted snippet of code, find the function/class defined in it,
    search the indexed symbols to locate its file, and return the original definition.
    """
    symbols = parse_code_string(body.code, body.file_path_hint, body.lang_hint)
    if not symbols:
        return DetectOriginalResponse(found=False)

    # Pick the first function, method, or class symbol
    target = None
    for sym in symbols:
        if sym.kind in ("function", "method", "class"):
            target = sym
            break
            
    if not target:
        return DetectOriginalResponse(found=False)

    # Search for this symbol in the indexed database
    matches = await search_symbol(name=target.name, kind=target.kind, limit=5)
    if not matches:
        # If it was a method or has a generic search, try search without strict kind or check functions
        if target.kind == "method":
            matches = await search_symbol(name=target.name, kind="function", limit=5)
        if not matches:
            matches = await search_symbol(name=target.name, limit=5)

    if not matches:
        return DetectOriginalResponse(found=False)

    # If file_path_hint is provided, prefer the file that matches or is closest
    best_match = matches[0]
    if body.file_path_hint:
        normalized_hint = body.file_path_hint.replace("\\", "/").lower()
        for m in matches:
            if m.file.replace("\\", "/").lower() in normalized_hint or normalized_hint in m.file.replace("\\", "/").lower():
                best_match = m
                break

    # Load original source
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    full_path = str((repo_root / best_match.file).resolve())
    
    orig_res = None
    if best_match.kind == "class":
        orig_res = get_class(full_path, best_match.name)
    else:
        orig_res = get_function(full_path, best_match.name)

    if not orig_res:
        return DetectOriginalResponse(found=False)

    return DetectOriginalResponse(
        found=True,
        file=best_match.file,
        name=best_match.name,
        kind=best_match.kind,
        source=orig_res.source
    )


# ── Embedding Endpoints ────────────────────────────────────────────────────

from codeengine.core.embedding_engine import get_status, encode_text, encode_batch, update_status

@router.get("/embedding-status")
async def embedding_status_route():
    """Get current embedding status."""
    return get_status()


class EmbeddingToggleRequest(BaseModel):
    enabled: bool

@router.post("/embedding-toggle")
async def embedding_toggle_route(body: EmbeddingToggleRequest):
    """Enable or disable embedding generation."""
    update_status(enabled=body.enabled)
    
    if body.enabled:
        # Start embedding in background
        import asyncio
        asyncio.create_task(_run_embedding())
    
    return {"status": "ok", "enabled": body.enabled}


def _extract_docstring(source: str, lang: str) -> str:
    """Extract docstring/comment from source code based on language."""
    lines = source.split('\n')
    
    # Language-specific patterns
    patterns = {
        'python': [
            ('"""', '"""'),  # Triple double quote
            ("'''", "'''"),  # Triple single quote
        ],
        'javascript': [
            ('/**', '*/'),   # JSDoc
            ('/*', '*/'),    # Block comment
        ],
        'typescript': [
            ('/**', '*/'),   # JSDoc
            ('/*', '*/'),    # Block comment
        ],
        'java': [
            ('/**', '*/'),   # Javadoc
            ('/*', '*/'),    # Block comment
        ],
        'go': [
            ('/*', '*/'),    # Block comment
            ('//', '\n'),    # Single line comment (take all until non-comment)
        ],
        'rust': [
            ('///', '\n'),   # Doc comment
            ('//!', '\n'),   # Module doc comment
            ('/*', '*/'),    # Block comment
        ],
    }
    
    # Get patterns for this language (fallback to python-style)
    lang_patterns = patterns.get(lang, patterns['python'])
    
    for i, line in enumerate(lines[:15]):
        stripped = line.strip()
        
        for start_marker, end_marker in lang_patterns:
            if start_marker in stripped:
                # Found start of docstring/comment
                start_idx = stripped.index(start_marker) + len(start_marker)
                
                # Check if it's single-line
                remaining = stripped[start_idx:]
                if end_marker in remaining:
                    # Single-line docstring
                    end_idx = remaining.index(end_marker)
                    return remaining[:end_idx].strip()
                
                # Multi-line: collect lines until end marker
                doc_lines = [remaining]
                for j in range(i + 1, min(i + 15, len(lines))):
                    next_line = lines[j]
                    if end_marker in next_line:
                        end_idx = next_line.index(end_marker)
                        doc_lines.append(next_line[:end_idx])
                        break
                    doc_lines.append(next_line)
                
                return ' '.join(l.strip() for l in doc_lines if l.strip())
        
        # Stop if we hit non-comment, non-empty line
        if stripped and not stripped.startswith('//') and not stripped.startswith('/*') and not stripped.startswith('*'):
            break
    
    return ""


async def _run_embedding():
    """Background task to generate embeddings for all symbols."""
    from codeengine.database.sqlite import get_db
    from codeengine.core.embedding_engine import encode_text, update_status
    from codeengine.core.ast_engine import get_function, get_class
    
    update_status(embedding=0, total=0, current_file="Starting...")
    
    try:
        async with get_db() as db:
            # Get all symbols with source code
            async with db.execute("""
                SELECT s.id, s.name, s.kind, s.line_start, s.line_end, f.path, f.lang
                FROM symbols s
                JOIN files f ON s.file_id = f.id
                WHERE s.kind IN ('function', 'class', 'method')
            """) as cursor:
                rows = await cursor.fetchall()
                
            total = len(rows)
            update_status(total=total, embedded_count=0)
            
            repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
            
            for i, row in enumerate(rows):
                # Check if disabled
                status = get_status()
                if not status.get("enabled"):
                    update_status(current_file="Stopped by user")
                    return
                
                symbol_id = row["id"]
                name = row["name"]
                kind = row["kind"]
                file_path = row["path"]
                lang = row["lang"] or "python"
                
                # Build text for embedding: name + docstring + first N lines
                text_parts = [f"{kind} {name}"]
                
                # Try to get source code
                try:
                    full_path = str((repo_root / file_path).resolve())
                    
                    if kind == "class":
                        result = get_class(full_path, name)
                    else:
                        result = get_function(full_path, name)
                    
                    if result and result.source:
                        source = result.source
                        
                        # Extract docstring based on language
                        docstring = _extract_docstring(source, lang)
                        if docstring:
                            text_parts.append(docstring)
                        
                        # Add first N lines of code (skip def/class line)
                        lines = source.split('\n')
                        code_start = 1
                        code_lines = lines[code_start:code_start + 5]  # First 5 lines
                        code_text = ' '.join(l.strip() for l in code_lines if l.strip())
                        if code_text:
                            text_parts.append(code_text)
                            
                except Exception as e:
                    # Fallback: just use name
                    pass
                
                # Combine all parts
                text = ' '.join(text_parts)
                
                # Encode
                embedding = encode_text(text)
                if embedding:
                    # Upsert into embeddings table
                    await db.execute("""
                        INSERT OR REPLACE INTO embeddings (symbol_id, embedding, model, created_at)
                        VALUES (?, ?, ?, ?)
                    """, (symbol_id, embedding, "BAAI/bge-small-en-v1.5", time.time()))
                
                update_status(
                    embedded_count=i + 1,
                    current_file=f"{file_path}::{name}"
                )
                
                # Yield control periodically
                if i % 10 == 0:
                    await asyncio.sleep(0)
            
            await db.commit()
            update_status(current_file="Done", enabled=False)
            
    except Exception as e:
        update_status(error=str(e), current_file="Error")


@router.get("/semantic")
async def semantic_search_route(
    q: str = Query(..., description="Natural language query"),
    limit: int = Query(10, description="Max results"),
):
    """Natural language code search using embeddings."""
    from codeengine.core.embedding_engine import encode_text, cosine_distance, get_status
    from codeengine.database.sqlite import get_db
    
    status = get_status()
    if status.get("loading"):
        raise HTTPException(status_code=408, detail="Model is loading, please wait")
    
    # Check if any embeddings exist
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM embeddings") as cursor:
            count = (await cursor.fetchone())[0]
            if count == 0:
                raise HTTPException(status_code=404, detail="No embeddings found. Enable embeddings in the Index page first.")
    
    # Encode query
    query_vec = encode_text(q)
    if not query_vec:
        raise HTTPException(status_code=500, detail="Failed to encode query")
    
    # Search
    async with get_db() as db:
        async with db.execute("""
            SELECT e.symbol_id, e.embedding, s.name, s.kind, f.path,
                   s.line_start, s.line_end
            FROM embeddings e
            JOIN symbols s ON e.symbol_id = s.id
            JOIN files f ON s.file_id = f.id
        """) as cursor:
            rows = await cursor.fetchall()
        
        # Compute distances
        results = []
        for row in rows:
            dist = cosine_distance(query_vec, row["embedding"])
            results.append({
                "symbol_id": row["symbol_id"],
                "name": row["name"],
                "kind": row["kind"],
                "file": row["path"],
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "distance": dist,
            })
        
        # Sort by distance
        results.sort(key=lambda x: x["distance"])
        
        return {"query": q, "results": results[:limit]}


@router.get("/similar")
async def find_similar_route(
    symbol: str = Query(..., description="Symbol name to find similar to"),
    file: str | None = Query(None, description="File path filter"),
    limit: int = Query(5, description="Max results"),
):
    """Find symbols with similar behavior by embedding distance."""
    from codeengine.core.embedding_engine import cosine_distance, get_status
    from codeengine.database.sqlite import get_db
    
    status = get_status()
    if status.get("loading"):
        raise HTTPException(status_code=408, detail="Model is loading, please wait")
    
    async with get_db() as db:
        # Find the target symbol
        query = "SELECT s.id, e.embedding FROM symbols s JOIN embeddings e ON s.id = e.symbol_id WHERE s.name = ?"
        params = [symbol]
        if file:
            query += " AND s.file_id = (SELECT id FROM files WHERE path = ?)"
            params.append(file)
        
        async with db.execute(query, params) as cursor:
            target = await cursor.fetchone()
        
        if not target:
            raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found or has no embedding")
        
        target_id = target["id"]
        target_vec = target["embedding"]
        
        # Find similar
        async with db.execute("""
            SELECT e.symbol_id, e.embedding, s.name, s.kind, f.path,
                   s.line_start, s.line_end
            FROM embeddings e
            JOIN symbols s ON e.symbol_id = s.id
            JOIN files f ON s.file_id = f.id
            WHERE e.symbol_id != ?
        """, (target_id,)) as cursor:
            rows = await cursor.fetchall()
        
        # Compute distances
        results = []
        for row in rows:
            dist = cosine_distance(target_vec, row["embedding"])
            results.append({
                "symbol_id": row["symbol_id"],
                "name": row["name"],
                "kind": row["kind"],
                "file": row["path"],
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "distance": dist,
            })
        
        # Sort by distance
        results.sort(key=lambda x: x["distance"])
        
        return {"symbol": symbol, "results": results[:limit]}


# ── Feature 1: Blast Radius ────────────────────────────────────────────────────

@router.get("/blast-radius")
async def blast_radius_route(symbol: str = Query(..., description="Symbol name")):
    """Return precomputed transitive blast radius for a symbol. O(1) lookup."""
    return await get_blast_radius(symbol)


# ── Feature 2: Error Diagnostic Bundle ────────────────────────────────────────

@router.get("/error-context")
async def error_context_route(
    error: str = Query(..., description="The full error message text"),
    file: str = Query(..., description="Relative file path where the error occurred"),
    line: int = Query(..., description="Line number of the error"),
):
    """
    Return a pre-packaged diagnostic bundle for a compiler/linter error.
    Includes type signatures, enclosing function, imports, and callers.
    """
    return await get_error_context(error, file, line)


# ── Feature 3: Git Function History ───────────────────────────────────────────

@router.get("/function-history")
async def function_history_route(
    symbol: str = Query(..., description="Function or method name"),
    limit: int = Query(20, description="Max number of commits to return"),
):
    """Return precomputed git change history for a symbol."""
    return await get_function_history(symbol, limit)


# ── Feature 4: Endpoint Flow Trace ────────────────────────────────────────────

@router.get("/endpoint-flow")
async def endpoint_flow_route(
    entry: str = Query(..., description="Entry point function name or partial name"),
    max_depth: int = Query(8, description="Maximum call chain depth"),
):
    """Trace execution flow from an entry point function through all callees."""
    return await trace_endpoint_flow(entry, max_depth)
