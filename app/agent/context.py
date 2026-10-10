"""Per-invocation services stay outside checkpointed workflow records."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import time

from app.storage.repository import Repository
from app.llm.client import ModelClient, ModelClientError, ModelProviderError, ModelResponseError
from app.domain.workflow import MemoryFact, SearchResult
from app.storage.events import trace
from app.services.limits import Limits
from app.connectors.gmail.client import GmailTool
from app.connectors.search import SearchTool, ToolError
from app.services.cancellation import check_cancelled


class ManagedModelClient:
    """Reserve calls and estimated cost, bound duration, and record outcomes."""

    def __init__(self, client: ModelClient, repository: Repository, run_id: str, limits: Limits):
        self.client, self.repository, self.run_id, self.limits = client, repository, run_id, limits
        self.semaphore = asyncio.Semaphore(limits.concurrency)
        self.consecutive_failures = 0

    async def generate_structured(self, *, instructions, input_text, response_model):
        async with self.semaphore:
            if self.consecutive_failures >= 3:
                raise ModelClientError("Model requests were stopped after repeated failures.")
            # Transport/server failures get one retry. Configuration failures,
            # rate limits, invalid output, and refusals need owner action or time.
            for attempt in range(2):
                check_cancelled(self.repository, self.run_id)
                self.repository.reserve_call(self.run_id, "model", self.limits)
                started = time.monotonic()
                trace(self.repository, self.run_id, "model_start", task=response_model.__name__, attempt=attempt)
                try:
                    async with asyncio.timeout(self.limits.model_timeout):
                        result = await self.client.generate_structured(
                            instructions=instructions, input_text=input_text, response_model=response_model,
                        )
                    self.consecutive_failures = 0
                    trace(self.repository, self.run_id, "model_end", task=response_model.__name__,
                          seconds=time.monotonic() - started, usage=getattr(self.client, "last_usage", {}),
                          model=getattr(self.client, "model_name", None))
                    return result
                except (ModelClientError, TimeoutError) as error:
                    self.consecutive_failures += 1
                    details = ({"provider": error.provider, "reason": error.reason,
                                "http_status": error.status_code, "message": error.public_message}
                               if isinstance(error, ModelProviderError) else {})
                    trace(self.repository, self.run_id, "model_failure", task=response_model.__name__,
                          error_type=type(error).__name__, seconds=time.monotonic() - started, **details)
                    if (attempt or isinstance(error, (ModelResponseError, TimeoutError))
                            or isinstance(error, ModelProviderError) and not error.retryable):
                        if isinstance(error, TimeoutError):
                            raise ModelClientError("Model request exceeded its time limit.") from error
                        raise
                    await asyncio.sleep(0.05)
            raise ModelClientError("Model requests could not complete.")


class ManagedSearchTool:
    def __init__(self, tool: SearchTool, repository: Repository, run_id: str, limits: Limits):
        self.tool, self.repository, self.run_id, self.limits = tool, repository, run_id, limits

    async def search(self, query: str) -> list[SearchResult]:
        for attempt in range(2):
            check_cancelled(self.repository, self.run_id)
            self.repository.reserve_call(self.run_id, "search", self.limits)
            started = time.monotonic()
            trace(self.repository, self.run_id, "search_start", attempt=attempt)
            try:
                async with asyncio.timeout(self.limits.search_timeout):
                    results = await self.tool.search(query)
                trace(self.repository, self.run_id, "search_end", count=len(results), seconds=time.monotonic() - started)
                return results[:self.limits.max_search_results]
            except (ToolError, TimeoutError) as error:
                trace(self.repository, self.run_id, "search_failure", error_type=type(error).__name__)
                if attempt:
                    raise ToolError("Search exceeded its retry or time limit.") from error
                await asyncio.sleep(0.05)
        return []


@dataclass(frozen=True)
class WorkflowContext:
    client: ModelClient
    repository: Repository
    limits: Limits
    search: SearchTool | None = None
    gmail: GmailTool | None = None
    browser: object | None = None
    read_gmail: bool = False
    sending_enabled: bool = False
    memory_retriever: Callable[[Repository, str, str, Limits], Awaitable[list[MemoryFact]]] | None = None
