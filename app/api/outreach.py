"""Receive a user's goal and connect the HTTP request to the workflow."""

from fastapi import APIRouter

from app.models.schemas import OutreachRequest
from app.orchestration.state import OutreachState
from app.orchestration.workflow import run_workflow

# A router groups endpoints; main.py registers this group with the application.
router = APIRouter()


# POST /outreach accepts a JSON request. The response model describes and
# validates the outgoing state, which FastAPI converts to JSON for the caller.
@router.post("/outreach", response_model=OutreachState, tags=["outreach"])
# FastAPI uses the request's type annotation to validate incoming data before
# this function runs. The return annotation says the result is OutreachState.
async def create_outreach(request: OutreachRequest) -> OutreachState:
    """Initialize the workflow for a validated outreach goal."""
    # Create a new record for this request using its already validated goal.
    state = OutreachState(goal=request.goal)
    # await waits for the asynchronous workflow to finish before responding.
    return await run_workflow(state)
