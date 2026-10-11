"""Use SQLite locally and the same tables with PostgreSQL when configured."""

from pathlib import Path
from threading import RLock
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

from alembic import command
from alembic.config import Config
import migrations


def create_database(url: str = "sqlite:///:memory:", *, private_schema: bool = False) -> Engine:
    options: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if url.endswith(":memory:"):
            # Each thread gets a separate checked-out connection to the same
            # temporary database. StaticPool can hand out a connection that
            # another session is still using, mixing their transactions.
            url = f'sqlite:///file:outreach-{uuid4().hex}?mode=memory&cache=shared&uri=true'
            options.update(poolclass=QueuePool, pool_size=5, max_overflow=0)
        elif ":///" in url:
            Path(url.split(":///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
    if url.startswith('postgresql'):
        options.update(pool_size=3, max_overflow=0, pool_timeout=10)
    engine = create_engine(url, **options)
    if url.startswith('sqlite:///file:outreach-') and 'mode=memory' in url:
        # Shared in-memory SQLite has table locks. Short database transactions
        # take turns; network/model calls still run concurrently outside them.
        connection_lock = RLock()
        event.listen(engine, 'checkout', lambda *_: connection_lock.acquire())
        event.listen(engine, 'checkin', lambda *_: connection_lock.release())
    if private_schema:
        if engine.dialect.name != 'postgresql':
            engine.dispose()
            raise ValueError('Private Supabase storage requires PostgreSQL.')
        from app.storage.postgres import prepare_connection
        event.listen(engine, 'connect', prepare_connection, insert=True)
    # This establishes the initial schema. Later table changes need explicit
    # migrations rather than silently relying on create_all to alter a table.
    config = Config()
    config.set_main_option("script_location", str(Path(migrations.__file__).parent))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        if private_schema:
            from app.storage.postgres import protect_tables
            protect_tables(engine)
    except Exception:
        engine.dispose()
        raise
    return engine
