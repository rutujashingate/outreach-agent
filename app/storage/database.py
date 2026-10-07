"""Use SQLite locally and the same tables with PostgreSQL when configured."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from alembic import command
from alembic.config import Config
import migrations


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
    config = Config()
    config.set_main_option("script_location", str(Path(migrations.__file__).parent))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    return engine
