import os
import json
import time
import asyncio
import shutil
from pathlib import Path


_SEMGREP_SEVERITY_MAP = {
    "ERROR":   "HIGH",
    "WARNING": "MEDIUM",
    "INFO":    "LOW",
}

# Semgrep registry shorthand configs (no local file needed, require internet)
_REGISTRY_PREFIXES = ("p/", "r/", "auto", "r2c")

# Directories to exclude from scanning by default (covers Python, Java, JS, C/C++, Rust, etc.)
DEFAULT_EXCLUDE_DIRS = [
    # Version control & IDE
    ".git", ".svn", ".hg",
    ".idea", ".vscode", ".eclipse", ".project",
    # Python
    ".venv", ".venv-mcp", "venv", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", ".tox", ".nox",
    "codeengine.egg-info", "*.egg-info",
    # Node / JavaScript / TypeScript
    "node_modules", ".npm", ".yarn", "dist", "build", ".next", ".nuxt",
    # Java / Kotlin
    "target", ".gradle", ".m2", "out", "bin",
    # C / C++
    "cmake-build-*", "CMakeFiles", ".cache",
    # Rust
    "target",  # also Rust's build dir
    # Go
    "vendor",
    # General
    ".code-scan", ".semgrep",
    # OS artifacts
    ".DS_Store", "Thumbs.db",
]


def _is_registry_config(config: str) -> bool:
    """Return True if config is a Semgrep registry reference, not a local file."""
    return config == "auto" or any(config.startswith(p) for p in _REGISTRY_PREFIXES)


def _find_semgrep() -> str:
    exe = shutil.which("semgrep")
    if exe:
        return exe
    venv_scripts = Path(__file__).parent.parent.parent / ".venv-mcp" / "Scripts" / "semgrep.exe"
    if venv_scripts.is_file():
        return str(venv_scripts)
    raise RuntimeError("semgrep not found — install with: .venv-mcp\\Scripts\\pip.exe install semgrep")


async def run_semgrep(config: str, repo_root: Path, exclude_dirs: list[str] | None = None) -> list[dict]:
    """
    Run semgrep with either:
    - A local YAML rulebook path
    - A Semgrep registry config string (e.g. 'auto', 'p/java', 'p/owasp-top-ten')
    """
    # Validate local files; registry configs pass through directly
    if not _is_registry_config(config):
        rulebook = Path(config)
        if not rulebook.is_file():
            raise FileNotFoundError(f"Semgrep rulebook not found: {config}")
        config_arg = str(rulebook)
    else:
        config_arg = config

    # Merge caller-provided exclusions with defaults
    dirs_to_exclude = list(DEFAULT_EXCLUDE_DIRS)
    if exclude_dirs:
        dirs_to_exclude.extend(d for d in exclude_dirs if d not in dirs_to_exclude)

    semgrep_bin = _find_semgrep()
    cmd = [
        semgrep_bin,
        "scan",
        "--config", config_arg,
        "--json",
        "--quiet",
        "--no-git-ignore",
    ]
    for d in dirs_to_exclude:
        cmd.extend(["--exclude", d])
    cmd.append(str(repo_root))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except FileNotFoundError:
        raise RuntimeError("semgrep not found — install with: pip install semgrep")
    except asyncio.TimeoutError:
        raise RuntimeError("semgrep scan timed out after 300s")

    if proc.returncode not in (0, 1):
        err_msg = stderr.decode("utf-8", errors="replace").strip()
        if not err_msg:
            try:
                partial = json.loads(stdout.decode("utf-8", errors="replace"))
                errs = partial.get("errors", [])
                if errs:
                    err_msg = "; ".join(
                        e.get("message") or e.get("short_msg") or str(e) for e in errs
                    )
            except Exception:
                pass
        raise RuntimeError(f"semgrep failed (exit {proc.returncode}): {err_msg or '(no error detail available)'}")

    raw = stdout.decode("utf-8", errors="replace")
    results = json.loads(raw)
    findings = []

    for r in results.get("results", []):
        # rule_id: strip dotted module prefix, keep only the last segment
        full_rule_id = r.get("check_id", "UNKNOWN")
        rule_id = full_rule_id.split(".")[-1] if "." in full_rule_id else full_rule_id

        file_path  = r.get("path", "")
        start_line = r.get("start", {}).get("line", 1)
        end_line   = r.get("end",   {}).get("line", start_line)
        extra      = r.get("extra", {})
        message    = extra.get("message", "").strip()
        severity   = _SEMGREP_SEVERITY_MAP.get(extra.get("severity", "INFO").upper(), "LOW")
        metadata   = extra.get("metadata", {})

        # snippet: prefer 'lines' from semgrep; fall back to reading the file directly
        snippet = extra.get("lines", "").strip()
        if not snippet or snippet == "requires login":
            try:
                abs_path = repo_root / file_path if not Path(file_path).is_absolute() else Path(file_path)
                lines = abs_path.read_text("utf-8", errors="replace").splitlines()
                snippet = lines[start_line - 1].strip() if 0 < start_line <= len(lines) else ""
            except Exception:
                snippet = ""

        try:
            rel_path = str(Path(file_path).relative_to(repo_root))
        except ValueError:
            rel_path = file_path

        findings.append({
            "rule_id":        rule_id,
            "title":          rule_id,
            "category":       metadata.get("category", "UNKNOWN"),
            "severity":       severity,
            "message":        message,
            "file":           rel_path,
            "line_start":     start_line,
            "line_end":       end_line,
            "snippet":        snippet[:500],
            "confidence":     float(metadata.get("confidence", 0.8)),
            "recommendation": metadata.get("recommendation", ""),
        })

    return findings


async def scan_codebase_internal(
    rulebook_path: str | None = None,
    rules: list[dict] | None = None,  # kept for API compat, ignored
    exclude_dirs: list[str] | None = None,
) -> dict:
    start_time = time.time()
    repo_root  = Path(os.getenv("REPO_PATH", ".")).resolve()

    # ── Resolve config ───────────────────────────────────────────────────────
    if rulebook_path:
        config = rulebook_path
        # Resolve relative local paths against repo_root
        if not _is_registry_config(config):
            p = Path(config)
            if not p.is_absolute():
                p = (repo_root / config).resolve()
            config = str(p)
    else:
        # Auto-discover first YAML rulebook under codeengine/rulebook/
        rulebook_base = Path(__file__).parent.parent / "rulebook"
        config = None
        if rulebook_base.is_dir():
            for candidate in sorted(rulebook_base.rglob("*.yaml")):
                config = str(candidate)
                break
        if config is None:
            raise FileNotFoundError(
                "No rulebook specified and no YAML rulebook found under "
                "codeengine/rulebook/. Pass rulebook_path explicitly "
                "(e.g. 'p/java', 'auto', or a local .yaml path)."
            )

    # ── Run Semgrep ──────────────────────────────────────────────────────────
    findings = await run_semgrep(config, repo_root, exclude_dirs=exclude_dirs)
    elapsed  = round(time.time() - start_time, 3)

    return {
        "findings":          findings,
        "total_findings":    len(findings),
        "scanned_files":     len({f["file"] for f in findings}),
        "scan_time_seconds": elapsed,
        "engine":            "semgrep",
        "config":            config,
    }
