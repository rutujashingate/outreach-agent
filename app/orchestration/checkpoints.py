"""Select local or PostgreSQL execution storage without changing graph code."""

from contextlib import asynccontextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

from app.settings import Settings
from app.models import schemas, workflow
from app.orchestration import state


def checkpoint_serializer():
    # Explicitly allow only the application's record types. The serializer
    # does not need pickle or arbitrary dynamically imported application types.
    allowed = {(record.__module__, record.__name__) for module in (schemas, workflow, state)
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
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_postgres_url) as saver:
            saver.serde = checkpoint_serializer()
            await saver.setup()
            yield saver
