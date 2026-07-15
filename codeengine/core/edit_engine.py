# from __future__ import annotations

# import time
# import difflib
# import textwrap
# import ulid
# from pathlib import Path

# from codeengine.database.sqlite import get_db
# from codeengine.core.ast_engine import parse_blocks_from_code
# from codeengine.models.edit_models import (
#     ApplyResult,
#     UndoResult,
#     CodeBlock,
#     BlockResult,
#     SmartEditPreview,
#     SmartEditResult,
#     EditRequest,
#     EditPreview,
# )

# import os
# import git


# # ---------------------------------------------------------------------------
# # Git helpers (unchanged from original)
# # ---------------------------------------------------------------------------

# def _get_repo(path: str = ".") -> git.Repo:
#     try:
#         return git.Repo(path, search_parent_directories=True)
#     except git.InvalidGitRepositoryError:
#         raise ValueError(f"Directory '{path}' is not a git repository.")


# def _find_repo_for_root(root: Path) -> git.Repo:
#     try:
#         return git.Repo(str(root), search_parent_directories=True)
#     except git.InvalidGitRepositoryError:
#         pass
#     for child in sorted(root.iterdir()):
#         if child.is_dir() and (child / ".git").exists():
#             return git.Repo(str(child))
#     for child in sorted(root.iterdir()):
#         if child.is_dir():
#             for grandchild in sorted(child.iterdir()):
#                 if grandchild.is_dir() and (grandchild / ".git").exists():
#                     return git.Repo(str(grandchild))
#     raise ValueError(f"No git repository found in or under '{root}'.")


# # ---------------------------------------------------------------------------
# # AST-based block parser
# # ---------------------------------------------------------------------------

# def _parse_blocks(source: str, file_path_hint: str | None = None, lang_hint: str | None = None) -> list[CodeBlock]:
#     """
#     Parse top-level nodes from source into CodeBlock list.

#     Uses tree-sitter for all supported languages (Python, JS, TS, Java, Go, Rust).
#     Handles:
#       - import / from-import  → kind="import", name=None
#       - def / async def / fn  → kind="function", name=<func name>
#       - class / struct / impl → kind="class",    name=<class name>
#       - UPPER_CASE assignment → kind="constant",  name=<var name>
#       - anything else         → kind="other",     name=None
#     """
#     raw_blocks = parse_blocks_from_code(source, file_path_hint=file_path_hint, lang_hint=lang_hint)
#     return [
#         CodeBlock(kind=kind, name=name, source=src)
#         for kind, name, src in raw_blocks
#     ]


# # ---------------------------------------------------------------------------
# # Block-level replacement engine
# # ---------------------------------------------------------------------------

# def _find_function_bounds(lines: list[str], name: str) -> tuple[int, int] | None:
#     """
#     Find the start (inclusive) and end (exclusive) line indices of a
#     top-level or class-level function/class named `name`.

#     Uses indentation to determine the end of the block — works for Python
#     without needing a full AST re-parse of the existing file.

#     Returns (start_idx, end_idx) into `lines`, or None if not found.
#     """
#     # Match: optional decorator lines, then def/async def/class <name>
#     import re
#     header_re = re.compile(
#         r"^(async\s+def|def|class)\s+" + re.escape(name) + r"\s*[:(]"
#     )

#     start_idx: int | None = None
#     block_indent: int | None = None

#     for i, line in enumerate(lines):
#         stripped = line.lstrip()
#         if start_idx is None:
#             if header_re.match(stripped) and (len(line) - len(stripped) == 0 or True):
#                 # Only match top-level (indent == 0) or consistent indent
#                 indent = len(line) - len(line.lstrip())
#                 start_idx = i
#                 block_indent = indent
#         else:
#             # We're inside the block — find where it ends
#             if line.strip() == "":
#                 continue  # blank lines don't end a block
#             current_indent = len(line) - len(line.lstrip())
#             if current_indent <= block_indent and line.strip():
#                 # Back to same or lower indent → block ended at previous line
#                 # Walk back over trailing blank lines
#                 end_idx = i
#                 while end_idx > start_idx and lines[end_idx - 1].strip() == "":
#                     end_idx -= 1
#                 return (start_idx, end_idx)

#     if start_idx is not None:
#         # Block runs to end of file
#         end_idx = len(lines)
#         while end_idx > start_idx and lines[end_idx - 1].strip() == "":
#             end_idx -= 1
#         return (start_idx, end_idx)

#     return None


# def _find_constant_bounds(lines: list[str], name: str) -> tuple[int, int] | None:
#     """Find a module-level constant assignment line."""
#     import re
#     pattern = re.compile(r"^" + re.escape(name) + r"\s*(:|=)")
#     for i, line in enumerate(lines):
#         if pattern.match(line.strip()) and len(line) - len(line.lstrip()) == 0:
#             return (i, i + 1)
#     return None


# def _find_import_section(lines: list[str]) -> tuple[int, int]:
#     """
#     Return (start, end) indices of the existing import block.
#     end is the index of the first non-import, non-blank line.
#     If no imports exist, returns (0, 0).
#     """
#     import re
#     import_re = re.compile(r"^(import |from )")
#     in_imports = False
#     end = 0
#     for i, line in enumerate(lines):
#         if import_re.match(line):
#             in_imports = True
#             end = i + 1
#         elif in_imports and line.strip() == "":
#             end = i + 1
#         elif in_imports:
#             break
#     return (0, end)


# def _merge_imports(existing_lines: list[str], new_import: str) -> list[str]:
#     """
#     Add new_import line(s) into the import section if not already present.
#     Returns the full updated lines list.
#     """
#     new_imp_lines = [l for l in new_import.splitlines() if l.strip()]
#     _, imp_end = _find_import_section(existing_lines)

#     result = list(existing_lines)
#     insert_at = imp_end
#     for imp_line in new_imp_lines:
#         # Skip if already present
#         if any(imp_line.strip() == l.strip() for l in result):
#             continue
#         result.insert(insert_at, imp_line + "\n")
#         insert_at += 1

#     return result


# def _apply_blocks(
#     original: str,
#     blocks: list[CodeBlock],
#     file_path_hint: str | None = None,
# ) -> tuple[str, list[BlockResult]]:
#     """
#     Apply each block from `blocks` onto `original` source.

#     Strategy per block kind:
#       import   → merge into import section (skip duplicates)
#       function → replace existing def by name, or append
#       class    → replace existing class by name, or append
#       constant → replace existing assignment, or insert after imports
#       other    → append at end
#     """
#     from codeengine.core.ast_engine import find_symbol_bounds_in_code

#     lines = original.splitlines(keepends=True)
#     results: list[BlockResult] = []

#     for block in blocks:
#         if block.kind == "import":
#             lines = _merge_imports(lines, block.source)
#             results.append(BlockResult(kind="import", name=None, action="added"))

#         elif block.kind in ("function", "class"):
#             bounds = find_symbol_bounds_in_code(
#                 "".join(lines),
#                 block.name,
#                 block.kind,
#                 file_path_hint=file_path_hint,
#             )
#             # Normalise block source — strip leading blank lines, ensure trailing newline
#             new_src = textwrap.dedent(block.source).strip() + "\n"
#             if bounds:
#                 start, end = bounds
#                 # Preserve blank line before block
#                 prefix_blank = "\n" if start > 0 and lines[start - 1].strip() != "" else ""
#                 replacement = (prefix_blank + new_src + "\n").splitlines(keepends=True)
#                 lines[start:end] = replacement
#                 results.append(BlockResult(
#                     kind=block.kind, name=block.name, action="replaced",
#                     detail=f"lines {start+1}–{end}"
#                 ))
#             else:
#                 # Not found — append at end with blank line separator
#                 if lines and lines[-1].strip() != "":
#                     lines.append("\n")
#                 lines.extend((new_src + "\n").splitlines(keepends=True))
#                 results.append(BlockResult(
#                     kind=block.kind, name=block.name, action="added",
#                     detail="appended at end"
#                 ))

#         elif block.kind == "constant":
#             bounds = find_symbol_bounds_in_code(
#                 "".join(lines),
#                 block.name,
#                 block.kind,
#                 file_path_hint=file_path_hint,
#             )
#             new_src = block.source.strip() + "\n"
#             if bounds:
#                 start, end = bounds
#                 lines[start:end] = [new_src]
#                 results.append(BlockResult(
#                     kind="constant", name=block.name, action="replaced",
#                     detail=f"lines {start+1}–{end}"
#                 ))
#             else:
#                 # Insert after import section
#                 _, imp_end = _find_import_section(lines)
#                 insert_at = imp_end
#                 # Skip blank lines after imports
#                 while insert_at < len(lines) and lines[insert_at].strip() == "":
#                     insert_at += 1
#                 lines.insert(insert_at, new_src)
#                 results.append(BlockResult(
#                     kind="constant", name=block.name, action="added",
#                     detail=f"inserted at line {insert_at+1}"
#                 ))

#         else:
#             # "other" — append
#             if lines and lines[-1].strip() != "":
#                 lines.append("\n")
#             lines.extend((block.source.strip() + "\n").splitlines(keepends=True))
#             results.append(BlockResult(kind="other", name=None, action="added"))

#     return "".join(lines), results


# # ---------------------------------------------------------------------------
# # Public API
# # ---------------------------------------------------------------------------

# # In-memory pending store: edit_id → (file_path_str, new_content_str)
# _pending: dict[str, tuple[str, str]] = {}


# async def preview_smart_edit(file: str, new_code: str) -> SmartEditPreview:
#     """
#     Parse new_code into blocks, apply each onto the existing file,
#     compute a unified diff, and store as a pending edit.

#     Args:
#         file:     Relative path to the file inside REPO_PATH.
#         new_code: The updated code you want merged in. Can be a full file
#                   rewrite or just the functions/classes that changed.

#     Returns:
#         SmartEditPreview with diff, lines_changed, and per-block results.
#     """
#     repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
#     file_path = (repo_root / file).resolve()

#     if not file_path.is_file():
#         raise FileNotFoundError(f"File not found: {file}")

#     original = file_path.read_text(encoding="utf-8", errors="replace")

#     blocks = _parse_blocks(new_code, file_path_hint=file)
#     merged, block_results = _apply_blocks(original, blocks, file_path_hint=file)

#     # Unified diff
#     old_lines = original.splitlines(keepends=True)
#     new_lines = merged.splitlines(keepends=True)
#     diff_list = list(difflib.unified_diff(old_lines, new_lines, fromfile=file, tofile=file))
#     diff_str = "".join(diff_list)

#     lines_changed = sum(
#         1 for l in diff_list
#         if (l.startswith("+") and not l.startswith("+++"))
#         or (l.startswith("-") and not l.startswith("---"))
#     )

#     edit_id = str(ulid.ULID())
#     _pending[edit_id] = (str(file_path), merged)

#     async with get_db() as db:
#         await db.execute(
#             "INSERT INTO edits (id, file_path, old_code, new_code, diff, applied, created_at) "
#             "VALUES (?, ?, ?, ?, ?, 0, ?)",
#             (edit_id, file, original, merged, diff_str, time.time())
#         )
#         await db.commit()

#     return SmartEditPreview(
#         edit_id=edit_id,
#         file=file,
#         diff=diff_str,
#         lines_changed=lines_changed,
#         blocks=block_results,
#     )


# async def apply_smart_edit(edit_id: str) -> SmartEditResult:
#     """
#     Write the merged content to disk, commit via git, mark as applied.

#     Args:
#         edit_id: ID returned by preview_smart_edit.
#     """
#     if edit_id not in _pending:
#         raise ValueError(f"No pending edit with ID '{edit_id}'.")

#     file_path_str, merged = _pending[edit_id]
#     file_path = Path(file_path_str)

#     if not file_path.is_file():
#         raise FileNotFoundError(f"File disappeared before apply: {file_path}")

#     file_path.write_text(merged, encoding="utf-8")

#     repo = _get_repo(str(file_path.parent))
    
#     # Auto-commit untracked files before first edit so undo won't delete them
#     try:
#         status = repo.git.status("--porcelain", str(file_path)).strip()
#         is_untracked = status.startswith("??")
#     except Exception:
#         is_untracked = False
#     if is_untracked:
#         repo.index.add([str(file_path)])
#         repo.index.commit(f"track: {file_path.name}")
    
#     repo.index.add([str(file_path)])
#     commit = repo.index.commit(f"smart-edit: {edit_id}")

#     async with get_db() as db:
#         await db.execute(
#             "UPDATE edits SET applied=1, applied_at=? WHERE id=?",
#             (time.time(), edit_id)
#         )
#         await db.commit()

#     # Retrieve block results from DB for the response
#     async with get_db() as db:
#         async with db.execute(
#             "SELECT diff FROM edits WHERE id=?", (edit_id,)
#         ) as cur:
#             row = await cur.fetchone()

#     del _pending[edit_id]

#     return SmartEditResult(
#         edit_id=edit_id,
#         file=str(file_path),
#         commit_hash=commit.hexsha,
#         blocks=[],  # block detail lives in preview; apply just confirms commit
#     )


# async def undo_edit() -> UndoResult:
#     """Revert the last git commit (HEAD)."""
#     repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
#     repo = _find_repo_for_root(repo_root)
#     reverted_commit = repo.head.commit.hexsha
#     try:
#         repo.git.revert("HEAD", no_edit=True)
#     except Exception as e:
#         raise ValueError(f"Git revert failed: {str(e)}")
#     return UndoResult(
#         reverted_commit=reverted_commit,
#         message=f"Reverted commit {reverted_commit} successfully."
#     )


# # ---------------------------------------------------------------------------
# # Legacy API (backward compatibility wrappers)
# # ---------------------------------------------------------------------------

# def _find_best_match(norm_old: str, norm_original: str, threshold: float = 0.85):
#     """
#     Find the best fuzzy match of norm_old inside norm_original.
#     Returns (start_char_index, end_char_index, ratio) or None if below threshold.
#     """
#     old_lines = norm_old.splitlines()
#     orig_lines = norm_original.splitlines()
#     n = len(old_lines)

#     if n == 0:
#         return None

#     best_ratio = 0.0
#     best_start_line = None

#     # Slide a window of len(old_lines) over orig_lines
#     for i in range(len(orig_lines) - n + 1):
#         window = orig_lines[i : i + n]
#         ratio = difflib.SequenceMatcher(
#             None,
#             "\n".join(old_lines),
#             "\n".join(window),
#             autojunk=False,
#         ).ratio()
#         if ratio > best_ratio:
#             best_ratio = ratio
#             best_start_line = i

#     if best_ratio < threshold or best_start_line is None:
#         return None

#     # Convert line indices back to char offsets
#     lines_with_endings = norm_original.splitlines(keepends=True)
#     start_char = sum(len(l) for l in lines_with_endings[:best_start_line])
#     end_char = sum(len(l) for l in lines_with_endings[:best_start_line + n])

#     return start_char, end_char, best_ratio


# async def preview_edit(req: EditRequest) -> EditPreview:
#     """
#     Preview a code edit with fuzzy matching support.
#     Tries exact match first, falls back to fuzzy matching (85% threshold).

#     Args:
#         req: EditRequest with file, old_code, and new_code.

#     Returns:
#         EditPreview with edit_id, file, diff, and lines_changed.
#     """
#     repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
#     file_path = (repo_root / req.file).resolve()

#     if not file_path.is_file():
#         raise FileNotFoundError(f"File not found: {req.file}")

#     original = file_path.read_text(encoding="utf-8", errors="replace")
#     norm_original = original.replace("\r\n", "\n")
#     norm_old = req.old_code.replace("\r\n", "\n")
#     norm_new = req.new_code.replace("\r\n", "\n")

#     # --- Fast path: exact match (preserves current behavior) ---
#     if norm_old in norm_original:
#         norm_new_content = norm_original.replace(norm_old, norm_new, 1)
#     else:
#         # --- Fuzzy path: find best matching block ---
#         match = _find_best_match(norm_old, norm_original)
#         if match is None:
#             raise ValueError(
#                 "Target code block (old_code) not found in the file. "
#                 "No sufficiently similar block could be located (threshold: 85%)."
#             )
#         start_char, end_char, ratio = match
#         norm_new_content = norm_original[:start_char] + norm_new + norm_original[end_char:]

#     # Restore CRLF if original used it
#     if "\r\n" in original and not original.startswith("\n"):
#         new_content = norm_new_content.replace("\n", "\r\n")
#     else:
#         new_content = norm_new_content

#     old_lines = original.splitlines(keepends=True)
#     new_lines = new_content.splitlines(keepends=True)
#     diff_list = list(difflib.unified_diff(old_lines, new_lines, fromfile=req.file, tofile=req.file))
#     diff_str = "".join(diff_list)

#     lines_changed = sum(
#         1 for l in diff_list
#         if (l.startswith("+") and not l.startswith("+++"))
#         or (l.startswith("-") and not l.startswith("---"))
#     )

#     edit_id = str(ulid.ULID())
#     _pending[edit_id] = (str(file_path), new_content)

#     async with get_db() as db:
#         await db.execute(
#             "INSERT INTO edits (id, file_path, old_code, new_code, diff, applied, created_at) "
#             "VALUES (?, ?, ?, ?, ?, 0, ?)",
#             (edit_id, req.file, req.old_code, req.new_code, diff_str, time.time())
#         )
#         await db.commit()

#     return EditPreview(
#         edit_id=edit_id,
#         file=req.file,
#         diff=diff_str,
#         lines_changed=lines_changed,
#     )


# async def apply_edit(edit_id: str) -> ApplyResult:
#     """
#     Legacy wrapper for apply_smart_edit.
#     Applies a pending edit from preview_edit to disk and commits to git.
    
#     Args:
#         edit_id: ID returned by preview_edit.
        
#     Returns:
#         ApplyResult with edit_id, file, and commit_hash.
#     """
#     if edit_id not in _pending:
#         raise ValueError(f"No pending edit with ID '{edit_id}'.")
    
#     file_path_str, new_content = _pending[edit_id]
#     file_path = Path(file_path_str)
    
#     if not file_path.is_file():
#         raise FileNotFoundError(f"File disappeared before apply: {file_path}")
    
#     file_path.write_text(new_content, encoding="utf-8")
    
#     repo = _get_repo(str(file_path.parent))
    
#     # Auto-commit untracked files before first edit so undo won't delete them
#     try:
#         status = repo.git.status("--porcelain", str(file_path)).strip()
#         is_untracked = status.startswith("??")
#     except Exception:
#         is_untracked = False
#     if is_untracked:
#         repo.index.add([str(file_path)])
#         repo.index.commit(f"track: {file_path.name}")
    
#     repo.index.add([str(file_path)])
#     commit = repo.index.commit(f"edit: {edit_id}")
    
#     async with get_db() as db:
#         await db.execute(
#             "UPDATE edits SET applied=1, applied_at=? WHERE id=?",
#             (time.time(), edit_id)
#         )
#         await db.commit()
    
#     del _pending[edit_id]
    
#     return ApplyResult(
#         edit_id=edit_id,
#         file=str(file_path.relative_to(Path(os.getenv("REPO_PATH", ".")).resolve())),
#         commit_hash=commit.hexsha,
#     )


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
                indent = len(line) - len(line.lstrip())
                start_idx = i
                block_indent = indent
        else:
            if line.strip() == "":
                continue  # blank lines don't end a block
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= block_indent and line.strip():
                end_idx = i
                while end_idx > start_idx and lines[end_idx - 1].strip() == "":
                    end_idx -= 1
                return (start_idx, end_idx)

    if start_idx is not None:
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
            bounds = None
            if block.name:
                bounds = find_symbol_bounds_in_code(
                    "".join(lines),
                    block.name,
                    block.kind,
                    file_path_hint=file_path_hint,
                )
            new_src = textwrap.dedent(block.source).strip() + "\n"
            if bounds:
                start, end = bounds
                prefix_blank = "\n" if start > 0 and lines[start - 1].strip() != "" else ""
                replacement = (prefix_blank + new_src).splitlines(keepends=True)
                lines[start:end] = replacement
                results.append(BlockResult(
                    kind=block.kind, name=block.name, action="replaced",
                    detail=f"lines {start+1}–{end}"
                ))
            else:
                if lines and lines[-1].strip() != "":
                    lines.append("\n")
                lines.extend(new_src.splitlines(keepends=True))
                results.append(BlockResult(
                    kind=block.kind, name=block.name, action="added",
                    detail="appended at end"
                ))

        elif block.kind == "constant":
            bounds = None
            if block.name:
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
                _, imp_end = _find_import_section(lines)
                insert_at = imp_end
                while insert_at < len(lines) and lines[insert_at].strip() == "":
                    insert_at += 1
                lines.insert(insert_at, new_src)
                results.append(BlockResult(
                    kind="constant", name=block.name, action="added",
                    detail=f"inserted at line {insert_at+1}"
                ))

        else:
            if lines and lines[-1].strip() != "":
                lines.append("\n")
            lines.extend((block.source.strip() + "\n").splitlines(keepends=True))
            results.append(BlockResult(kind="other", name=None, action="added"))

    return "".join(lines), results


# ---------------------------------------------------------------------------
# AST-based replace engine (redesigned with class context)
# ---------------------------------------------------------------------------

def _find_symbol_in_context(
    lines: list[str],
    name: str,
    kind: str,
    class_name: str | None = None,
) -> tuple[int, int] | None:
    """
    Find a symbol with class-aware matching.

    If class_name is provided, only match the symbol if it's nested inside
    that class definition. This solves the duplicate name problem (e.g.
    multiple classes each having a `run` method).

    If class_name is None, falls back to first top-level match.

    Returns (start_line_idx, end_line_idx) or None.
    """
    import re

    if kind in ("function", "class"):
        header_re = re.compile(
            r"^(async\s+def|def|class)\s+" + re.escape(name) + r"\s*[:(]"
        )
    elif kind == "constant":
        header_re = re.compile(r"^" + re.escape(name) + r"\s*(:|=)")
    else:
        return None

    # If class_name given, first find the class bounds
    class_start = None
    class_end = None
    if class_name:
        class_re = re.compile(r"^class\s+" + re.escape(class_name) + r"\s*[:\(]")
        for i, line in enumerate(lines):
            if class_re.match(line.lstrip()):
                class_indent = len(line) - len(line.lstrip())
                class_start = i
                # Find end of class
                for j in range(i + 1, len(lines)):
                    stripped = lines[j].lstrip()
                    if stripped == "" or stripped.startswith("#"):
                        continue
                    cur_indent = len(lines[j]) - len(lines[j].lstrip())
                    if cur_indent <= class_indent and stripped:
                        class_end = j
                        break
                if class_end is None:
                    class_end = len(lines)
                break

    search_start = class_start if class_start is not None else 0
    search_end = class_end if class_end is not None else len(lines)

    start_idx = None
    block_indent = None

    for i in range(search_start, search_end):
        line = lines[i]
        stripped = line.lstrip()
        if start_idx is None:
            if header_re.match(stripped):
                indent = len(line) - len(line.lstrip())
                start_idx = i
                block_indent = indent
        else:
            if line.strip() == "":
                continue
            cur_indent = len(line) - len(line.lstrip())
            if cur_indent <= block_indent and line.strip():
                end_idx = i
                while end_idx > start_idx and lines[end_idx - 1].strip() == "":
                    end_idx -= 1
                return (start_idx, end_idx)

    if start_idx is not None:
        end_idx = search_end
        while end_idx > start_idx and lines[end_idx - 1].strip() == "":
            end_idx -= 1
        return (start_idx, end_idx)

    return None


def _apply_blocks_ast(
    original: str,
    blocks: list[CodeBlock],
    file_path_hint: str | None = None,
    class_context: str | None = None,
) -> tuple[str, list[BlockResult]]:
    """
    Apply blocks using AST-aware replacement with class context support.

    Improvements over old _apply_blocks:
    - class_context parameter: when set, methods are matched within that class
    - No double-newline bug (single trailing \n on new_src)
    - None-name guard before find_symbol_bounds_in_code
    """
    from codeengine.core.ast_engine import find_symbol_bounds_in_code

    lines = original.splitlines(keepends=True)
    results: list[BlockResult] = []

    for block in blocks:
        if block.kind == "import":
            lines = _merge_imports(lines, block.source)
            results.append(BlockResult(kind="import", name=None, action="added"))

        elif block.kind in ("function", "class"):
            bounds = None
            if block.name:
                # Try class-aware match first if we have context
                if class_context and block.kind == "function":
                    bounds = _find_symbol_in_context(
                        lines, block.name, block.kind, class_name=class_context
                    )
                # Fall back to global AST search
                if bounds is None:
                    bounds = find_symbol_bounds_in_code(
                        "".join(lines),
                        block.name,
                        block.kind,
                        file_path_hint=file_path_hint,
                    )
            new_src = textwrap.dedent(block.source).strip() + "\n"
            if bounds:
                start, end = bounds
                prefix_blank = "\n" if start > 0 and lines[start - 1].strip() != "" else ""
                replacement = (prefix_blank + new_src).splitlines(keepends=True)
                lines[start:end] = replacement
                results.append(BlockResult(
                    kind=block.kind, name=block.name, action="replaced",
                    detail=f"lines {start+1}–{end}"
                ))
            else:
                if lines and lines[-1].strip() != "":
                    lines.append("\n")
                lines.extend(new_src.splitlines(keepends=True))
                results.append(BlockResult(
                    kind=block.kind, name=block.name, action="added",
                    detail="appended at end"
                ))

        elif block.kind == "constant":
            bounds = None
            if block.name:
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
                _, imp_end = _find_import_section(lines)
                insert_at = imp_end
                while insert_at < len(lines) and lines[insert_at].strip() == "":
                    insert_at += 1
                lines.insert(insert_at, new_src)
                results.append(BlockResult(
                    kind="constant", name=block.name, action="added",
                    detail=f"inserted at line {insert_at+1}"
                ))

        else:
            if lines and lines[-1].strip() != "":
                lines.append("\n")
            lines.extend((block.source.strip() + "\n").splitlines(keepends=True))
            results.append(BlockResult(kind="other", name=None, action="added"))

    return "".join(lines), results


def _detect_class_context(source: str, target_name: str) -> str | None:
    """
    Scan source to find which class contains a method named target_name.
    Returns the class name, or None if not found inside any class.
    """
    import re
    lines = source.splitlines()
    current_class = None
    current_indent = 0

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(line.lstrip())

        class_match = re.match(r"^class\s+(\w+)", stripped)
        if class_match:
            current_class = class_match.group(1)
            current_indent = indent
            continue

        if current_class and indent <= current_indent and stripped and not stripped.startswith("#"):
            current_class = None

        if current_class and re.match(r"^(async\s+def|def)\s+" + re.escape(target_name) + r"\s*[:(]", stripped):
            return current_class

    return None


# ---------------------------------------------------------------------------
# Fuzzy string-based replace engine (opencode approach)
# ---------------------------------------------------------------------------

def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if a == "" or b == "":
        return max(len(a), len(b))
    m, n = len(a), len(b)
    matrix = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        matrix[i][0] = i
    for j in range(n + 1):
        matrix[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            matrix[i][j] = min(
                matrix[i - 1][j] + 1,
                matrix[i][j - 1] + 1,
                matrix[i - 1][j - 1] + cost,
            )
    return matrix[m][n]


def _is_disproportionate_match(matched: str, original: str) -> bool:
    """Refuse replacement if matched span is much larger than original."""
    orig_lines = original.split("\n")
    match_lines = matched.split("\n")
    if len(match_lines) >= max(len(orig_lines) + 3, len(orig_lines) * 2):
        return True
    if len(orig_lines) == 1:
        return False
    return len(matched.strip()) > max(len(original.strip()) + 500, len(original.strip()) * 4)


# --- Replacers (each yields matched spans from content) ---

def _simple_replacer(content: str, find: str):
    """Exact match."""
    if find in content:
        yield find


def _line_trimmed_replacer(content: str, find: str):
    """Match with each line trimmed."""
    orig_lines = content.split("\n")
    search_lines = find.split("\n")
    if search_lines and search_lines[-1] == "":
        search_lines = search_lines[:-1]
    if len(search_lines) == 0:
        return
    for i in range(len(orig_lines) - len(search_lines) + 1):
        if all(orig_lines[i + j].strip() == search_lines[j].strip() for j in range(len(search_lines))):
            start = sum(len(orig_lines[k]) + 1 for k in range(i))
            end = start
            for k in range(len(search_lines)):
                end += len(orig_lines[i + k])
                if k < len(search_lines) - 1:
                    end += 1
            yield content[start:end]


def _block_anchor_replacer(content: str, find: str):
    """Match first+last line anchors, verify middle with Levenshtein."""
    orig_lines = content.split("\n")
    search_lines = find.split("\n")
    if search_lines and search_lines[-1] == "":
        search_lines = search_lines[:-1]
    if len(search_lines) < 3:
        return
    first_search = search_lines[0].strip()
    last_search = search_lines[-1].strip()
    search_size = len(search_lines)
    max_delta = max(1, int(search_size * 0.25))
    threshold = 0.65

    candidates = []
    for i in range(len(orig_lines)):
        if orig_lines[i].strip() != first_search:
            continue
        for j in range(i + 2, len(orig_lines)):
            if orig_lines[j].strip() == last_search:
                actual_size = j - i + 1
                if abs(actual_size - search_size) <= max_delta:
                    candidates.append((i, j))
                break

    if not candidates:
        return

    def _similarity(start: int, end: int) -> float:
        actual_size = end - start + 1
        lines_to_check = min(search_size - 2, actual_size - 2)
        if lines_to_check <= 0:
            return 1.0
        sim = 0.0
        for j in range(1, min(search_size - 1, actual_size - 1)):
            o = orig_lines[start + j].strip()
            s = search_lines[j].strip()
            max_len = max(len(o), len(s))
            if max_len == 0:
                continue
            sim += (1 - _levenshtein(o, s) / max_len) / lines_to_check
            if sim >= threshold:
                break
        return sim

    if len(candidates) == 1:
        s, e = candidates[0]
        if _similarity(s, e) >= threshold:
            start = sum(len(orig_lines[k]) + 1 for k in range(s))
            end = start
            for k in range(s, e + 1):
                end += len(orig_lines[k])
                if k < e:
                    end += 1
            yield content[start:end]
        return

    best = None
    best_sim = -1.0
    for s, e in candidates:
        sim = _similarity(s, e)
        if sim > best_sim:
            best_sim = sim
            best = (s, e)
    if best_sim >= threshold and best:
        s, e = best
        start = sum(len(orig_lines[k]) + 1 for k in range(s))
        end = start
        for k in range(s, e + 1):
            end += len(orig_lines[k])
            if k < e:
                end += 1
        yield content[start:end]


def _whitespace_normalized_replacer(content: str, find: str):
    """Collapse all whitespace to single space before comparing."""
    def _norm(t):
        return " ".join(t.split())
    norm_find = _norm(find)
    lines = content.split("\n")
    for line in lines:
        if _norm(line) == norm_find:
            yield line
    find_lines = find.split("\n")
    if len(find_lines) > 1:
        for i in range(len(lines) - len(find_lines) + 1):
            block = "\n".join(lines[i:i + len(find_lines)])
            if _norm(block) == norm_find:
                yield block


def _indentation_flexible_replacer(content: str, find: str):
    """Strip leading indentation uniformly before comparing."""
    def _dedent(text):
        lines = text.split("\n")
        non_empty = [l for l in lines if l.strip()]
        if not non_empty:
            return text
        min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
        return "\n".join("" if l.strip() == "" else l[min_indent:] for l in lines)

    norm_find = _dedent(find)
    content_lines = content.split("\n")
    find_lines = find.split("\n")
    for i in range(len(content_lines) - len(find_lines) + 1):
        block = "\n".join(content_lines[i:i + len(find_lines)])
        if _dedent(block) == norm_find:
            yield block


def _escape_normalized_replacer(content: str, find: str):
    """Handle escape sequences like \\n, \\t."""
    def _unescape(s):
        return s.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r").replace("\\\\", "\\")
    unescaped = _unescape(find)
    if unescaped in content:
        yield unescaped
    lines = content.split("\n")
    find_lines = unescaped.split("\n")
    for i in range(len(lines) - len(find_lines) + 1):
        block = "\n".join(lines[i:i + len(find_lines)])
        if _unescape(block) == unescaped:
            yield block


def _trimmed_boundary_replacer(content: str, find: str):
    """Trim leading/trailing whitespace from the whole block."""
    trimmed = find.strip()
    if trimmed == find:
        return
    if trimmed in content:
        yield trimmed
    lines = content.split("\n")
    find_lines = find.split("\n")
    for i in range(len(lines) - len(find_lines) + 1):
        block = "\n".join(lines[i:i + len(find_lines)])
        if block.strip() == trimmed:
            yield block


def _context_aware_replacer(content: str, find: str):
    """Match first+last line anchors, verify 50% middle match."""
    find_lines = find.split("\n")
    if find_lines and find_lines[-1] == "":
        find_lines = find_lines[:-1]
    if len(find_lines) < 3:
        return
    first = find_lines[0].strip()
    last = find_lines[-1].strip()
    content_lines = content.split("\n")
    for i in range(len(content_lines)):
        if content_lines[i].strip() != first:
            continue
        for j in range(i + 2, len(content_lines)):
            if content_lines[j].strip() == last:
                block_lines = content_lines[i:j + 1]
                if len(block_lines) != len(find_lines):
                    break
                match_count = 0
                non_empty = 0
                for k in range(1, len(block_lines) - 1):
                    bl = block_lines[k].strip()
                    fl = find_lines[k].strip()
                    if bl or fl:
                        non_empty += 1
                        if bl == fl:
                            match_count += 1
                if non_empty == 0 or match_count / non_empty >= 0.5:
                    yield "\n".join(block_lines)
                break


def _multi_occurrence_replacer(content: str, find: str):
    """Find all exact occurrences (for replaceAll)."""
    idx = 0
    while True:
        pos = content.find(find, idx)
        if pos == -1:
            break
        yield find
        idx = pos + len(find)


_REPLACERS = [
    _simple_replacer,
    _line_trimmed_replacer,
    _block_anchor_replacer,
    _whitespace_normalized_replacer,
    _indentation_flexible_replacer,
    _escape_normalized_replacer,
    _trimmed_boundary_replacer,
    _context_aware_replacer,
    _multi_occurrence_replacer,
]


def _fuzzy_replace(content: str, old: str, new: str, replace_all: bool = False) -> str:
    """
    Try to replace `old` with `new` in `content` using cascading fuzzy replacers.
    Returns the modified content or raises ValueError on failure.
    """
    if old == new:
        raise ValueError("No changes to apply: oldString and newString are identical.")
    if old == "":
        raise ValueError("oldString cannot be empty.")

    not_found = True
    for replacer in _REPLACERS:
        for match in replacer(content, old):
            idx = content.find(match)
            if idx == -1:
                continue
            not_found = False
            if _is_disproportionate_match(match, old):
                raise ValueError(
                    "Refusing replacement: matched span is much larger than oldString. "
                    "Provide more surrounding context."
                )
            if replace_all:
                return content.replace(match, new)
            last_idx = content.rfind(match)
            if idx != last_idx:
                continue
            return content[:idx] + new + content[idx + len(match):]

    if not_found:
        raise ValueError(
            "Could not find oldString in the file. "
            "It must match exactly, including whitespace and indentation."
        )
    raise ValueError(
        "Found multiple matches for oldString. "
        "Provide more surrounding context to make the match unique."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# In-memory pending store: edit_id → (file_path_str, new_content_str)
_pending: dict[str, tuple[str, str]] = {}


async def preview_smart_edit(
    file: str,
    old_code: str,
    new_code: str,
    mode: str = "fuzzy",
) -> SmartEditPreview:
    """
    Preview a smart code edit as a unified diff WITHOUT writing to disk.

    Modes:
      "fuzzy" — opencode-style fuzzy string matching (9 cascading replacers).
                Resilient to whitespace differences, handles duplicate names.
      "ast"   — AST-based block parsing (tree-sitter). Intelligently merges
                functions/classes/imports by name. Best for structured edits
                where you want import merging and block-level replacement.

    Args:
        file:     Relative path to the file inside REPO_PATH.
        old_code: The text to find and replace.
        new_code: The replacement text.
        mode:     "fuzzy" (default) or "ast".

    Returns:
        SmartEditPreview with diff, lines_changed, and (for ast mode) block results.
    """
    if mode == "ast":
        return await preview_smart_edit_ast(file, old_code, new_code)
    return await _preview_smart_edit_fuzzy(file, old_code, new_code)


async def _preview_smart_edit_fuzzy(
    file: str, old_code: str, new_code: str, replace_all: bool = False
) -> SmartEditPreview:
    """Fuzzy string-based edit preview (opencode approach)."""
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    file_path = (repo_root / file).resolve()

    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file}")

    original = file_path.read_text(encoding="utf-8", errors="replace")

    norm_original = original.replace("\r\n", "\n")
    norm_old = old_code.replace("\r\n", "\n")
    norm_new = new_code.replace("\r\n", "\n")

    merged = _fuzzy_replace(norm_original, norm_old, norm_new, replace_all=replace_all)

    if "\r\n" in original:
        merged = merged.replace("\n", "\r\n")

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
            (edit_id, file, old_code, new_code, diff_str, time.time())
        )
        await db.commit()

    return SmartEditPreview(
        edit_id=edit_id,
        file=file,
        diff=diff_str,
        lines_changed=lines_changed,
        blocks=[],
    )


async def preview_smart_edit_ast(file: str, old_code: str, new_code: str) -> SmartEditPreview:
    """
    AST-based block edit preview. Parses new_code into top-level blocks
    (functions, classes, imports, constants) and applies each onto the file
    using tree-sitter symbol matching.

    Improvements over legacy:
    - class-aware matching: detects which class a method belongs to
    - no double-newline on replacements
    - None-name guard before AST lookups

    Args:
        file:     Relative path to the file inside REPO_PATH.
        old_code: Not used for AST mode (kept for interface compatibility).
                  The new_code is parsed into blocks and merged.
        new_code: Code containing blocks to merge into the file.

    Returns:
        SmartEditPreview with diff, lines_changed, and per-block results.
    """
    repo_root = Path(os.getenv("REPO_PATH", ".")).resolve()
    file_path = (repo_root / file).resolve()

    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file}")

    original = file_path.read_text(encoding="utf-8", errors="replace")

    blocks = _parse_blocks(new_code, file_path_hint=file)

    # Auto-detect class context for function blocks
    # If a function name appears in multiple classes, try to disambiguate
    class_context = None
    for block in blocks:
        if block.kind == "function" and block.name:
            ctx = _detect_class_context(original, block.name)
            if ctx:
                class_context = ctx
                break

    merged, block_results = _apply_blocks_ast(
        original, blocks, file_path_hint=file, class_context=class_context
    )

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
            (edit_id, file, old_code, new_code, diff_str, time.time())
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

def _find_best_match(
    norm_old: str,
    norm_original: str,
    threshold: float = 0.85,
) -> tuple[int, int, float] | None:
    """
    Find the best fuzzy match of norm_old inside norm_original using a
    sliding window over lines.

    Tracks top-2 scores in a single pass and raises ValueError if two
    candidates are both above threshold and within 5% of each other —
    meaning the match is ambiguous and old_code needs more context.

    Returns:
        (start_char_index, end_char_index, ratio) if a clear best match
        is found above `threshold`, else None.

    Raises:
        ValueError: if two blocks score above threshold within 5% of each
                    other (ambiguous match).
    """
    old_lines = norm_old.splitlines()
    orig_lines = norm_original.splitlines()
    n = len(old_lines)

    if n == 0 or n > len(orig_lines):
        return None

    old_joined = "\n".join(old_lines)

    best_ratio = 0.0
    second_best_ratio = 0.0
    best_start_line: int | None = None

    for i in range(len(orig_lines) - n + 1):
        window = "\n".join(orig_lines[i : i + n])
        ratio = difflib.SequenceMatcher(
            None, old_joined, window, autojunk=False
        ).ratio()
        if ratio > best_ratio:
            second_best_ratio = best_ratio
            best_ratio = ratio
            best_start_line = i
        elif ratio > second_best_ratio:
            second_best_ratio = ratio

    if best_ratio < threshold or best_start_line is None:
        return None

    # Ambiguity guard: two candidates both above threshold and too close
    if second_best_ratio >= threshold and (best_ratio - second_best_ratio) < 0.05:
        raise ValueError(
            f"Ambiguous match: two blocks scored {best_ratio:.0%} and "
            f"{second_best_ratio:.0%}. Provide more context in old_code "
            "to disambiguate."
        )

    # Convert best line index to char offsets
    lines_with_endings = norm_original.splitlines(keepends=True)
    start_char = sum(len(l) for l in lines_with_endings[:best_start_line])
    end_char = sum(len(l) for l in lines_with_endings[:best_start_line + n])

    return start_char, end_char, best_ratio


