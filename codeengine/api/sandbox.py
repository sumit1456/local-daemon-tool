from fastapi import APIRouter, Query
from pydantic import BaseModel
from codeengine.core.sandbox_engine import (
    setup_sandbox, check_syntax, compile_project, run_tests,
    stop_sandbox, detect_stack, is_docker_available,
    install_container_deps, _get_or_start_container,
)
import os

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


class TerminalCommand(BaseModel):
    command: str


@router.post("/terminal/exec")
async def terminal_exec_route(
    cmd: TerminalCommand,
    stack: str | None = Query(None, description="Stack name (auto-detected if omitted)"),
):
    """Execute a shell command inside the sandbox container. Returns stdout+stderr."""
    repo = os.getenv("REPO_PATH", ".")
    if not is_docker_available():
        return {"success": False, "error": "Docker is not available."}

    _stack = stack or detect_stack(repo)
    if not _stack:
        return {"success": False, "error": "Could not detect stack."}

    try:
        container = _get_or_start_container(_stack, repo)
        exit_code, output = container.exec_run(
            ["/bin/sh", "-c", cmd.command],
            workdir="/repo"
        )
        output_str = output.decode("utf-8", errors="replace") if output else ""
        return {"success": True, "exit_code": exit_code, "output": output_str, "stack": _stack}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/terminal/exec-local")
async def terminal_exec_local_route(cmd: TerminalCommand):
    """Execute a shell command on the host machine (not in Docker). Returns stdout+stderr."""
    import subprocess
    try:
        result = subprocess.run(
            cmd.command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.getenv("REPO_PATH", "."),
        )
        return {
            "success": True,
            "exit_code": result.returncode,
            "output": result.stdout + result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out (30s limit)."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/setup")
async def setup_sandbox_route():
    """Detect stack and start the sandbox container with deps installed."""
    repo = os.getenv("REPO_PATH", ".")
    return await setup_sandbox(repo)


@router.get("/status")
async def sandbox_status_route():
    """Return Docker availability and detected stack for the current repo."""
    repo = os.getenv("REPO_PATH", ".")
    return {
        "docker_available": is_docker_available(),
        "detected_stack": detect_stack(repo),
        "repo": repo,
    }


@router.get("/lint")
async def lint_route(
    file: str = Query(..., description="Relative file path to lint"),
):
    """Lint a single file inside the sandbox. Returns structured errors only."""
    repo = os.getenv("REPO_PATH", ".")
    return await check_syntax(file, repo)


@router.post("/compile")
async def compile_route():
    """Compile the full project inside the sandbox. Returns structured errors only."""
    repo = os.getenv("REPO_PATH", ".")
    return await compile_project(repo)


@router.post("/test")
async def test_route(
    path: str | None = Query(None, description="Optional relative path to specific test file or dir"),
):
    """Run tests inside the sandbox. Returns structured pass/fail summary only."""
    repo = os.getenv("REPO_PATH", ".")
    return await run_tests(repo, path)


@router.delete("/stop")
async def stop_sandbox_route(
    stack: str = Query(..., description="Stack to stop: python | node | java | go | rust"),
):
    """Stop and remove a specific sandbox container."""
    return {"stopped": stop_sandbox(stack)}


@router.post("/install-deps")
async def install_deps_route():
    """Reinstall all dependencies (system packages + project deps) in the sandbox."""
    repo = os.getenv("REPO_PATH", ".")
    stack = detect_stack(repo)
    if not stack:
        return {"success": False, "error": "Could not detect stack"}
    container = _get_or_start_container(stack, repo)
    result = install_container_deps(container, stack)
    return {
        "success": result["exit_code"] == 0,
        "stack": stack,
        "output": result["output"],
    }
