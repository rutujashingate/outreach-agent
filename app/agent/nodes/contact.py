"""Apply deterministic rules, including duplicate contacts within this run."""

from langgraph.runtime import Runtime

from app.domain.workflow import ContactDecision, Outcome, WorkflowState
from app.agent.context import WorkflowContext
from app.agent.policy import check_contact


async def contact_node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    context, decisions, seen = runtime.context, {}, set()
    outcomes = dict(state.outcomes)
    for prospect in state.qualified_prospects:
        recipient = state.recipients.get(prospect.id)
        decision = check_contact(context.repository, recipient, context.limits)
        if recipient is not None and recipient.email.casefold() in seen:
            decision = ContactDecision(allowed=False, reasons=["Duplicate recipient in the same run."])
        if recipient is not None:
            seen.add(recipient.email.casefold())
        decisions[prospect.id] = decision
        if not decision.allowed:
            outcomes[prospect.id] = Outcome(prospect_id=prospect.id, status="blocked",
                reason=" ".join(decision.reasons), source=f"run:{state.run_id}:contact_policy")
    return {"contact_decisions": decisions, "outcomes": outcomes, "current_step": "contact_checked"}
