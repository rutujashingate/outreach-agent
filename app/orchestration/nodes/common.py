"""Small shared helpers for the nodes that process individual prospects."""

import asyncio

from app.models.workflow import Outcome, WorkflowState
from app.orchestration.context import WorkflowContext
from app.observability import trace


async def for_each(prospects, operation, context: WorkflowContext, *, run_id: str, stage: str):
    """Bound concurrency and retain each result with its original prospect."""
    semaphore = asyncio.Semaphore(context.limits.concurrency)

    async def execute(prospect):
        async with semaphore:
            try:
                return prospect, await operation(prospect)
            except Exception as error:
                trace(context.repository, run_id, "prospect_failure", stage=stage,
                      prospect_id=prospect.id, error_type=type(error).__name__)
                return prospect, error

    return await asyncio.gather(*(execute(prospect) for prospect in prospects))


def allowed_prospects(state: WorkflowState):
    return [prospect for prospect in state.qualified_prospects
            if prospect.id in state.contact_decisions and state.contact_decisions[prospect.id].allowed
            and prospect.id not in state.outcomes]


def failure(state: WorkflowState, prospect_id: str, stage: str) -> Outcome:
    return Outcome(prospect_id=prospect_id, status="failed", reason=f"{stage} could not complete.",
                   source=f"run:{state.run_id}:{stage}")
