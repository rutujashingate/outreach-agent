"""Review new or revised content and stop when its revision budget runs out."""

from langgraph.runtime import Runtime

from app.agent.components.reviewer import review_draft
from app.domain.workflow import Outcome, WorkflowState
from app.agent.context import WorkflowContext
from app.agent.nodes.common import allowed_prospects, failure, for_each
from app.agent.nodes.direct import direct_brief


async def review_node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    context, reviews, outcomes = runtime.context, dict(state.reviews), dict(state.outcomes)
    failures = dict(state.failures)
    prospects = [prospect for prospect in allowed_prospects(state) if prospect.id in state.drafts
                 and (prospect.id not in reviews or not reviews[prospect.id].approved)]
    async def assess(prospect):
        return await review_draft(prospect, state.strategies[prospect.id], state.memories.get(prospect.id, []),
                                   state.sender, state.drafts[prospect.id], context.client, brief=direct_brief(state))
    for prospect, result in await for_each(prospects, assess, context, run_id=state.run_id, stage="review"):
        if isinstance(result, Exception):
            outcomes[prospect.id] = failure(state, prospect.id, "review")
            failures[prospect.id] = "Review failed."
        else:
            reviews[prospect.id] = result
            if not result.approved and state.revision_counts.get(prospect.id, 0) >= context.limits.max_revisions:
                outcomes[prospect.id] = Outcome(prospect_id=prospect.id, status="manual_review",
                    reason="Automated review still rejected the draft at the revision limit.",
                    source=f"run:{state.run_id}:review")
    return {"reviews": reviews, "outcomes": outcomes, "failures": failures, "current_step": "reviewed"}
