from fastapi import APIRouter, HTTPException
from typing import Optional
from pydantic import BaseModel

from codeengine.core.edit_engine import (
    preview_smart_edit,
    apply_smart_edit,
    undo_edit,
)
from codeengine.core.ast_engine import parse_blocks_from_code
from codeengine.models.edit_models import (
    SmartEditPreview,
    SmartEditResult,
    UndoResult,
)

router = APIRouter(tags=["edit"])


# ---------------------------------------------------------------------------
# Smart Endpoints (block-based editing)
# ---------------------------------------------------------------------------

class SmartEditRequest(BaseModel):
    file: str
    old_code: str
    new_code: str
    mode: str = "fuzzy"  # "fuzzy" or "ast"
    replace_all: bool = False  # fuzzy mode only: replace every match instead of erroring on ambiguity

class ApplySmartRequest(BaseModel):
    edit_id: str

@router.post("/preview-smart-edit", response_model=SmartEditPreview)
async def preview_smart(req: SmartEditRequest):
    """
    Generate a unified diff preview for smart code editing.
    mode="fuzzy" uses opencode-style string matching.
    mode="ast" uses tree-sitter block parsing with class-aware matching.
    replace_all=True (fuzzy mode only) replaces every occurrence of old_code
    instead of raising on multiple matches.
    """
    try:
        return await preview_smart_edit(
            req.file, req.old_code, req.new_code, req.mode, replace_all=req.replace_all
        )
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/apply-smart-edit", response_model=SmartEditResult)
async def apply_smart(req: ApplySmartRequest):
    """Apply a pending smart edit preview to disk and commit to git."""
    try:
        return await apply_smart_edit(req.edit_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Multi-block parsing endpoint (for multi-window editor UI)
# ---------------------------------------------------------------------------

class ParseBlocksRequest(BaseModel):
    code: str
    file_path_hint: Optional[str] = None
    lang_hint: Optional[str] = None

class ParsedBlock(BaseModel):
    kind: str          # function | class | import | constant | other
    name: Optional[str]
    source: str

class ParseBlocksResponse(BaseModel):
    blocks: list[ParsedBlock]
    lang: Optional[str]

@router.post("/parse-blocks", response_model=ParseBlocksResponse)
async def parse_blocks(req: ParseBlocksRequest):
    """
    Parse pasted code into top-level blocks (functions, classes, imports, etc.).
    Used by the multi-window editor to create one diff panel per block.
    """
    try:
        raw = parse_blocks_from_code(
            req.code,
            file_path_hint=req.file_path_hint,
            lang_hint=req.lang_hint,
        )
        blocks = [ParsedBlock(kind=k, name=n, source=s) for k, n, s in raw]
        # Try to figure out detected language
        lang = req.lang_hint
        if not lang and req.file_path_hint:
            from codeengine.core.ast_engine import detect_language
            lang = detect_language(req.file_path_hint)
        return ParseBlocksResponse(blocks=blocks, lang=lang)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Common Endpoints
# ---------------------------------------------------------------------------

@router.post("/undo", response_model=UndoResult)
async def undo():
    """Revert the last applied edit commit using git revert."""
    try:
        return await undo_edit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
