"""Prepare a visible decision record and pause without external side effects."""

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.domain.workflow import ApprovalRequest, ApprovalSubmission, Outcome, WorkflowState
from app.agent.context import WorkflowContext
from app.agent.nodes.common import allowed_prospects
from app.agent.policy import message_fingerprint


async def prepare_approval(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    requests = []
    for prospect in allowed_prospects(state):
        review = state.reviews.get(prospect.id)
        if review is None or not review.approved:
            continue
        fingerprint = message_fingerprint(state.sender, state.recipients[prospect.id], state.drafts[prospect.id], state.gmail_action, state.gmail_account_id)
        decision = state.human_decisions.get(prospect.id)
        if decision is not None and decision.action == "approve" and decision.fingerprint == fingerprint:
            continue
        requests.append(ApprovalRequest(prospect=prospect, recipient=state.recipients[prospect.id],
            version=state.draft_versions[prospect.id], fingerprint=fingerprint,
            research_summary=prospect.signals + prospect.sources,
            memories=state.memories.get(prospect.id, []), strategy=state.strategies[prospect.id].model_dump(),
            draft=state.drafts[prospect.id]))
    return {"approval_requests": requests,
            "current_step": "awaiting_approval" if requests else "reviewed"}


async def human_approval(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    # LangGraph starts this function again on resume. No writes or model calls
    # occur before interrupt, so replay cannot duplicate external actions.
    submitted = interrupt({"run_id": state.run_id,
                           "requests": [request.model_dump(mode="json") for request in state.approval_requests]})
    submission = ApprovalSubmission.model_validate(submitted)
    validate_decisions(state, submission)
    decisions, drafts, reviews, counts, versions, outcomes = map(dict, (
        state.human_decisions, state.drafts, state.reviews, state.revision_counts, state.draft_versions, state.outcomes,
    ))
    for decision in submission.decisions:
        prospect_id = decision.prospect_id
        if decision.action == "edit":
            decisions.pop(prospect_id, None)
            if counts.get(prospect_id, 0) >= runtime.context.limits.max_revisions:
                outcomes[prospect_id] = Outcome(prospect_id=prospect_id, status="manual_review",
                    reason="Edit would exceed the revision limit.", source=f"run:{state.run_id}:approval")
                continue
            drafts[prospect_id] = decision.edited_draft
            reviews.pop(prospect_id, None)
            counts[prospect_id] = counts.get(prospect_id, 0) + 1
            versions[prospect_id] += 1
        else:
            decisions[prospect_id] = decision
            if decision.action == "reject":
                outcomes[prospect_id] = Outcome(prospect_id=prospect_id, status="rejected",
                    reason="The user rejected this draft.", source=f"run:{state.run_id}:approval")
    return {"human_decisions": decisions, "drafts": drafts, "reviews": reviews,
            "revision_counts": counts, "draft_versions": versions, "outcomes": outcomes,
            "approval_requests": []}


def validate_decisions(state: WorkflowState, submission: ApprovalSubmission) -> None:
    expected = {request.prospect.id: request for request in state.approval_requests}
    ids = [decision.prospect_id for decision in submission.decisions]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise ValueError("Supply exactly one decision for each pending prospect.")
    for decision in submission.decisions:
        request = expected[decision.prospect_id]
        if decision.version != request.version or decision.fingerprint != request.fingerprint:
            raise ValueError("Decision does not match the current draft version and content.")
