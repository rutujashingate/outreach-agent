"""Document text and the location of its private original file."""
from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, Session
from app.storage.models import Base
from app.storage.control import now


class DocumentRow(Base):
    __tablename__ = 'uploaded_documents'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(180))
    suffix: Mapped[str] = mapped_column(String(10))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    storage_backend: Mapped[str] = mapped_column(String(20), default='local', server_default='local')
    object_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    extracted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


def document_record(engine, document_id):
    with Session(engine) as session:
        row = session.get(DocumentRow, document_id)
        if row is None: return None
        return {name: getattr(row, name) for name in (
            'id', 'filename', 'suffix', 'sha256', 'size', 'status', 'created_at', 'extracted_at', 'content', 'error',
            'storage_backend', 'object_key')}
