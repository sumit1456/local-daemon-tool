import os
import time
import difflib
import git
import ulid
from pathlib import Path

from codeengine.database.sqlite import get_db
from codeengine.models.edit_models import EditRequest, EditPreview, ApplyResult, UndoResult

# In-memory store of pending (not yet applied) edits
# Key: edit_id (ULID string), Value: EditRequest
_pending: dict[str, EditRequest] = {}

def _get_repo(path: str = ".") -> git.Repo:
    """Return gitpython Repo object searching upward from path. Raise if not a git repo."""
    try:
        return git.Repo(path, search_parent_directories=True)
    except git.InvalidGitRepositoryError:
        raise ValueError(f"Directory '{path}' is not a git repository.")

def _find_repo_for_root(root: Path) -> git.Repo:
    """
    Find a git repo starting from root.
    First tries root itself (search_parent_directories=True goes upward).
    If that fails, walks child directories to find a .git folder.
    Returns the first git.Repo found.
    """
    # Try root itself first (handles case where root IS the git repo)
    try:
        return git.Repo(str(root), search_parent_directories=True)
    except git.InvalidGitRepositoryError:
        pass
    
    # Walk one level deep to find a child git repo (e.g. pdf-editor/pdf-editor-service/.git)
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / ".git").exists():
            return git.Repo(str(child))
    
    # Walk two levels deep as a last resort
    for child in sorted(root.iterdir()):
        if child.is_dir():
            for grandchild in sorted(child.iterdir()):
                if grandchild.is_dir() and (grandchild / ".git").exists():
                    return git.Repo(str(grandchild))
    
    raise ValueError(f"No git repository found in or under '{root}'.")

async def preview_edit(req: EditRequest) -> EditPreview:
    """
    Read file contents. Compute unified diff.
    Store the pending edit in memory and in the database edits table.
    """
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    file_path = (repo_root / req.file).resolve()
    
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {req.file}")
        
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        old_content = f.read()
        
    if req.old_code not in old_content:
        raise ValueError("Target code block to replace (old_code) not found in the file.")
        
    # Replace first occurrence
    new_content = old_content.replace(req.old_code, req.new_code, 1)
    
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    
    diff_list = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=req.file,
        tofile=req.file
    ))
    diff_str = "".join(diff_list)
    
    # Count lines changed in unified diff
    lines_changed = 0
    for line in diff_list:
        if line.startswith("+") and not line.startswith("+++"):
            lines_changed += 1
        elif line.startswith("-") and not line.startswith("---"):
            lines_changed += 1
            
    edit_id = str(ulid.ULID())
    _pending[edit_id] = req
    
    async with get_db() as db:
        await db.execute(
            "INSERT INTO edits (id, file_path, old_code, new_code, diff, applied, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?)",
            (edit_id, req.file, req.old_code, req.new_code, diff_str, time.time())
        )
        await db.commit()
        
    return EditPreview(
        edit_id=edit_id,
        file=req.file,
        diff=diff_str,
        lines_changed=lines_changed
    )

async def apply_edit(edit_id: str) -> ApplyResult:
    """
    Apply a pending edit to disk, commit via git, and update database.
    """
    if edit_id not in _pending:
        raise ValueError(f"Pending edit ID '{edit_id}' not found.")
        
    req = _pending[edit_id]
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    file_path = (repo_root / req.file).resolve()
    
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {req.file}")
        
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        old_content = f.read()
        
    if req.old_code not in old_content:
        raise ValueError("Target code block to replace (old_code) not found in the file.")
        
    new_content = old_content.replace(req.old_code, req.new_code, 1)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
        
    # Search for the git repo upward from the file itself (handles nested repos)
    repo = _get_repo(str(file_path.parent))
    repo.index.add([str(file_path)])
    commit = repo.index.commit(f"edit: {edit_id}")
    commit_hash = commit.hexsha
    
    async with get_db() as db:
        await db.execute(
            "UPDATE edits SET applied=1, applied_at=? WHERE id = ?",
            (time.time(), edit_id)
        )
        await db.commit()
        
    del _pending[edit_id]
    
    return ApplyResult(
        edit_id=edit_id,
        file=req.file,
        commit_hash=commit_hash
    )

async def undo_edit() -> UndoResult:
    """Revert the last git commit (HEAD)."""
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    # Use _find_repo_for_root so it can locate a child git repo when REPO_PATH
    # is a container folder (e.g. pdf-editor) with sub-repos (e.g. pdf-editor-service)
    repo = _find_repo_for_root(repo_root)
    
    reverted_commit = repo.head.commit.hexsha
    
    try:
        repo.git.revert("HEAD", no_edit=True)
    except Exception as e:
        raise ValueError(f"Git revert failed: {str(e)}")
        
    return UndoResult(
        reverted_commit=reverted_commit,
        message=f"Reverted commit {reverted_commit} successfully."
    )
