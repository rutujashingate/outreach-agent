"""Use SQLite locally and the same tables with PostgreSQL when configured."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.storage.models import Base


def create_database(url: str = "sqlite:///:memory:") -> Engine:
    options: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if url.endswith(":memory:"):
            options["poolclass"] = StaticPool
        elif ":///" in url:
            Path(url.split(":///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **options)
    # This establishes the initial schema. Later table changes need explicit
    # migrations rather than silently relying on create_all to alter a table.
    Base.metadata.create_all(engine)
    return engine
