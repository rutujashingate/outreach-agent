"""Receive a user's goal and connect the HTTP request to the workflow."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.researcher import Researcher
from app.models.client import ModelClient, ModelClientError, OpenAIModelClient
from app.models.groq_client import GroqModelClient
from app.models.schemas import OutreachRequest
from app.orchestration.state import OutreachState
from app.orchestration.workflow import run_workflow

# A router groups endpoints; main.py registers this group with the application.
router = APIRouter()


async def get_research_client(request: OutreachRequest, http_request: Request) -> AsyncIterator[ModelClient | None]:
    """Provide a real client only for requests with evidence; tests can replace it."""
    if not request.research_material.strip():
        yield None
        return
    provider = http_request.app.state.settings.model_provider
    try:
        client = GroqModelClient.from_env() if provider == "groq" else OpenAIModelClient.from_env()
    except ValueError as error:
        raise HTTPException(
            status_code=503,
            detail=("Research requires GROQ_API_KEY and a supported GROQ_MODEL to be configured."
                    if provider == "groq" else "Research requires OPENAI_API_KEY and OPENAI_MODEL to be configured."),
        ) from error
    # This dependency owns the client and closes it after success or failure.
    async with client as ready_client:
        yield ready_client


# POST /outreach accepts a JSON request. The response model describes and
# validates the outgoing state, which FastAPI converts to JSON for the caller.
@router.post(
    "/outreach", response_model=OutreachState, tags=["outreach"],
    responses={502: {"description": "Research model request or output failed."},
               503: {"description": "Research model settings are missing."}},
)
# FastAPI uses the request's type annotation to validate incoming data before
# this function runs. The return annotation says the result is OutreachState.
async def create_outreach(
    request: OutreachRequest,
    client: Annotated[ModelClient | None, Depends(get_research_client)],
) -> OutreachState:
    """Research a validated goal using optional supplied evidence."""
    # Create a new record for this request using its already validated goal.
    state = OutreachState(goal=request.goal)
    # await waits for the asynchronous workflow to finish before responding.
    try:
        if request.research_material.strip():
            return await run_workflow(
                state, researcher=Researcher(client=client), research_material=request.research_material
            )
        return await run_workflow(state)
    except ModelClientError as error:
        # Keep provider details out of the HTTP response; direct callers still
        # receive the existing ModelClientError / ModelResponseError types.
        raise HTTPException(status_code=502, detail="Research could not complete.") from error
