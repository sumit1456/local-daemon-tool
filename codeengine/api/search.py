from fastapi import APIRouter, Query, HTTPException
from codeengine.core.search_engine import (
    search_code, search_symbol, find_file,
    get_index, get_callers, get_callees, get_repo_overview,
    get_function_signature, get_function_body
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
async def search_symbol_route(name: str, kind: str | None = None):
    """Search for matching symbols in the SQLite DB."""
    return await search_symbol(name, kind)

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
async def get_index_route(files: list[str] = Query(None)):
    """Get file and symbol index for the repository."""
    try:
        return await get_index(files)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/callers")
async def get_callers_route(symbol_name: str = Query(...)):
    """Get all functions that call the given symbol."""
    try:
        return await get_callers(symbol_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/callees")
async def get_callees_route(symbol_name: str = Query(...)):
    """Get all functions called by the given symbol."""
    try:
        return await get_callees(symbol_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/overview")
async def get_overview_route(files: list[str] = Query(None)):
    """Get a complete overview of the repository including call edges."""
    try:
        return await get_repo_overview(files)
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


