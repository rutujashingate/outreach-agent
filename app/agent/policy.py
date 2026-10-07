"""Deterministic rules applied before writing and again before Gmail actions."""

from datetime import datetime, timedelta
from hashlib import sha256
import json

from app.storage.repository import Repository
from app.domain.schemas import EmailDraft
from app.domain.workflow import ContactDecision, Recipient, Sender, utc_now
from app.services.limits import Limits


def message_fingerprint(sender: Sender, recipient: Recipient, draft: EmailDraft) -> str:
    # The recipient, sender, and actual message are bound to approval together.
    content = {"from": {"name": sender.name, "email": sender.email.casefold() if sender.email else None},
               "to": recipient.email.casefold(),
               "subject": draft.subject, "body": draft.body}
    return sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def check_contact(repository: Repository, recipient: Recipient | None, limits: Limits,
                  *, now: datetime | None = None) -> ContactDecision:
    if recipient is None:
        return ContactDecision(allowed=False, reasons=["No recipient address was explicitly supplied."])
    now = now or utc_now()
    contact = repository.contact(recipient.email)
    reasons = []
    if contact["opted_out"]:
        reasons.append("The contact opted out.")
    if contact["active_conversation"]:
        reasons.append("An active conversation should not receive new cold outreach.")
    if contact["reconnect_at"] and datetime.fromisoformat(contact["reconnect_at"]) > now:
        reasons.append("The requested reconnect date has not arrived.")
    if contact["last_contact_at"] and datetime.fromisoformat(contact["last_contact_at"]) > now - timedelta(days=limits.recent_contact_days):
        reasons.append("The contact was reached too recently.")
    if repository.has_pending_action(recipient.email):
        reasons.append("A previous external action is pending or needs reconciliation.")
    return ContactDecision(allowed=not reasons, reasons=reasons or ["Contact rules allow outreach."])
