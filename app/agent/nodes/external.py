"""Execute approved Gmail actions once, and preserve uncertain results."""

import asyncio

from langgraph.runtime import Runtime

from app.storage.repository import stable_id
from app.domain.workflow import Outcome, WorkflowState, utc_now
from app.storage.events import trace
from app.agent.context import WorkflowContext
from app.agent.policy import check_contact, message_fingerprint


async def external_node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    context, outcomes = runtime.context, dict(state.outcomes)
    for prospect in state.qualified_prospects:
        from app.services.cancellation import check_cancelled
        check_cancelled(context.repository, state.run_id)
        prospect_id = prospect.id
        if prospect_id in outcomes:
            continue
        decision, review = state.human_decisions.get(prospect_id), state.reviews.get(prospect_id)
        recipient, draft = state.recipients.get(prospect_id), state.drafts.get(prospect_id)
        if recipient is None or draft is None or review is None or not review.approved or decision is None:
            continue
        fingerprint = message_fingerprint(state.sender, recipient, draft, state.gmail_action, state.gmail_account_id)
        if decision.action != "approve" or decision.version != state.draft_versions.get(prospect_id) or decision.fingerprint != fingerprint:
            outcomes[prospect_id] = Outcome(prospect_id=prospect_id, status="blocked",
                reason="There is no approval for the current recipient and message.", source=f"run:{state.run_id}:approval")
            continue
        source = f"run:{state.run_id}:approval"
        if state.gmail_action == "none":
            outcomes[prospect_id] = Outcome(prospect_id=prospect_id, status="approved", source=source)
            continue
        if hasattr(context.gmail, "ensure_account"):
            await context.gmail.ensure_account(state.sender.email, state.gmail_account_id)
        key = stable_id("gmail:" + state.gmail_action, fingerprint)
        existing = context.repository.action(key)
        if existing is not None:
            # Replaying a completed node from the SAME run returns its recorded
            # result. A different run cannot turn an old send into a new one.
            if existing["status"] == "done" and existing.get("run_id") == state.run_id:
                outcomes[prospect_id] = Outcome.model_validate(existing["outcome"])
            else:
                outcomes[prospect_id] = Outcome(prospect_id=prospect_id, status="blocked",
                    reason="Duplicate or uncertain external action; inspect action history.", source=source)
            continue
        policy = check_contact(context.repository, recipient, context.limits)
        if not policy.allowed or context.gmail is None or state.sender.email is None:
            outcomes[prospect_id] = Outcome(prospect_id=prospect_id, status="blocked",
                reason=" ".join(policy.reasons) if not policy.allowed else "Gmail and a sender address are required.", source=source)
            continue
        if state.gmail_action == "send" and not context.sending_enabled:
            outcomes[prospect_id] = Outcome(prospect_id=prospect_id, status="blocked",
                reason="Email sending has not been explicitly enabled.", source=source)
            continue
        if not context.repository.claim_contact_action(recipient.email, key):
            outcomes[prospect_id] = Outcome(prospect_id=prospect_id, status="blocked",
                reason="Another action for this contact is in progress or uncertain.", source=source)
            continue
        # Recheck under the contact lock so two workers with different messages
        # cannot both act on an old 'not recently contacted' decision.
        policy = check_contact(context.repository, recipient, context.limits)
        if not policy.allowed:
            context.repository.release_contact_action(recipient.email, key)
            outcomes[prospect_id] = Outcome(prospect_id=prospect_id, status="blocked",
                reason=" ".join(policy.reasons), source=source)
            continue
        if not context.repository.claim_action(key, recipient.email, state.gmail_action):
            context.repository.release_contact_action(recipient.email, key)
            outcomes[prospect_id] = Outcome(prospect_id=prospect_id, status="blocked",
                reason="Another execution already claimed this external action.", source=source)
            continue
        trace(context.repository, state.run_id, "external_action_start", action=state.gmail_action,
              prospect_id=prospect_id, action_key=key)
        try:
            async with asyncio.timeout(context.limits.tool_timeout):
                result = (await context.gmail.create_draft(state.sender, recipient, draft)
                          if state.gmail_action == "draft" else await context.gmail.send(state.sender, recipient, draft))
            message = result.get("message", result)
            outcome = Outcome(prospect_id=prospect_id,
                status="drafted" if state.gmail_action == "draft" else "sent",
                source=f"gmail:{result['id']}", external_id=result["id"], thread_id=message.get("threadId"))
            context.repository.finish_action(key, "done", {"run_id": state.run_id, "outcome": outcome.model_dump()})
            if state.gmail_action == "send":
                context.repository.update_contact(recipient.email, last_contact_at=utc_now().isoformat())
            context.repository.release_contact_action(recipient.email, key)
            outcomes[prospect_id] = outcome
            trace(context.repository, state.run_id, "external_action_end", action=state.gmail_action,
                  prospect_id=prospect_id, external_id=result["id"])
        except Exception as error:
            # A timeout or lost response can occur after Gmail accepted the
            # message. Preserve uncertainty and never retry this POST blindly.
            context.repository.finish_action(key, "uncertain", {"run_id": state.run_id})
            outcomes[prospect_id] = Outcome(prospect_id=prospect_id, status="uncertain",
                reason="The Gmail action needs manual reconciliation before another attempt.", source=source)
            trace(context.repository, state.run_id, "external_action_uncertain", action_key=key,
                  error_type=type(error).__name__)
    return {"outcomes": outcomes}


async def finish_node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    for prospect_id, outcome in state.outcomes.items():
        recipient = state.recipients.get(prospect_id)
        if recipient is not None:
            runtime.context.repository.record_event(recipient.email,
                f"run:{state.run_id}:{prospect_id}:{outcome.status}",
                {"kind": outcome.status, "outcome": outcome.model_dump(mode="json")})
    step = "no_matches" if not state.qualified_prospects and not state.failures else "completed"
    return {"current_step": step, "approval_requests": []}
