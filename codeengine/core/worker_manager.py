from codeengine.models.edit_models import WorkerResult

async def build_project(lang: str, repo_path: str) -> WorkerResult:
    """Stub function for project build in Stage 1."""
    return WorkerResult(
        exit_code=0,
        stdout="Build skipped (Docker workers are implemented in Stage 3)",
        stderr="",
        duration_ms=0
    )

async def run_tests(lang: str, repo_path: str) -> WorkerResult:
    """Stub function for running tests in Stage 1."""
    return WorkerResult(
        exit_code=0,
        stdout="Tests skipped (Docker workers are implemented in Stage 3)",
        stderr="",
        duration_ms=0
    )

async def lint_project(lang: str, repo_path: str) -> WorkerResult:
    """Stub function for running linter in Stage 1."""
    return WorkerResult(
        exit_code=0,
        stdout="Lint skipped (Docker workers are implemented in Stage 3)",
        stderr="",
        duration_ms=0
    )
