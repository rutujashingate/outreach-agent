"""Durable jobs and interface records shared by Telegram and the dashboard.

JSON values here are application data, not executable code. Secret-bearing
values are encrypted by the credential store before being written here.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, select, update, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.storage.models import Base, RunRow


def now():
    return datetime.now(timezone.utc).isoformat()


class ValueRow(Base):
    __tablename__ = "service_values"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class RunMeta(Base):
    __tablename__ = "run_metadata"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="outreach")
    origin: Mapped[str] = mapped_column(String(20), default="core")
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    browser_calls: Mapped[int] = mapped_column(Integer, default=0)


class JobRow(Base):
    __tablename__ = "service_jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    request_key: Mapped[str] = mapped_column(String(200), unique=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class InboxRow(Base):
    __tablename__ = "telegram_updates"
    update_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    done: Mapped[bool] = mapped_column(Boolean, default=False)


class OutboxRow(Base):
    __tablename__ = "telegram_outbox"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    retry_at: Mapped[float] = mapped_column(Float, default=0)


def job_dict(row):
    return {name: getattr(row, name) for name in (
        "id", "run_id", "kind", "status", "created_at", "updated_at", "error",
    )}


def set_value(session, key, value):
    """Insert or replace one value in the caller's transaction, in one query."""
    dialect = session.get_bind().dialect.name
    if dialect in {'sqlite', 'postgresql'}:
        if dialect == 'sqlite':
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        statement = insert(ValueRow).values(key=key, value=value)
        session.execute(statement.on_conflict_do_update(index_elements=[ValueRow.key],
                                                        set_={'value': statement.excluded.value}))
    else:
        session.merge(ValueRow(key=key, value=value))


class ControlStore:
    def __init__(self, engine):
        self.engine = engine

    def get(self, key, default=None):
        with Session(self.engine) as session:
            row = session.get(ValueRow, key)
            return row.value if row else default

    def put(self, key, value):
        with Session(self.engine) as session, session.begin():
            set_value(session, key, value)

    def get_many(self, keys):
        """Read related small values together instead of separate cloud trips."""
        with Session(self.engine) as session:
            return dict(session.execute(select(ValueRow.key, ValueRow.value).where(ValueRow.key.in_(keys))).all())

    def put_many(self, values):
        with Session(self.engine) as session, session.begin():
            for key, value in values.items():
                set_value(session, key, value)

    def work_controls(self, run_id):
        """Read cancellation and resumable-stop flags in one fresh query."""
        cancelled = select(RunMeta.run_id).where(RunMeta.run_id == run_id, RunMeta.cancel_requested.is_(True)).exists()
        stopped = select(ValueRow.value).where(ValueRow.key == 'stop:' + run_id).scalar_subquery()
        with Session(self.engine) as session:
            cancel, stop = session.execute(select(cancelled, stopped)).one()
            return bool(cancel), bool((stop or {}).get('requested'))

    def delete(self, key):
        with Session(self.engine) as session, session.begin():
            row = session.get(ValueRow, key)
            if row: session.delete(row)

    def take(self, key):
        """Read and delete a one-use secret atomically (SQLite service model)."""
        from sqlalchemy import delete
        with Session(self.engine) as session, session.begin():
            return session.execute(delete(ValueRow).where(ValueRow.key == key).returning(ValueRow.value)).scalar_one_or_none()

    def metadata(self, run_id):
        with Session(self.engine) as session:
            row = session.get(RunMeta, run_id)
            return None if row is None else {name: getattr(row, name) for name in (
                "kind", "origin", "created_at", "updated_at", "cancel_requested", "browser_calls",
            )}

    def cancellation_requested(self, run_id):
        return bool((self.metadata(run_id) or {}).get("cancel_requested"))

    def cancel(self, run_id):
        with Session(self.engine) as session, session.begin():
            row = session.get(RunMeta, run_id)
            if row: row.cancel_requested, row.updated_at = True, now()
            session.execute(update(JobRow).where(JobRow.run_id == run_id, JobRow.status == "queued").values(status="cancelled", updated_at=now()))

    def reserve_browser(self, run_id, maximum):
        from app.services.limits import LimitExceeded
        with Session(self.engine) as session, session.begin():
            changed = session.execute(update(RunMeta).where(RunMeta.run_id == run_id, RunMeta.browser_calls < maximum).values(browser_calls=RunMeta.browser_calls + 1))
            if changed.rowcount != 1: raise LimitExceeded("Browser page limit reached.")

    def find_job(self, request_key):
        with Session(self.engine) as session:
            row = session.scalar(select(JobRow).where(JobRow.request_key == request_key))
            return job_dict(row) if row else None

    def enqueue(self, kind, run_id, payload, request_key, *, state=None, origin="dashboard", run_kind="outreach"):
        """Create a run and its first job in one transaction, or return a replay."""
        existing = self.find_job(request_key)
        if existing: return existing
        try:
            with Session(self.engine) as session, session.begin():
                if state is not None:
                    session.add(RunRow(id=run_id, payload=state.model_dump(mode="json"), status="queued"))
                    session.add(RunMeta(run_id=run_id, origin=origin, kind=run_kind))
                    if run_kind == 'chat':
                        set_value(session, 'chat:latest:' + payload['session_id'], {'run_id': run_id})
                elif run_id:
                    active = session.scalar(select(JobRow.id).where(JobRow.run_id == run_id, JobRow.status.in_(["queued", "running"])))
                    if active:
                        from app.services.runs import RunConflict
                        raise RunConflict("This run already has queued or running work.")
                row = JobRow(id=uuid4().hex, request_key=request_key, run_id=run_id, kind=kind, payload=payload)
                session.add(row); session.flush()
                return job_dict(row)
        except IntegrityError:
            existing = self.find_job(request_key)
            if existing: return existing
            raise

    def claim(self):
        with Session(self.engine) as session, session.begin():
            paused = select(ValueRow.key).where(ValueRow.key == 'queue', ValueRow.value['paused'].as_boolean().is_(True)).exists()
            row = session.scalar(select(JobRow).where(JobRow.status == "queued", ~paused).order_by(JobRow.created_at, JobRow.id).limit(1))
            if row is None: return None
            result = session.execute(update(JobRow).where(JobRow.id == row.id, JobRow.status == "queued").values(status="running", updated_at=now()))
            if result.rowcount != 1: return None
            return {**job_dict(row), "payload": row.payload}

    def finish_job(self, job_id, status, error=None):
        with Session(self.engine) as session, session.begin():
            session.execute(update(JobRow).where(JobRow.id == job_id).values(status=status, error=error, updated_at=now()))

    def recover(self):
        """After the instance lock is acquired, mark abandoned executions."""
        with Session(self.engine) as session, session.begin():
            rows = list(session.scalars(select(JobRow).where(JobRow.status == "running")))
            for row in rows:
                row.status, row.error, row.updated_at = "interrupted", "Service stopped during execution; inspect and retry.", now()
                if row.run_id:
                    run = session.get(RunRow, row.run_id)
                    if run and run.status in {"running", "queued"}:
                        run.status, run.error, run.lease_until = "failed", row.error, 0
            # A Telegram send may have succeeded before the process stopped.
            session.execute(update(OutboxRow).where(OutboxRow.status == "sending").values(status="uncertain"))

    def jobs(self, limit=50):
        with Session(self.engine) as session:
            return [job_dict(row) for row in session.scalars(select(JobRow).order_by(JobRow.created_at.desc()).limit(limit))]

    def accept_updates(self, updates, owner_id):
        with Session(self.engine) as session, session.begin():
            for item in updates:
                message = item.get("message") or item.get("callback_query", {}).get("message", {})
                actor = item.get("callback_query", {}).get("from") or message.get("from", {})
                if actor.get("id") == owner_id and message.get("chat", {}).get("type") == "private" and message.get("chat", {}).get("id") == owner_id:
                    if session.get(InboxRow, item["update_id"]) is None:
                        session.add(InboxRow(update_id=item["update_id"], payload=item))
            if updates:
                set_value(session, "telegram_offset", {"next": max(item["update_id"] for item in updates) + 1})

    def next_update(self):
        with Session(self.engine) as session:
            row = session.scalar(select(InboxRow).where(InboxRow.done == False).order_by(InboxRow.update_id).limit(1))
            return row.payload if row else None

    def finish_update(self, update_id, conversation):
        with Session(self.engine) as session, session.begin():
            set_value(session, "telegram_conversation", conversation)
            row = session.get(InboxRow, update_id)
            if row: row.done = True

    def notify(self, key, payload):
        try:
            with Session(self.engine) as session, session.begin():
                session.add(OutboxRow(key=key, payload=payload))
        except IntegrityError: pass
