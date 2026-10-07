"""Search adapters: the researcher never imports a provider's SDK."""

from copy import deepcopy
from typing import Protocol

import httpx
from pydantic import ValidationError

from app.domain.workflow import SearchResult


class ToolError(RuntimeError):
    """An external tool failed without exposing credentials in its message."""


class SearchTool(Protocol):
    async def search(self, query: str) -> list[SearchResult]: ...


class FakeSearchTool:
    def __init__(self, results: list[SearchResult]):
        self.results = deepcopy(results)
        self.queries: list[str] = []

    async def search(self, query: str) -> list[SearchResult]:
        self.queries.append(query)
        return deepcopy(self.results)


class BraveSearchTool:
    """Use Brave's web endpoint; the HTTP client is owned by the caller."""

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
