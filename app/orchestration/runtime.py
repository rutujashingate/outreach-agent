"""Open the same workflow services for the terminal and the optional HTTP API."""

from contextlib import AsyncExitStack, asynccontextmanager
import os

import httpx

from app.db.database import create_database
from app.memory.repository import Repository
from app.orchestration.checkpoints import open_checkpointer
from app.orchestration.runs import RunManager
from app.settings import Settings
from app.tools.gmail import GmailClient
from app.tools.search import BraveSearchTool


@asynccontextmanager
async def open_runtime(settings: Settings | None = None):
    """Give one caller a manager, then close every connection when it exits.

    Merely opening the runtime does not call a model, search, or Gmail. Those
    tools are used only when the workflow requests them.
    """
    configured = settings or Settings.from_env()
    async with AsyncExitStack() as stack:
        url = configured.database_url or f"sqlite:///{configured.data_dir / 'relationships.sqlite3'}"
        engine = create_database(url)
        stack.callback(engine.dispose)
        checkpointer = await stack.enter_async_context(open_checkpointer(configured))
        http = await stack.enter_async_context(httpx.AsyncClient(timeout=configured.limits.tool_timeout))
        search_key = os.getenv("BRAVE_SEARCH_API_KEY", "")
        gmail_token = os.getenv("GMAIL_ACCESS_TOKEN", "")
        search = BraveSearchTool(http, search_key, count=configured.limits.max_search_results) if search_key.strip() else None
        gmail = GmailClient(http, gmail_token) if gmail_token.strip() else None
        yield RunManager(Repository(engine), checkpointer, settings=configured, search=search, gmail=gmail)
