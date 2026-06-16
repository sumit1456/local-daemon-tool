from fastapi import APIRouter, Query
from codeengine.core.sandbox_engine import (
    setup_sandbox, check_syntax, compile_project, run_tests,
    stop_sandbox, detect_stack, is_docker_available,
    install_container_deps, _get_or_start_container,
)
import os

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


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
