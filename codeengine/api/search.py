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
)
from codeengine.core.ast_engine import get_function, get_class, parse_code_string
from codeengine.models.search_models import SearchResponse, Symbol, FunctionResult
from pydantic import BaseModel
import os
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
    """Get a complete overview of the repository including call edges."""
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


