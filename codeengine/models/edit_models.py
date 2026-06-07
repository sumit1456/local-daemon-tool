from pydantic import BaseModel
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Legacy Models (backward compatibility)
# ---------------------------------------------------------------------------

class EditRequest(BaseModel):
    """Schema representing a request to modify code in a file."""
    file: str                    # relative path from repo root
    old_code: str                # exact string to replace
    new_code: str                # replacement string

class EditPreview(BaseModel):
    """Schema representing the preview of a proposed code edit."""
    edit_id: str                 # ULID — store this to apply later
    file: str
    diff: str                    # unified diff as a string
    lines_changed: int

class ApplyRequest(BaseModel):
    """Schema representing a request to apply a stored preview edit."""
    edit_id: str

class ApplyResult(BaseModel):
    """Schema representing the result of applying an edit and committing to git."""
    edit_id: str
    file: str
    commit_hash: str

class UndoResult(BaseModel):
    """Schema representing the result of reverting the last edit commit."""
    reverted_commit: str
    message: str

class WorkerResult(BaseModel):
    """Schema representing the execution results of a background container task."""
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


# ---------------------------------------------------------------------------
# Smart Edit Models (new block-based editing)
# ---------------------------------------------------------------------------

@dataclass
class CodeBlock:
    """A named top-level block parsed from the new code."""
    kind: str           # "function" | "class" | "import" | "constant" | "other"
    name: str | None    # None for bare imports / module-level statements
    source: str         # full source text of this block


@dataclass
class BlockResult:
    """Outcome of applying one block."""
    kind: str
    name: str | None
    action: str         # "replaced" | "added" | "skipped"
    detail: str = ""


@dataclass
class SmartEditPreview(BaseModel):
    edit_id: str
    file: str
    diff: str
    lines_changed: int
    blocks: list[BlockResult]


@dataclass
class SmartEditResult(BaseModel):
    edit_id: str
    file: str
    commit_hash: str
    blocks: list[BlockResult]
