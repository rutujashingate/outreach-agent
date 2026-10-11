"""Search adapters: the researcher never imports a provider's SDK."""

from copy import deepcopy
import asyncio
from typing import Protocol

import httpx
from pydantic import ValidationError

from app.domain.workflow import SearchResult


class ToolError(RuntimeError):
    """An external tool failed without exposing credentials in its message."""


class SearchTool(Protocol):
    async def search(self, query: str) -> list[SearchResult]: ...


class PublicSearchTool:
    """Keyless public search; failures are reported rather than invented."""
    provider = 'duckduckgo'

    def __init__(self, *, count=10, timeout=10, factory=None):
        from ddgs import DDGS
        self.factory = factory or DDGS
        self.count, self.timeout = min(max(count, 1), 20), timeout

    async def search(self, query):
        from app.connectors.browser.network import parse_public_url
        if not isinstance(query, str) or not query.strip():
            raise ValueError('Search query must be nonblank text.')
        try:
            # The library is synchronous; keep network work off the event loop.
            def retrieve():
                return self.factory(timeout=self.timeout).text(query, backend='duckduckgo', max_results=self.count)
            rows = await asyncio.to_thread(retrieve)
            results, seen = [], set()
            for item in rows[:self.count]:
                try:
                    parse_public_url(item['href'])
                    result = SearchResult(title=item['title'][:2000], url=item['href'], description=item.get('body', '')[:10000])
                    if result.url not in seen:
                        results.append(result); seen.add(result.url)
                except (ToolError, ValueError, KeyError, TypeError):
                    continue
            if not results:
                raise ToolError('Public search returned no usable results. Try a narrower query or supply a website.')
            return results
        except ToolError:
            raise
        except Exception as error:
            raise ToolError('Public search is temporarily unavailable or rate-limited. Try later or supply a website.') from error


class FakeSearchTool:
    def __init__(self, results: list[SearchResult]):
        self.results = deepcopy(results)
        self.queries: list[str] = []

    async def search(self, query: str) -> list[SearchResult]:
        self.queries.append(query)
        return deepcopy(self.results)


class BraveSearchTool:
    """Use Brave's web endpoint; the HTTP client is owned by the caller."""
    provider = 'brave'

    def __init__(self, client: httpx.AsyncClient, api_key: str, *, count: int = 10):
        if not api_key.strip():
            raise ValueError("BRAVE_SEARCH_API_KEY is required for search.")
        self.client, self.api_key, self.count = client, api_key, min(max(count, 1), 20)

    async def search(self, query: str) -> list[SearchResult]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Search query must be nonblank text.")
        try:
            response = await self.client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": self.count},
                headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
            return [SearchResult(title=item["title"], url=item["url"],
                                 description=item.get("description", ""))
                    for item in payload.get("web", {}).get("results", [])[:self.count]]
        except (httpx.HTTPError, ValueError, KeyError, TypeError, ValidationError) as error:
            raise ToolError("Search could not return usable results.") from error
