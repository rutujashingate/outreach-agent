"""Write initial drafts or make a bounded revision using review feedback."""

from langgraph.runtime import Runtime

from app.agent.components.writer import write_draft
from app.domain.workflow import Outcome, WorkflowState
from app.agent.context import WorkflowContext
from app.agent.nodes.common import allowed_prospects, failure, for_each


async def writing_node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    context = runtime.context
    failures = dict(state.failures)
    drafts, counts, versions, outcomes = map(dict, (state.drafts, state.revision_counts, state.draft_versions, state.outcomes))
    candidates = []
    for prospect in allowed_prospects(state):
        review = state.reviews.get(prospect.id)
        # An edited draft with its old review removed is ready for review, not
        # another unsolicited rewrite. Approved drafts are left intact.
        if prospect.id in drafts and (review is None or review.approved):
            continue
        if prospect.id in drafts and counts.get(prospect.id, 0) >= context.limits.max_revisions:
            outcomes[prospect.id] = Outcome(prospect_id=prospect.id, status="manual_review",
                reason="Revision limit reached.", source=f"run:{state.run_id}:review")
            continue
        candidates.append(prospect)
    async def write(prospect):
        return await write_draft(prospect, state.strategies[prospect.id], state.memories.get(prospect.id, []),
            state.sender, context.client, previous=drafts.get(prospect.id),
            feedback=state.reviews[prospect.id].issues if prospect.id in state.reviews else [])
    for prospect, result in await for_each(candidates, write, context, run_id=state.run_id, stage="writing"):
        if isinstance(result, Exception):
            outcomes[prospect.id] = failure(state, prospect.id, "writing")
            failures[prospect.id] = "Writing failed."
        else:
            if prospect.id in drafts:
                counts[prospect.id] = counts.get(prospect.id, 0) + 1
            drafts[prospect.id] = result
            versions[prospect.id] = versions.get(prospect.id, 0) + 1
    return {"drafts": drafts, "revision_counts": counts, "draft_versions": versions,
            "outcomes": outcomes, "failures": failures, "current_step": "written"}
