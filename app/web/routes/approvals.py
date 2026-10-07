"""Submit approval, rejection, or edits for the exact paused draft version."""

from fastapi import APIRouter

from app.web.routes.runs import Manager, RunID
from app.domain.workflow import ApprovalSubmission, RunResponse

router = APIRouter(tags=["approval"])


@router.post("/runs/{run_id}/decisions", response_model=RunResponse)
async def submit_decisions(run_id: RunID, request: ApprovalSubmission, manager: Manager):
    """Resume the existing execution; send one decision for each pending draft."""
    return await manager.resume(run_id, request)
