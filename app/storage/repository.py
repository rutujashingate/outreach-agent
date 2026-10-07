"""Read and write relationship facts, actions, and outcomes transactionally."""

from hashlib import sha256
import time

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.storage.models import ActionRow, ContactLockRow, ContactRow, EventRow, MemoryRow, RunRow
from app.domain.workflow import MemoryFact, WorkflowState, utc_now
from app.services.limits import LimitExceeded, Limits


def stable_id(*parts: str) -> str:
    return sha256("\x00".join(parts).encode()).hexdigest()


class Repository:
    """One small storage boundary shared by real and local test databases."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def contact(self, email: str) -> dict:
        with Session(self.engine) as session:
            row = session.get(ContactRow, email.casefold())
            if row is None:
                return {"opted_out": False, "active_conversation": False,
                        "last_contact_at": None, "reconnect_at": None}
            return {name: getattr(row, name) for name in (
                "opted_out", "active_conversation", "last_contact_at", "reconnect_at",
            )}

    def update_contact(self, email: str, **changes) -> None:
        allowed = {"opted_out", "active_conversation", "last_contact_at", "reconnect_at"}
        if not changes.keys() <= allowed:
            raise ValueError("Unknown contact property.")
        with Session(self.engine) as session, session.begin():
            row = session.get(ContactRow, email.casefold())
            if row is None:
                row = ContactRow(email=email.casefold())
                session.add(row)
            # An ordinary interaction cannot silently clear an existing opt-out.
            if row.opted_out and changes.get("opted_out") is False:
                raise ValueError("Clearing an opt-out requires a separate consent process.")
            for name, value in changes.items():
                setattr(row, name, value)

    def store_fact(self, fact: MemoryFact) -> None:
        with Session(self.engine) as session, session.begin():
            session.merge(MemoryRow(id=fact.id, email=fact.contact_email.casefold(),
                                    payload=fact.model_dump(mode="json")))
            if fact.kind == "opt_out":
                contact = session.get(ContactRow, fact.contact_email.casefold())
                if contact is None:
                    contact = ContactRow(email=fact.contact_email.casefold())
                    session.add(contact)
                contact.opted_out = True

    def facts(self, email: str) -> list[MemoryFact]:
        with Session(self.engine) as session:
            rows = session.scalars(select(MemoryRow).where(MemoryRow.email == email.casefold()))
            return [MemoryFact.model_validate(row.payload) for row in rows]

    def record_event(self, email: str, source: str, payload: dict) -> bool:
        key = stable_id(email.casefold(), source, str(payload.get("kind", "interaction")))
        try:
            with Session(self.engine) as session, session.begin():
                session.add(EventRow(id=key, email=email.casefold(), source=source,
                                     payload={**payload, "recorded_at": utc_now().isoformat()}))
            return True
        except IntegrityError:
            return False

    def history(self, email: str) -> list[dict]:
        with Session(self.engine) as session:
            rows = session.scalars(select(EventRow).where(EventRow.email == email.casefold()))
            return [{"source": row.source, **row.payload} for row in rows]

    def claim_action(self, key: str, email: str, kind: str) -> bool:
        try:
            with Session(self.engine) as session, session.begin():
                session.add(ActionRow(key=key, email=email.casefold(), kind=kind,
                                      status="pending", payload={}))
            return True
        except IntegrityError:
            return False

    def action(self, key: str) -> dict | None:
        with Session(self.engine) as session:
            row = session.get(ActionRow, key)
            return None if row is None else {"status": row.status, **row.payload}

    def finish_action(self, key: str, status: str, payload: dict) -> None:
        with Session(self.engine) as session, session.begin():
            row = session.get(ActionRow, key)
            if row is None:
                raise ValueError("Action was never claimed.")
            row.status, row.payload = status, payload

    def has_pending_action(self, email: str) -> bool:
        with Session(self.engine) as session:
            return session.scalar(select(ActionRow.key).where(
                ActionRow.email == email.casefold(), ActionRow.status.in_(["pending", "uncertain"]),
            ).limit(1)) is not None

    def claim_contact_action(self, email: str, key: str) -> bool:
        try:
            with Session(self.engine) as session, session.begin():
                session.add(ContactLockRow(email=email.casefold(), action_key=key))
            return True
        except IntegrityError:
            return False

    def release_contact_action(self, email: str, key: str) -> None:
        with Session(self.engine) as session, session.begin():
            row = session.get(ContactLockRow, email.casefold())
            if row is not None and row.action_key == key:
                session.delete(row)

    def save_run(self, state: WorkflowState, status: str, error: str | None = None) -> None:
        with Session(self.engine) as session, session.begin():
            row = session.get(RunRow, state.run_id)
            if row is None:
                row = RunRow(id=state.run_id)
                session.add(row)
            row.payload, row.status, row.error = state.model_dump(mode="json"), status, error

    def run(self, run_id: str) -> dict | None:
        with Session(self.engine) as session:
            row = session.get(RunRow, run_id)
            if row is None:
                return None
            return {"state": row.payload, "status": row.status, "error": row.error,
                    "model_calls": row.model_calls, "search_calls": row.search_calls,
                    "estimated_cost": row.estimated_cost}

    def list_runs(self, limit: int = 100) -> list[dict]:
        """Return bounded summaries of outreach runs for the terminal menu.

        Outreach IDs are 32-character UUIDs. Reply-processing budget records
        use longer IDs and do not belong in the user's outreach-run list.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Run list limit must be between 1 and 100.")
        with Session(self.engine) as session:
            rows = session.scalars(select(RunRow).where(func.length(RunRow.id) == 32)
                                   .order_by(RunRow.id).limit(limit))
            return [{"run_id": row.id, "goal": row.payload["goal"], "status": row.status,
                     "current_step": row.payload["current_step"]} for row in rows]

    def acquire_run(self, run_id: str, lease_seconds: int = 900) -> bool:
        with Session(self.engine) as session, session.begin():
            result = session.execute(update(RunRow).where(
                RunRow.id == run_id, RunRow.lease_until < time.time(),
            ).values(lease_until=time.time() + lease_seconds))
            return result.rowcount == 1

    def release_run(self, run_id: str) -> None:
        with Session(self.engine) as session, session.begin():
            session.execute(update(RunRow).where(RunRow.id == run_id).values(lease_until=0))

    def reserve_call(self, run_id: str, kind: str, limits: Limits) -> None:
        """Count calls across pauses and retries, not just inside one invocation."""
        with Session(self.engine) as session, session.begin():
            if kind == "model":
                result = session.execute(update(RunRow).where(
                    RunRow.id == run_id, RunRow.model_calls < limits.max_model_calls,
                    RunRow.estimated_cost + limits.estimated_cost_per_call <= limits.max_estimated_cost_per_run + 1e-9,
                ).values(model_calls=RunRow.model_calls + 1,
                         estimated_cost=RunRow.estimated_cost + limits.estimated_cost_per_call))
            else:
                result = session.execute(update(RunRow).where(
                    RunRow.id == run_id, RunRow.search_calls < limits.max_search_calls,
                ).values(search_calls=RunRow.search_calls + 1))
            if result.rowcount != 1:
                raise LimitExceeded(f"The {kind} call or estimated cost limit was reached.")
