"""Inspect contact history and process user-supplied incoming replies."""

from fastapi import APIRouter

from app.web.routes.runs import Manager
from app.domain.workflow import ContactUpdate, EmailText, MemoryFact, ReplyRequest, ReplyState
from app.storage.repository import stable_id
from app.agent.components.memory.advanced import consolidate, possible_conflicts
from app.agent.replies import process_reply

router = APIRouter(tags=["relationship memory"])


@router.post("/replies", response_model=ReplyState)
async def receive_reply(request: ReplyRequest, manager: Manager):
    return await process_reply(manager, request)


@router.get("/contacts/{email}")
async def contact_history(email: EmailText, manager: Manager):
    facts = manager.repository.facts(email)
    return {"contact": manager.repository.contact(email), "history": manager.repository.history(email),
            "facts": [fact.model_dump(mode="json") for fact in facts],
            "consolidated_facts": [group.model_dump(mode="json") for group in consolidate(facts)],
            "possible_conflicts": possible_conflicts(facts)}


@router.put("/contacts/{email}/policy")
async def update_contact(email: EmailText, request: ContactUpdate, manager: Manager):
    changes = {}
    if request.active_conversation is not None:
        changes["active_conversation"] = request.active_conversation
    if request.reconnect_at is not None:
        changes["reconnect_at"] = request.reconnect_at.isoformat()
    if not changes:
        raise ValueError("Supply an active-conversation or reconnect-date change.")
    manager.repository.update_contact(email, **changes)
    manager.repository.store_fact(MemoryFact(id=stable_id(email.casefold(), request.source, "manual_policy"),
        contact_email=email, kind="relationship", value=request.evidence_quote,
        source=request.source, evidence_quote=request.evidence_quote))
    return manager.repository.contact(email)
