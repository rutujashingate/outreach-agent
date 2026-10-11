"""Persist page usage and evidence so graph retries reuse successful reads."""
import asyncio
from hashlib import sha256

from app.connectors.search import ToolError
from app.domain.browser import PageEvidence
from app.storage.control import ControlStore
from app.storage.events import atrace as trace
from app.services.cancellation import acheck_cancelled as check_cancelled


class ManagedBrowser:
    def __init__(self, tool, repository, run_id, limits):
        self.tool, self.repository, self.run_id, self.limits = tool, repository, run_id, limits
        self.store = ControlStore(repository.engine)

    async def read(self, url):
        await check_cancelled(self.repository, self.run_id)
        key = 'page:' + self.run_id + ':' + sha256(url.encode()).hexdigest()
        cached = await asyncio.to_thread(self.store.get, key)
        if cached:
            page = PageEvidence.model_validate(cached)
            from app.services.knowledge import capture_page
            await asyncio.to_thread(capture_page, self.repository.engine, page)
            return page
        await asyncio.to_thread(self.store.reserve_browser, self.run_id, self.limits.max_browser_pages)
        await trace(self.repository, self.run_id, 'browser_start', url=url)
        try:
            async with asyncio.timeout(self.limits.browser_timeout):
                page = await self.tool.read(url, timeout=self.limits.browser_timeout, max_chars=self.limits.max_page_chars)
        except (ToolError, TimeoutError):
            page = PageEvidence(url=url, error='Page unavailable or blocked by browser limits.')
        await asyncio.to_thread(self.store.put, key, page.model_dump(mode='json'))
        from app.services.knowledge import capture_page
        await asyncio.to_thread(capture_page, self.repository.engine, page)
        await trace(self.repository, self.run_id, 'browser_end', url=page.url, readable=page.error is None)
        return page
