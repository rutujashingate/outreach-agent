"""HTTP entry points for complete runs and their recorded execution history."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.web.routes.dependencies import get_manager
from app.domain.workflow import RunResponse, WorkflowRequest
from app.services.runs import RunManager

router = APIRouter(tags=["complete workflow"])
RunID = Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")]
Manager = Annotated[RunManager, Depends(get_manager)]


@router.post("/runs", response_model=RunResponse, status_code=201)
async def create_run(request: WorkflowRequest, manager: Manager):
    """Interpret, research, qualify, prepare a draft, and pause for approval."""
    return await manager.start(request)


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: RunID, manager: Manager):
    return manager.get(run_id)


@router.get("/runs/{run_id}/events")
async def get_events(run_id: RunID, manager: Manager):
    return manager.execution_events(run_id)


@router.post("/runs/{run_id}/retry", response_model=RunResponse)
async def retry_run(run_id: RunID, manager: Manager):
    """Continue a failed execution from its checkpoint within the same limits."""
    return await manager.retry(run_id)
