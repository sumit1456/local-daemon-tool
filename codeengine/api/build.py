from fastapi import APIRouter
from pydantic import BaseModel
from codeengine.core.worker_manager import build_project, run_tests, lint_project
from codeengine.models.edit_models import WorkerResult

router = APIRouter(tags=["build"])

class WorkerRequest(BaseModel):
    """Schema for container execution request."""
    lang: str
    repo_path: str

@router.post("/build", response_model=WorkerResult)
async def build_route(req: WorkerRequest):
    """Build the repository within a worker container."""
    return await build_project(req.lang, req.repo_path)

@router.post("/test", response_model=WorkerResult)
async def test_route(req: WorkerRequest):
    """Run test suite within a worker container."""
    return await run_tests(req.lang, req.repo_path)

@router.post("/lint", response_model=WorkerResult)
async def lint_route(req: WorkerRequest):
    """Run linter within a worker container."""
    return await lint_project(req.lang, req.repo_path)
