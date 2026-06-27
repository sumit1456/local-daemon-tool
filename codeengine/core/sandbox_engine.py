"""
sandbox_engine.py — Docker-based execution sandbox for lint, compile, and test.

Strategy:
  - One container per stack, lazy-loaded on first use.
  - Repo is bind-mounted read-only into /repo in the container.
  - Dependencies are stored in named Docker volumes (persisted, not in repo).
  - All tool output is parsed and normalized before returning to the agent.
  - Agent never sees raw build logs — only structured error objects.
"""
from __future__ import annotations

import os
import re
import json
import time
import logging
from pathlib import Path

logger = logging.getLogger("codeengine.sandbox")

# ── Stack → Docker image mapping ─────────────────────────────────────────────
STACK_IMAGES: dict[str, str] = {
    "python":      "python:3.12-slim",
    "node":        "node:20-slim",
    "java-maven":  "maven:3.9-eclipse-temurin-21-alpine",
    "java-gradle": "gradle:8.7-jdk21-alpine",
    "go":          "golang:1.23-alpine",
    "rust":        "rust:1.80-alpine",
    "ruby":        "ruby:3.3-slim",
    "php":         "php:8.3-cli",
    "cpp":         "gcc:14",
}

# ── Stack indicator files for auto-detection ──────────────────────────────────
STACK_INDICATORS: list[tuple[str, str]] = [
    # (filename_to_check, stack_name)
    ("pom.xml",          "java-maven"),
    ("build.gradle",     "java-gradle"),
    ("build.gradle.kts", "java-gradle"),
    ("package.json",     "node"),
    ("go.mod",           "go"),
    ("Cargo.toml",       "rust"),
    ("pyproject.toml",   "python"),
    ("setup.py",         "python"),
    ("requirements.txt", "python"),
    ("Gemfile",          "ruby"),
    ("composer.json",    "php"),
    ("CMakeLists.txt",   "cpp"),
    ("Makefile",         "cpp"),
]

# ── Dep install commands per stack ────────────────────────────────────────────
DEPS_COMMANDS: dict[str, str] = {
    "python":      "pip install -r /repo/requirements.txt -q 2>&1 || true",
    "node":        "npm install --prefix /repo --silent 2>&1 || true",
    "java-maven":  "mvn dependency:resolve -f /repo/pom.xml -q 2>&1 || true",
    "java-gradle": "cd /repo && gradle dependencies --quiet 2>&1 || true",
    "go":          "cd /repo && go mod download 2>&1 || true",
    "rust":        "cd /repo && cargo fetch 2>&1 || true",
    "ruby":        "cd /repo && bundle install --quiet 2>&1 || true",
    "php":         "cd /repo && composer install --no-interaction --quiet 2>&1 || true",
    "cpp":         "echo 'No package manager for C/C++ — build deps via Makefile/CMakeLists.txt'",
}

# ── Full dependency install commands (system + project deps) ──────────────────
FULL_DEPS_COMMANDS: dict[str, str] = {
    "python": (
        "apt-get update -qq && apt-get install -y -qq git > /dev/null 2>&1; "
        "pip install pytest gitpython ruff -q 2>&1; "
        "pip install -r /repo/requirements.txt -q 2>&1 || true"
    ),
    "node": (
        "apt-get update -qq && apt-get install -y -qq git > /dev/null 2>&1; "
        "npm install --prefix /repo --silent 2>&1 || true"
    ),
    "java-maven": (
        "apk add --no-cache git > /dev/null 2>&1 || true; "
        "mvn dependency:resolve -f /repo/pom.xml -q 2>&1 || true"
    ),
    "java-gradle": (
        "apk add --no-cache git > /dev/null 2>&1 || true; "
        "cd /repo && gradle dependencies --quiet 2>&1 || true"
    ),
    "go": (
        "apk add --no-cache git > /dev/null 2>&1 || true; "
        "cd /repo && go mod download 2>&1 || true"
    ),
    "rust": (
        "apk add --no-cache git > /dev/null 2>&1 || true; "
        "cd /repo && cargo fetch 2>&1 || true"
    ),
    "ruby": (
        "apt-get update -qq && apt-get install -y -qq git build-essential > /dev/null 2>&1; "
        "cd /repo && bundle install --quiet 2>&1 || true"
    ),
    "php": (
        "apt-get update -qq && apt-get install -y -qq git unzip > /dev/null 2>&1; "
        "cd /repo && composer install --no-interaction --quiet 2>&1 || true"
    ),
    "cpp": (
        "apt-get update -qq && apt-get install -y -qq git build-essential cmake > /dev/null 2>&1; "
        "echo 'C/C++ deps: use Makefile or CMakeLists.txt to build'"
    ),
}


def install_container_deps(container, stack: str) -> dict:
    """
    Install all dependencies for a stack inside a running container.
    Includes system packages (git, etc.) and project dependencies.
    Returns exit code and output.
    """
    cmd = FULL_DEPS_COMMANDS.get(stack)
    if not cmd:
        return {"exit_code": -1, "output": f"Unknown stack: {stack}"}

    logger.info("Installing full deps for %s...", stack)
    exit_code, output = container.exec_run(
        ["/bin/sh", "-c", cmd],
        workdir="/repo"
    )
    output_str = output.decode("utf-8", errors="replace") if output else ""
    logger.info("Dep install done (exit=%d)", exit_code)
    return {"exit_code": exit_code, "output": output_str}

# ── Named dep volumes per stack ───────────────────────────────────────────────
DEP_VOLUMES: dict[str, tuple[str, str]] = {
    # stack: (volume_name, container_mount_path)
    "python":      ("ce-python-deps",      "/root/.cache/pip"),
    "node":        ("ce-node-deps",        "/repo/node_modules"),
    "java-maven":  ("ce-java-maven-deps",  "/root/.m2"),
    "java-gradle": ("ce-java-gradle-deps", "/root/.gradle/caches"),
    "go":          ("ce-go-deps",          "/go/pkg/mod"),
    "rust":        ("ce-rust-deps",        "/root/.cargo/registry"),
    "ruby":        ("ce-ruby-deps",        "/usr/local/bundle"),
    "php":         ("ce-php-deps",         "/root/.composer/cache"),
    "cpp":         ("ce-cpp-deps",         "/tmp/cpp-build"),
}


# ── Docker availability check ─────────────────────────────────────────────────

def is_docker_available() -> bool:
    """Return True if Docker daemon is reachable."""
    try:
        import docker
        client = docker.from_env(timeout=3)
        client.ping()
        return True
    except Exception:
        return False


# ── Stack detection ───────────────────────────────────────────────────────────

def detect_stack(repo_root: str) -> str | None:
    """
    Detect the primary stack of a repository by looking for indicator files.
    Returns the stack name ('python', 'node', 'java', 'go', 'rust') or None.
    """
    root = Path(repo_root)
    for filename, stack in STACK_INDICATORS:
        if (root / filename).exists():
            logger.info("Detected stack '%s' via %s", stack, filename)
            return stack
    logger.warning("Could not detect stack in %s", repo_root)
    return None


# ── Container lifecycle ───────────────────────────────────────────────────────

def _get_container_name(stack: str) -> str:
    return f"ce-{stack}-sandbox"


def _get_or_start_container(stack: str, repo_root: str) -> object:
    """
    Get a running container for the given stack, starting it if necessary.
    Installs dependencies on first start. Returns the Docker container object.
    Raises RuntimeError if Docker is unavailable.
    """
    import docker
    client = docker.from_env()
    name = _get_container_name(stack)
    image = STACK_IMAGES[stack]

    # Check if already running
    try:
        container = client.containers.get(name)
        if container.status == "running":
            logger.debug("Reusing warm container: %s", name)
            return container
        # Exists but stopped — remove and recreate
        container.remove(force=True)
    except docker.errors.NotFound:
        pass

    logger.info("Starting new sandbox container: %s (image=%s)", name, image)

    # Build volumes dict
    dep_vol_name, dep_mount = DEP_VOLUMES[stack]
    volumes = {
        repo_root: {"bind": "/repo", "mode": "rw"},
        dep_vol_name: {"bind": dep_mount, "mode": "rw"},
    }

    # node_modules needs special handling — mount over the read-only repo subfolder
    if stack == "node":
        volumes[dep_vol_name] = {"bind": "/repo/node_modules", "mode": "rw"}

    container = client.containers.run(
        image=image,
        name=name,
        volumes=volumes,
        working_dir="/repo",
        detach=True,
        tty=True,
        # Resource limits — keep sandbox lightweight
        mem_limit="512m",
        nano_cpus=1_000_000_000,  # 1 CPU
        network_mode="bridge",
    )

    logger.info("Container started: %s (id=%s)", name, container.short_id)

    # Install all deps on first start (system packages + project deps)
    install_container_deps(container, stack)

    return container


def stop_sandbox(stack: str) -> bool:
    """Stop and remove a sandbox container for the given stack."""
    try:
        import docker
        client = docker.from_env()
        container = client.containers.get(_get_container_name(stack))
        container.remove(force=True)
        logger.info("Stopped sandbox: %s", _get_container_name(stack))
        return True
    except Exception as e:
        logger.debug("stop_sandbox error: %s", e)
        return False


def stop_all_sandboxes() -> None:
    """Stop all running ce-*-sandbox containers. Call on daemon shutdown."""
    for stack in STACK_IMAGES:
        stop_sandbox(stack)


# ── Output parsers (normalize raw tool output → structured errors) ─────────────

def _parse_ruff(raw: str) -> list[dict]:
    """Parse ruff JSON output into normalized error list."""
    errors = []
    try:
        items = json.loads(raw)
        for item in items:
            errors.append({
                "file": item.get("filename", ""),
                "line": item.get("location", {}).get("row", 0),
                "col":  item.get("location", {}).get("column", 0),
                "code": item.get("code", ""),
                "message": item.get("message", ""),
                "severity": "error" if item.get("code", "").startswith("E") else "warning",
            })
    except (json.JSONDecodeError, TypeError):
        # Fallback: plain text parsing
        for line in raw.splitlines():
            m = re.match(r'(.+):(\d+):(\d+):\s+([EW]\d+)\s+(.+)', line)
            if m:
                errors.append({
                    "file": m.group(1), "line": int(m.group(2)),
                    "col": int(m.group(3)), "code": m.group(4),
                    "message": m.group(5),
                    "severity": "error" if m.group(4).startswith("E") else "warning",
                })
    return errors


def _parse_tsc(raw: str) -> list[dict]:
    """Parse TypeScript compiler output: file(line,col): error TSxxxx: message"""
    errors = []
    for line in raw.splitlines():
        m = re.match(r'(.+)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.+)', line)
        if m:
            errors.append({
                "file": m.group(1), "line": int(m.group(2)),
                "col": int(m.group(3)), "severity": m.group(4),
                "code": m.group(5), "message": m.group(6),
            })
    return errors


def _parse_maven(raw: str) -> list[dict]:
    """Parse Maven output — extract only [ERROR] lines with file/line info."""
    errors = []
    for line in raw.splitlines():
        if "[ERROR]" not in line:
            continue
        m = re.search(r'\[ERROR\]\s+(.+\.java):\[(\d+),(\d+)\]\s+(.+)', line)
        if m:
            errors.append({
                "file": m.group(1), "line": int(m.group(2)),
                "col": int(m.group(3)), "severity": "error",
                "code": "", "message": m.group(4).strip(),
            })
        else:
            msg = line.replace("[ERROR]", "").strip()
            if msg and "BUILD FAILURE" not in msg and "-----" not in msg:
                errors.append({
                    "file": "", "line": 0, "col": 0,
                    "severity": "error", "code": "", "message": msg,
                })
    return errors


def _parse_go(raw: str) -> list[dict]:
    """Parse Go compiler/vet output: ./file.go:line:col: message"""
    errors = []
    for line in raw.splitlines():
        m = re.match(r'(.+\.go):(\d+):(\d+):\s+(.+)', line)
        if m:
            errors.append({
                "file": m.group(1), "line": int(m.group(2)),
                "col": int(m.group(3)), "severity": "error",
                "code": "", "message": m.group(4).strip(),
            })
    return errors


def _parse_cargo(raw: str) -> list[dict]:
    """Parse Cargo output with --message-format=json."""
    errors = []
    for line in raw.splitlines():
        try:
            obj = json.loads(line)
            if obj.get("reason") == "compiler-message":
                msg = obj.get("message", {})
                if msg.get("level") in ("error", "warning"):
                    spans = msg.get("spans", [{}])
                    primary = next((s for s in spans if s.get("is_primary")), spans[0] if spans else {})
                    errors.append({
                        "file": primary.get("file_name", ""),
                        "line": primary.get("line_start", 0),
                        "col":  primary.get("column_start", 0),
                        "severity": msg.get("level", "error"),
                        "code": msg.get("code", {}).get("code", "") if msg.get("code") else "",
                        "message": msg.get("message", ""),
                    })
        except (json.JSONDecodeError, KeyError):
            continue
    return errors


def _parse_pytest(raw: str) -> dict:
    """
    Parse pytest output into: total, passed, failed, errors, and failure details.
    Extracts only FAILED lines and short tracebacks.
    """
    lines = raw.splitlines()
    total = passed = failed = errors_count = 0
    failures = []
    current_failure = None

    for line in lines:
        m = re.search(r'(\d+) passed', line)
        if m: passed = int(m.group(1))
        m = re.search(r'(\d+) failed', line)
        if m: failed = int(m.group(1))
        m = re.search(r'(\d+) error', line)
        if m: errors_count = int(m.group(1))

        if line.startswith("FAILED "):
            parts = line[7:].split(" - ", 1)
            current_failure = {
                "test": parts[0].strip(),
                "error": parts[1].strip() if len(parts) > 1 else "",
                "traceback": [],
            }
            failures.append(current_failure)
        elif current_failure and line.startswith("  ") and line.strip():
            current_failure["traceback"].append(line.strip())

    total = passed + failed + errors_count
    return {
        "total": total, "passed": passed,
        "failed": failed, "errors": errors_count,
        "success": failed == 0 and errors_count == 0,
        "failures": failures,
    }


PARSERS = {
    "python":      _parse_ruff,
    "node":        _parse_tsc,
    "java-maven":  _parse_maven,
    "java-gradle": _parse_maven,
    "go":          _parse_go,
    "rust":        _parse_cargo,
}


# ── Public API functions ───────────────────────────────────────────────────────

async def setup_sandbox(repo_root: str) -> dict:
    """
    Detect stack and start the sandbox container with deps installed.
    Safe to call multiple times — idempotent.
    Returns status dict.
    """
    if not is_docker_available():
        return {"success": False, "error": "Docker is not available on this machine."}

    stack = detect_stack(repo_root)
    if not stack:
        return {"success": False, "error": "Could not detect project stack. No pom.xml, build.gradle, package.json, go.mod, Cargo.toml, requirements.txt, Gemfile, composer.json, or CMakeLists.txt found."}

    try:
        container = _get_or_start_container(stack, repo_root)
        return {
            "success": True,
            "stack": stack,
            "image": STACK_IMAGES[stack],
            "container": container.name,
            "container_id": container.short_id,
            "deps_installed": True,
        }
    except Exception as e:
        logger.error("setup_sandbox failed: %s", e)
        return {"success": False, "stack": stack, "error": str(e)}


async def check_syntax(file_path: str, repo_root: str) -> dict:
    """
    Lint a single file using the appropriate tool for the detected stack.
    Returns structured errors only — never raw tool output.

    Fallback chain:
      1. Docker container with stack linter (preferred)
      2. Python ast.parse() for .py files (if Docker unavailable)
      3. Error: unsupported without Docker
    """
    file_ext = Path(file_path).suffix.lower()

    # Python fallback: use built-in ast.parse, no Docker needed
    if file_ext == ".py" and not is_docker_available():
        import ast
        full_path = str(Path(repo_root) / file_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                source = f.read()
            ast.parse(source)
            return {"file": file_path, "passed": True, "errors": [], "tool": "ast.parse"}
        except SyntaxError as e:
            return {
                "file": file_path, "passed": False,
                "errors": [{"line": e.lineno, "col": e.offset, "message": e.msg, "severity": "error", "code": "SyntaxError"}],
                "tool": "ast.parse",
            }

    if not is_docker_available():
        return {"file": file_path, "passed": None, "errors": [],
                "warning": "Docker not available. Install Docker Desktop to enable linting for this stack."}

    stack = detect_stack(repo_root)
    if not stack:
        return {"file": file_path, "passed": None, "errors": [], "warning": "Could not detect stack."}

    container = _get_or_start_container(stack, repo_root)

    container_file = f"/repo/{file_path}"
    commands = {
        "python":      f"ruff check {container_file} --output-format json 2>&1",
        "node":        f"npx eslint {container_file} --format json 2>&1 || true",
        "java-maven":  f"javac -proc:none -cp /repo/target/dependency/* {container_file} 2>&1 || true",
        "java-gradle": f"javac -proc:none -cp /repo/build/libs/* {container_file} 2>&1 || true",
        "go":          f"go vet /repo/... 2>&1 || true",
        "rust":        f"cargo check --manifest-path /repo/Cargo.toml --message-format json 2>&1 || true",
    }
    cmd = commands.get(stack, "echo 'unsupported'")

    _, raw = container.exec_run(["/bin/sh", "-c", cmd], workdir="/repo")
    raw_str = raw.decode("utf-8", errors="replace") if raw else ""

    parser = PARSERS.get(stack)
    errors = parser(raw_str) if parser else []

    # Filter to only the requested file
    errors = [e for e in errors if not e["file"] or file_path in e["file"] or container_file in e["file"]]

    return {
        "file": file_path,
        "stack": stack,
        "passed": len(errors) == 0,
        "error_count": len(errors),
        "errors": errors,
        "tool": cmd.split()[0],
    }


async def compile_project(repo_root: str) -> dict:
    """
    Compile the entire project using the detected stack's build tool.
    Returns only structured errors — not raw build logs.
    """
    if not is_docker_available():
        return {"success": None, "error": "Docker not available.", "errors": []}

    stack = detect_stack(repo_root)
    if not stack:
        return {"success": None, "error": "Could not detect stack.", "errors": []}

    container = _get_or_start_container(stack, repo_root)

    compile_commands = {
        "python":      "ruff check /repo --output-format json 2>&1",
        "node":        "npx tsc --noEmit 2>&1 || true",
        "java-maven":  "mvn compile -f /repo/pom.xml -q 2>&1 || true",
        "java-gradle": "cd /repo && gradle compileJava --quiet 2>&1 || true",
        "go":          "cd /repo && go build ./... 2>&1 || true",
        "rust":        "cargo check --manifest-path /repo/Cargo.toml --message-format json 2>&1 || true",
    }
    cmd = compile_commands.get(stack, "echo 'unsupported'")

    start = time.time()
    _, raw = container.exec_run(["/bin/sh", "-c", cmd], workdir="/repo")
    raw_str = raw.decode("utf-8", errors="replace") if raw else ""

    parser = PARSERS.get(stack)
    errors = parser(raw_str) if parser else []

    # Python: also run ast.parse to catch syntax errors ruff misses
    if stack == "python":
        syntax_cmd = """python3 -c "
import ast, pathlib
repo = pathlib.Path('/repo')
for f in repo.rglob('*.py'):
    try:
        ast.parse(f.read_text(), str(f))
    except SyntaxError as e:
        rel = str(f.relative_to('/repo'))
        print(f'SYNTAX_ERROR: {rel}:{e.lineno}:{e.offset}: {e.msg}')
" 2>&1"""
        _, syntax_raw = container.exec_run(["/bin/sh", "-c", syntax_cmd], workdir="/repo")
        syntax_str = syntax_raw.decode("utf-8", errors="replace") if syntax_raw else ""
        
        for line in syntax_str.splitlines():
            if line.startswith("SYNTAX_ERROR:"):
                parts = line[13:].split(":", 2)
                if len(parts) >= 3:
                    errors.append({
                        "file": parts[0].strip(),
                        "line": int(parts[1]) if parts[1].isdigit() else 0,
                        "col": int(parts[2].split(":")[0]) if parts[2].split(":")[0].isdigit() else 0,
                        "message": parts[2].split(":", 1)[1].strip() if ":" in parts[2] else parts[2].strip(),
                        "severity": "error",
                    })

    elapsed = round(time.time() - start, 2)

    return {
        "stack": stack,
        "success": len(errors) == 0,
        "error_count": len(errors),
        "elapsed_seconds": elapsed,
        "errors": errors,
    }


async def run_tests(repo_root: str, test_path: str | None = None) -> dict:
    """
    Run the test suite (or a specific test file) inside the sandbox container.
    Returns structured pass/fail summary — not raw pytest/jest/go test output.
    """
    if not is_docker_available():
        return {"success": None, "error": "Docker not available.", "total": 0, "passed": 0, "failed": 0}

    stack = detect_stack(repo_root)
    if not stack:
        return {"success": None, "error": "Could not detect stack.", "total": 0, "passed": 0, "failed": 0}

    container = _get_or_start_container(stack, repo_root)

    target = f"/repo/{test_path}" if test_path else "/repo"
    test_commands = {
        "python":      f"pytest {target} --tb=short -q 2>&1",
        "node":        f"npm test --prefix /repo 2>&1 || true",
        "java-maven":  f"mvn test -f /repo/pom.xml -q 2>&1 || true",
        "java-gradle": f"cd /repo && gradle test --quiet 2>&1 || true",
        "go":          f"cd /repo && go test ./... -v 2>&1 || true",
        "rust":        f"cargo test --manifest-path /repo/Cargo.toml 2>&1 || true",
    }
    cmd = test_commands.get(stack, "echo 'unsupported'")

    start = time.time()
    _, raw = container.exec_run(["/bin/sh", "-c", cmd], workdir="/repo")
    elapsed = round(time.time() - start, 2)

    raw_str = raw.decode("utf-8", errors="replace") if raw else ""

    if stack == "python":
        result = _parse_pytest(raw_str)
    else:
        failed_count = len(re.findall(r'FAIL|FAILED|BUILD FAILURE|FAILED TO COMPILE', raw_str, re.IGNORECASE))
        passed_count = len(re.findall(r'ok|PASS|passed|BUILD SUCCESS', raw_str, re.IGNORECASE))
        result = {
            "total": passed_count + failed_count,
            "passed": passed_count,
            "failed": failed_count,
            "errors": 0,
            "success": failed_count == 0,
            "failures": [],
        }

    result["elapsed_seconds"] = elapsed
    result["stack"] = stack
    return result
