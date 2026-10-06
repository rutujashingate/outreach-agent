"""Portable SQL tables: the JSON payloads are validated by application records."""

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ContactRow(Base):
    __tablename__ = "contacts"
    email: Mapped[str] = mapped_column(String(254), primary_key=True)
    # Explicit stop/defer decisions remain durable even if old facts expire.
    opted_out: Mapped[bool] = mapped_column(default=False)
    active_conversation: Mapped[bool] = mapped_column(default=False)
    last_contact_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reconnect_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class MemoryRow(Base):
    __tablename__ = "relationship_memory"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class EventRow(Base):
    __tablename__ = "interactions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    source: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)


class ActionRow(Base):
    __tablename__ = "external_actions"
    # A unique action key is claimed before contacting Gmail. An uncertain
    # response is kept for reconciliation, never automatically sent again.
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class RunRow(Base):
    __tablename__ = "outreach_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A persisted lease prevents simultaneous approval/resume calls from two
    # workers. If a worker dies, the lease eventually expires.
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    search_calls: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0)


class ContactLockRow(Base):
    __tablename__ = "contact_action_locks"
    email: Mapped[str] = mapped_column(String(254), primary_key=True)
    action_key: Mapped[str] = mapped_column(String(64))


class TraceRow(Base):
    __tablename__ = "workflow_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[str] = mapped_column(String(40))
    event: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON)
