"""
git_engine.py — Git history indexing for per-symbol change tracking.
Parses git log output and maps each commit's diff to indexed symbols.
"""
from __future__ import annotations

import re
import subprocess
import logging
import os
from pathlib import Path

from codeengine.database.sqlite import get_db

logger = logging.getLogger("codeengine.git")


def _run_git(args: list[str], cwd: str) -> str:
    """Run a git command and return stdout as a string."""
    kwargs: dict = {"cwd": cwd, "capture_output": True, "text": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(["git"] + args, **kwargs)
    return result.stdout


def _classify_change(old_lines: list[str], new_lines: list[str]) -> str:
    """Classify the type of change made to a function block."""
    if not old_lines:
        return "new"
    if not new_lines:
        return "deleted"
    old_sig = old_lines[0] if old_lines else ""
    new_sig = new_lines[0] if new_lines else ""
    if old_sig.strip() != new_sig.strip():
        return "signature_change"
    return "logic_edit"


async def index_git_history(repo_root: str, max_commits: int = 200) -> int:
    """
    Walk the last `max_commits` commits of the git repo.
    For each commit, parse which functions changed and record them
    in the git_history table. Returns total rows inserted.
    """
    root = Path(repo_root).resolve()

    # Get list of commits: hash|date|subject
    log_output = _run_git(
        ["log", f"-{max_commits}", "--format=%H|%aI|%s", "--diff-filter=AM"],
        cwd=str(root)
    )
    if not log_output.strip():
        logger.warning("No git history found in %s", root)
        return 0

    commits = []
    for line in log_output.strip().splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({"hash": parts[0], "date": parts[1], "msg": parts[2]})

    total_inserted = 0

    async with get_db() as db:
        for commit in commits:
            # Get the diff for this commit (only +/- lines, no context)
            diff_output = _run_git(
                ["diff", "--unified=0", f"{commit['hash']}^..{commit['hash']}"],
                cwd=str(root)
            )
            if not diff_output:
                continue

            # Parse diff: find which file and which lines changed
            current_file = None
            added_lines: set[int] = set()

            for diff_line in diff_output.splitlines():
                if diff_line.startswith("+++ b/"):
                    current_file = diff_line[6:]
                    added_lines = set()
                elif diff_line.startswith("@@ "):
                    # @@ -old_start,old_count +new_start,new_count @@
                    m = re.search(r'\+(\d+)(?:,(\d+))?', diff_line)
                    if m:
                        start = int(m.group(1))
                        count = int(m.group(2)) if m.group(2) else 1
                        added_lines.update(range(start, start + count))

                # When we finish a file block, look up which symbols were touched
                if current_file and added_lines:
                    # Find symbols in DB whose line ranges overlap with changed lines
                    async with db.execute(
                        """
                        SELECT s.id, s.name, s.kind, s.line_start, s.line_end
                        FROM symbols s
                        JOIN files f ON s.file_id = f.id
                        WHERE f.path = ?
                        """,
                        (current_file,)
                    ) as cur:
                        syms = await cur.fetchall()

                    for sym in syms:
                        sym_lines = set(range(sym["line_start"], sym["line_end"] + 1))
                        if sym_lines & added_lines:
                            lines_added = len(sym_lines & added_lines)
                            try:
                                await db.execute(
                                    """
                                    INSERT OR IGNORE INTO git_history
                                    (symbol_id, file_path, commit_hash, commit_date,
                                     commit_msg, change_type, lines_added, lines_removed)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (sym["id"], current_file, commit["hash"],
                                     commit["date"], commit["msg"],
                                     "logic_edit",  # simplified; extend if needed
                                     lines_added, 0)
                                )
                                total_inserted += 1
                            except Exception as e:
                                logger.debug("Insert skip: %s", e)

        await db.commit()

    logger.info("Git history indexed: %d rows", total_inserted)
    return total_inserted


async def get_function_history(symbol_name: str, limit: int = 20) -> dict:
    """
    Return the precomputed commit history for a symbol.
    Each entry shows: commit hash, date, message, change type, lines touched.
    """
    async with get_db() as db:
        async with db.execute(
            """
            SELECT gh.commit_hash, gh.commit_date, gh.commit_msg,
                   gh.change_type, gh.lines_added, gh.lines_removed, gh.file_path
            FROM git_history gh
            JOIN symbols s ON gh.symbol_id = s.id
            WHERE s.name = ?
            ORDER BY gh.commit_date DESC
            LIMIT ?
            """,
            (symbol_name, limit)
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        return {"symbol": symbol_name, "found": False, "history": []}

    history = [
        {
            "commit": r["commit_hash"][:8],
            "date": r["commit_date"],
            "message": r["commit_msg"],
            "change_type": r["change_type"],
            "lines_added": r["lines_added"],
            "lines_removed": r["lines_removed"],
            "file": r["file_path"],
        }
        for r in rows
    ]
    return {"symbol": symbol_name, "found": True, "total_commits": len(history), "history": history}
