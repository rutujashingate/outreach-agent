"""Select local or PostgreSQL execution storage without changing graph code."""

from contextlib import asynccontextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

from app.settings import Settings
from app.domain import schemas, workflow, browser, documents
from app.agent import state


def checkpoint_serializer():
    # Explicitly allow only the application's record types. The serializer
    # does not need pickle or arbitrary dynamically imported application types.
    allowed = {(record.__module__, record.__name__) for module in (schemas, workflow, browser, documents, state)
               for record in vars(module).values()
               if isinstance(record, type) and issubclass(record, BaseModel) and record is not BaseModel}
    return JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=sorted(allowed))


@asynccontextmanager
async def open_checkpointer(settings: Settings):
    if settings.checkpoint_backend == "memory":
        yield InMemorySaver(serde=checkpoint_serializer())
    elif settings.checkpoint_backend == "sqlite":
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "checkpoints.sqlite3")) as saver:
            saver.serde = checkpoint_serializer()
            await saver.setup()
            yield saver
    else:
        if not settings.checkpoint_postgres_url:
            raise ValueError("PostgreSQL checkpoints require OUTREACH_CHECKPOINT_POSTGRES_URL.")
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError as error:
            raise ValueError("Install the project's postgres extra to use PostgreSQL checkpoints.") from error
        if settings.supabase_database_url:
            from psycopg import AsyncConnection
            from psycopg.rows import dict_row
            # Session mode keeps this schema selection and LangGraph's prepared
            # statements on the same connection. Transaction pooling cannot.
            async with await AsyncConnection.connect(settings.checkpoint_postgres_url,
                    autocommit=True, prepare_threshold=0, row_factory=dict_row) as connection:
                await connection.execute('SET SESSION search_path TO outreach')
                saver = AsyncPostgresSaver(connection, serde=checkpoint_serializer())
                await saver.setup()
                yield saver
            return
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_postgres_url) as saver:
            saver.serde = checkpoint_serializer()
            await saver.setup()
            yield saver
