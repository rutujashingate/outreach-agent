"""Workflow routes are explicit code decisions, never hidden in prompts."""

from app.models.workflow import WorkflowState


def after_qualification(state: WorkflowState) -> str:
    return "memory_check" if state.qualified_prospects else "finish"


def after_contact_policy(state: WorkflowState) -> str:
    return "outreach" if any(decision.allowed for decision in state.contact_decisions.values()) else "finish"


def after_review(state: WorkflowState) -> str:
    for prospect in state.qualified_prospects:
        review = state.reviews.get(prospect.id)
        if review is not None and not review.approved and prospect.id not in state.outcomes:
            return "writing"
    return "end"


def after_prepare_approval(state: WorkflowState) -> str:
    return "human_approval" if state.approval_requests else "external_actions"


def after_human_approval(state: WorkflowState) -> str:
    # Edited drafts have no review. Other approvals remain bound to their
    # original content while only edited prospects return to the review path.
    if any(prospect.id in state.drafts and prospect.id not in state.reviews
           and prospect.id not in state.outcomes for prospect in state.qualified_prospects):
        return "outreach"
    return "external_actions"
