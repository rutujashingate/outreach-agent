"""Store concise execution events without recording credentials or full prompts."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.storage.models import TraceRow
from app.storage.repository import Repository
from app.domain.workflow import utc_now


def trace(repository: Repository, run_id: str, event: str, **details) -> None:
    with Session(repository.engine) as session, session.begin():
        session.add(TraceRow(id=uuid4().hex, run_id=run_id, timestamp=utc_now().isoformat(),
                             event=event, payload=details))


def events(repository: Repository, run_id: str) -> list[dict]:
    with Session(repository.engine) as session:
        rows = session.scalars(select(TraceRow).where(TraceRow.run_id == run_id).order_by(TraceRow.timestamp))
        return [{"timestamp": row.timestamp, "event": row.event, **row.payload} for row in rows]
