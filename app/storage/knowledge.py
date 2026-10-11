"""Source versions and their searchable passages, separate from workflow state."""
import json

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.storage.models import Base
from app.storage.control import now


class Vector384(UserDefinedType):
    """Use pgvector on Postgres and ordinary JSON for small offline test stores."""
    cache_ok = True

    def get_col_spec(self, **kw): return 'extensions.vector(384)'

    def bind_processor(self, dialect):
        return lambda value: None if value is None else json.dumps(value, allow_nan=False)

    def result_processor(self, dialect, coltype):
        return lambda value: json.loads(value) if isinstance(value, str) else value


class KnowledgeSource(Base):
    __tablename__ = 'knowledge_sources'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    ref: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(300))
    purpose: Mapped[str] = mapped_column(String(20), default='background')
    retrieved_at: Mapped[str] = mapped_column(String(40))
    content_hash: Mapped[str] = mapped_column(String(64))
    pages: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    active_version: Mapped[str | None] = mapped_column(String(150), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)


class KnowledgeChunk(Base):
    __tablename__ = 'knowledge_chunks'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey('knowledge_sources.id'), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer)
    ref: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    embedding_version: Mapped[str] = mapped_column(String(150))
    revision: Mapped[str] = mapped_column(String(150))
    evidence: Mapped[dict] = mapped_column(JSON)
    embedding: Mapped[list | None] = mapped_column(Vector384().with_variant(JSON(), 'sqlite'), nullable=True)
