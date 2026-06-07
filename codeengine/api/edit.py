from fastapi import APIRouter, HTTPException
from codeengine.core.edit_engine import (
    preview_edit,
    apply_edit,
    preview_smart_edit,
    apply_smart_edit,
    undo_edit,
)
from codeengine.models.edit_models import (
    EditRequest,
    EditPreview,
    ApplyRequest,
    ApplyResult,
    SmartEditPreview,
    SmartEditResult,
    UndoResult,
)

router = APIRouter(tags=["edit"])


# ---------------------------------------------------------------------------
# Legacy Endpoints (backward compatibility)
# ---------------------------------------------------------------------------

@router.post("/preview-edit", response_model=EditPreview)
async def preview(req: EditRequest):
    """Generate a unified diff preview for the proposed code edit (simple string replacement)."""
    try:
        return await preview_edit(req)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/apply-edit", response_model=ApplyResult)
async def apply(req: ApplyRequest):
    """Apply a pending preview edit to disk and commit to git."""
    try:
        return await apply_edit(req.edit_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# New Endpoints (smart block-based editing)
# ---------------------------------------------------------------------------

@router.post("/preview-smart-edit", response_model=SmartEditPreview)
async def preview_smart(file: str, new_code: str):
    """
    Generate a unified diff preview for smart block-based code editing.
    Parses new_code into blocks (functions, classes, imports, constants)
    and applies each onto the existing file intelligently.
    """
    try:
        return await preview_smart_edit(file, new_code)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/apply-smart-edit", response_model=SmartEditResult)
async def apply_smart(edit_id: str):
    """Apply a pending smart edit preview to disk and commit to git."""
    try:
        return await apply_smart_edit(edit_id)
    except (FileNotFoundError, ValueError) as e:
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
