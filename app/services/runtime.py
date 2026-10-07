"""Open and close the agent, database, and connector dependencies together."""
from contextlib import AsyncExitStack, asynccontextmanager
import os
import httpx

from app.storage.database import create_database
from app.storage.repository import Repository
from app.storage.control import ControlStore
from app.storage.checkpoints import open_checkpointer
from app.services.runs import RunManager
from app.settings import Settings
from app.connectors.gmail.oauth import GmailAccount, ConnectedGmail
from app.connectors.search import BraveSearchTool
from app.connectors.browser.client import BrowserClient


@asynccontextmanager
async def open_runtime(settings: Settings | None = None):
    configured = settings or Settings.from_env()
    async with AsyncExitStack() as stack:
        url = configured.database_url or f"sqlite:///{configured.data_dir / 'relationships.sqlite3'}"
        engine = create_database(url); stack.callback(engine.dispose)
        checkpointer = await stack.enter_async_context(open_checkpointer(configured))
        repository = Repository(engine)
        if configured.demo:
            from app.demo import build_demo_manager
            yield build_demo_manager(repository=repository, checkpointer=checkpointer, settings=configured)
            return
        http = await stack.enter_async_context(httpx.AsyncClient(timeout=configured.limits.tool_timeout))
        search_key = os.getenv('BRAVE_SEARCH_API_KEY', '')
        search = BraveSearchTool(http, search_key, count=configured.limits.max_search_results) if search_key.strip() else None
        account = GmailAccount(http, ControlStore(engine), configured)
        browser = BrowserClient() if configured.browser_enabled else None
        if browser and not await browser.available(): browser = None
        yield RunManager(repository, checkpointer, settings=configured, search=search,
                         gmail=ConnectedGmail(account), browser=browser)
