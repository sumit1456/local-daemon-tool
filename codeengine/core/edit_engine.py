from __future__ import annotations

import time
import difflib
import textwrap
import ulid
from pathlib import Path

from codeengine.database.sqlite import get_db
from codeengine.core.ast_engine import parse_blocks_from_code
from codeengine.models.edit_models import (
    ApplyResult,
    UndoResult,
    CodeBlock,
    BlockResult,
    SmartEditPreview,
    SmartEditResult,
    EditRequest,
    EditPreview,
)

import os
import git


# ---------------------------------------------------------------------------
# Git helpers (unchanged from original)
# ---------------------------------------------------------------------------

def _get_repo(path: str = ".") -> git.Repo:
    try:
        return git.Repo(path, search_parent_directories=True)
    except git.InvalidGitRepositoryError:
        raise ValueError(f"Directory '{path}' is not a git repository.")


def _find_repo_for_root(root: Path) -> git.Repo:
    try:
        return git.Repo(str(root), search_parent_directories=True)
    except git.InvalidGitRepositoryError:
        pass
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / ".git").exists():
            return git.Repo(str(child))
    for child in sorted(root.iterdir()):
        if child.is_dir():
            for grandchild in sorted(child.iterdir()):
                if grandchild.is_dir() and (grandchild / ".git").exists():
                    return git.Repo(str(grandchild))
    raise ValueError(f"No git repository found in or under '{root}'.")


# ---------------------------------------------------------------------------
# AST-based block parser
# ---------------------------------------------------------------------------

def _parse_blocks(source: str, file_path_hint: str | None = None, lang_hint: str | None = None) -> list[CodeBlock]:
    """
    Parse top-level nodes from source into CodeBlock list.

    Uses tree-sitter for all supported languages (Python, JS, TS, Java, Go, Rust).
    Handles:
      - import / from-import  → kind="import", name=None
      - def / async def / fn  → kind="function", name=<func name>
      - class / struct / impl → kind="class",    name=<class name>
      - UPPER_CASE assignment → kind="constant",  name=<var name>
      - anything else         → kind="other",     name=None
    """
    raw_blocks = parse_blocks_from_code(source, file_path_hint=file_path_hint, lang_hint=lang_hint)
    return [
        CodeBlock(kind=kind, name=name, source=src)
        for kind, name, src in raw_blocks
    ]


# ---------------------------------------------------------------------------
# Block-level replacement engine
# ---------------------------------------------------------------------------

def _find_function_bounds(lines: list[str], name: str) -> tuple[int, int] | None:
    """
    Find the start (inclusive) and end (exclusive) line indices of a
    top-level or class-level function/class named `name`.

    Uses indentation to determine the end of the block — works for Python
    without needing a full AST re-parse of the existing file.

    Returns (start_idx, end_idx) into `lines`, or None if not found.
    """
    # Match: optional decorator lines, then def/async def/class <name>
    import re
    header_re = re.compile(
        r"^(async\s+def|def|class)\s+" + re.escape(name) + r"\s*[:(]"
    )

    start_idx: int | None = None
    block_indent: int | None = None

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if start_idx is None:
            if header_re.match(stripped) and (len(line) - len(stripped) == 0 or True):
                # Only match top-level (indent == 0) or consistent indent
                indent = len(line) - len(line.lstrip())
                start_idx = i
                block_indent = indent
        else:
            # We're inside the block — find where it ends
            if line.strip() == "":
                continue  # blank lines don't end a block
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= block_indent and line.strip():
                # Back to same or lower indent → block ended at previous line
                # Walk back over trailing blank lines
                end_idx = i
                while end_idx > start_idx and lines[end_idx - 1].strip() == "":
                    end_idx -= 1
                return (start_idx, end_idx)

    if start_idx is not None:
        # Block runs to end of file
        end_idx = len(lines)
        while end_idx > start_idx and lines[end_idx - 1].strip() == "":
            end_idx -= 1
        return (start_idx, end_idx)

    return None


def _find_constant_bounds(lines: list[str], name: str) -> tuple[int, int] | None:
    """Find a module-level constant assignment line."""
    import re
    pattern = re.compile(r"^" + re.escape(name) + r"\s*(:|=)")
    for i, line in enumerate(lines):
        if pattern.match(line.strip()) and len(line) - len(line.lstrip()) == 0:
            return (i, i + 1)
    return None


def _find_import_section(lines: list[str]) -> tuple[int, int]:
    """
    Return (start, end) indices of the existing import block.
    end is the index of the first non-import, non-blank line.
    If no imports exist, returns (0, 0).
    """
    import re
    import_re = re.compile(r"^(import |from )")
    in_imports = False
    end = 0
    for i, line in enumerate(lines):
        if import_re.match(line):
            in_imports = True
            end = i + 1
        elif in_imports and line.strip() == "":
            end = i + 1
        elif in_imports:
            break
    return (0, end)


def _merge_imports(existing_lines: list[str], new_import: str) -> list[str]:
    """
    Add new_import line(s) into the import section if not already present.
    Returns the full updated lines list.
    """
    new_imp_lines = [l for l in new_import.splitlines() if l.strip()]
    _, imp_end = _find_import_section(existing_lines)

    result = list(existing_lines)
    insert_at = imp_end
    for imp_line in new_imp_lines:
        # Skip if already present
        if any(imp_line.strip() == l.strip() for l in result):
            continue
        result.insert(insert_at, imp_line + "\n")
        insert_at += 1

    return result


def _apply_blocks(
    original: str,
    blocks: list[CodeBlock],
    file_path_hint: str | None = None,
) -> tuple[str, list[BlockResult]]:
    """
    Apply each block from `blocks` onto `original` source.

    Strategy per block kind:
      import   → merge into import section (skip duplicates)
      function → replace existing def by name, or append
      class    → replace existing class by name, or append
      constant → replace existing assignment, or insert after imports
      other    → append at end
    """
    from codeengine.core.ast_engine import find_symbol_bounds_in_code

    lines = original.splitlines(keepends=True)
    results: list[BlockResult] = []

    for block in blocks:
        if block.kind == "import":
            lines = _merge_imports(lines, block.source)
            results.append(BlockResult(kind="import", name=None, action="added"))

        elif block.kind in ("function", "class"):
            bounds = find_symbol_bounds_in_code(
                "".join(lines),
                block.name,
                block.kind,
                file_path_hint=file_path_hint,
            )
            # Normalise block source — strip leading blank lines, ensure trailing newline
            new_src = textwrap.dedent(block.source).strip() + "\n"
            if bounds:
                start, end = bounds
                # Preserve blank line before block
                prefix_blank = "\n" if start > 0 and lines[start - 1].strip() != "" else ""
                replacement = (prefix_blank + new_src + "\n").splitlines(keepends=True)
                lines[start:end] = replacement
                results.append(BlockResult(
                    kind=block.kind, name=block.name, action="replaced",
                    detail=f"lines {start+1}–{end}"
                ))
            else:
                # Not found — append at end with blank line separator
                if lines and lines[-1].strip() != "":
                    lines.append("\n")
                lines.extend((new_src + "\n").splitlines(keepends=True))
                results.append(BlockResult(
                    kind=block.kind, name=block.name, action="added",
                    detail="appended at end"
                ))

        elif block.kind == "constant":
            bounds = find_symbol_bounds_in_code(
                "".join(lines),
                block.name,
                block.kind,
                file_path_hint=file_path_hint,
            )
            new_src = block.source.strip() + "\n"
            if bounds:
                start, end = bounds
                lines[start:end] = [new_src]
                results.append(BlockResult(
                    kind="constant", name=block.name, action="replaced",
                    detail=f"lines {start+1}–{end}"
                ))
            else:
                # Insert after import section
                _, imp_end = _find_import_section(lines)
                insert_at = imp_end
                # Skip blank lines after imports
                while insert_at < len(lines) and lines[insert_at].strip() == "":
                    insert_at += 1
                lines.insert(insert_at, new_src)
                results.append(BlockResult(
                    kind="constant", name=block.name, action="added",
                    detail=f"inserted at line {insert_at+1}"
                ))

        else:
            # "other" — append
            if lines and lines[-1].strip() != "":
                lines.append("\n")
            lines.extend((block.source.strip() + "\n").splitlines(keepends=True))
            results.append(BlockResult(kind="other", name=None, action="added"))

    return "".join(lines), results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# In-memory pending store: edit_id → (file_path_str, new_content_str)
_pending: dict[str, tuple[str, str]] = {}


async def preview_smart_edit(file: str, new_code: str) -> SmartEditPreview:
    """
    Parse new_code into blocks, apply each onto the existing file,
    compute a unified diff, and store as a pending edit.

    Args:
        file:     Relative path to the file inside REPO_PATH.
        new_code: The updated code you want merged in. Can be a full file
                  rewrite or just the functions/classes that changed.

    Returns:
        SmartEditPreview with diff, lines_changed, and per-block results.
    """
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    file_path = (repo_root / file).resolve()

    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file}")

    original = file_path.read_text(encoding="utf-8", errors="replace")

    blocks = _parse_blocks(new_code, file_path_hint=file)
    merged, block_results = _apply_blocks(original, blocks, file_path_hint=file)

    # Unified diff
    old_lines = original.splitlines(keepends=True)
    new_lines = merged.splitlines(keepends=True)
    diff_list = list(difflib.unified_diff(old_lines, new_lines, fromfile=file, tofile=file))
    diff_str = "".join(diff_list)

    lines_changed = sum(
        1 for l in diff_list
        if (l.startswith("+") and not l.startswith("+++"))
        or (l.startswith("-") and not l.startswith("---"))
    )

    edit_id = str(ulid.ULID())
    _pending[edit_id] = (str(file_path), merged)

    async with get_db() as db:
        await db.execute(
            "INSERT INTO edits (id, file_path, old_code, new_code, diff, applied, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?)",
            (edit_id, file, original, merged, diff_str, time.time())
        )
        await db.commit()

    return SmartEditPreview(
        edit_id=edit_id,
        file=file,
        diff=diff_str,
        lines_changed=lines_changed,
        blocks=block_results,
    )


async def apply_smart_edit(edit_id: str) -> SmartEditResult:
    """
    Write the merged content to disk, commit via git, mark as applied.

    Args:
        edit_id: ID returned by preview_smart_edit.
    """
    if edit_id not in _pending:
        raise ValueError(f"No pending edit with ID '{edit_id}'.")

    file_path_str, merged = _pending[edit_id]
    file_path = Path(file_path_str)

    if not file_path.is_file():
        raise FileNotFoundError(f"File disappeared before apply: {file_path}")

    file_path.write_text(merged, encoding="utf-8")

    repo = _get_repo(str(file_path.parent))
    
    # Auto-commit untracked files before first edit so undo won't delete them
    try:
        status = repo.git.status("--porcelain", str(file_path)).strip()
        is_untracked = status.startswith("??")
    except Exception:
        is_untracked = False
    if is_untracked:
        repo.index.add([str(file_path)])
        repo.index.commit(f"track: {file_path.name}")
    
    repo.index.add([str(file_path)])
    commit = repo.index.commit(f"smart-edit: {edit_id}")

    async with get_db() as db:
        await db.execute(
            "UPDATE edits SET applied=1, applied_at=? WHERE id=?",
            (time.time(), edit_id)
        )
        await db.commit()

    # Retrieve block results from DB for the response
    async with get_db() as db:
        async with db.execute(
            "SELECT diff FROM edits WHERE id=?", (edit_id,)
        ) as cur:
            row = await cur.fetchone()

    del _pending[edit_id]

    return SmartEditResult(
        edit_id=edit_id,
        file=str(file_path),
        commit_hash=commit.hexsha,
        blocks=[],  # block detail lives in preview; apply just confirms commit
    )


async def undo_edit() -> UndoResult:
    """Revert the last git commit (HEAD)."""
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
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


# ---------------------------------------------------------------------------
# Legacy API (backward compatibility wrappers)
# ---------------------------------------------------------------------------

async def preview_edit(req: EditRequest) -> EditPreview:
    """
    Legacy wrapper for preview_smart_edit.
    Converts old EditRequest (old_code/new_code replacement) to smart block editing.
    
    Args:
        req: EditRequest with file, old_code, and new_code.
        
    Returns:
        EditPreview with edit_id, file, diff, and lines_changed.
    """
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    file_path = (repo_root / req.file).resolve()
    
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {req.file}")
    
    original = file_path.read_text(encoding="utf-8", errors="replace")
    
    # Normalize line endings to LF for robust search and replace
    norm_original = original.replace("\r\n", "\n")
    norm_old = req.old_code.replace("\r\n", "\n")
    norm_new = req.new_code.replace("\r\n", "\n")
    
    if norm_old not in norm_original:
        raise ValueError("Target code block to replace (old_code) not found in the file.")
    
    # Perform replacement in normalized space
    norm_new_content = norm_original.replace(norm_old, norm_new, 1)
    
    # Restore original line ending style if file used CRLF
    if "\r\n" in original and not original.startswith("\n"):
        new_content = norm_new_content.replace("\n", "\r\n")
    else:
        new_content = norm_new_content
    
    old_lines = original.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff_list = list(difflib.unified_diff(old_lines, new_lines, fromfile=req.file, tofile=req.file))
    diff_str = "".join(diff_list)
    
    lines_changed = sum(
        1 for l in diff_list
        if (l.startswith("+") and not l.startswith("+++"))
        or (l.startswith("-") and not l.startswith("---"))
    )
    
    edit_id = str(ulid.ULID())
    _pending[edit_id] = (str(file_path), new_content)
    
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
        lines_changed=lines_changed,
    )


async def apply_edit(edit_id: str) -> ApplyResult:
    """
    Legacy wrapper for apply_smart_edit.
    Applies a pending edit from preview_edit to disk and commits to git.
    
    Args:
        edit_id: ID returned by preview_edit.
        
    Returns:
        ApplyResult with edit_id, file, and commit_hash.
    """
    if edit_id not in _pending:
        raise ValueError(f"No pending edit with ID '{edit_id}'.")
    
    file_path_str, new_content = _pending[edit_id]
    file_path = Path(file_path_str)
    
    if not file_path.is_file():
        raise FileNotFoundError(f"File disappeared before apply: {file_path}")
    
    file_path.write_text(new_content, encoding="utf-8")
    
    repo = _get_repo(str(file_path.parent))
    
    # Auto-commit untracked files before first edit so undo won't delete them
    try:
        status = repo.git.status("--porcelain", str(file_path)).strip()
        is_untracked = status.startswith("??")
    except Exception:
        is_untracked = False
    if is_untracked:
        repo.index.add([str(file_path)])
        repo.index.commit(f"track: {file_path.name}")
    
    repo.index.add([str(file_path)])
    commit = repo.index.commit(f"edit: {edit_id}")
    
    async with get_db() as db:
        await db.execute(
            "UPDATE edits SET applied=1, applied_at=? WHERE id=?",
            (time.time(), edit_id)
        )
        await db.commit()
    
    del _pending[edit_id]
    
    return ApplyResult(
        edit_id=edit_id,
        file=str(file_path.relative_to(Path(os.getenv("REPO_PATH", ".")).resolve())),
        commit_hash=commit.hexsha,
    )