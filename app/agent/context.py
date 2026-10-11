"""Per-invocation services stay outside checkpointed workflow records."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from contextvars import ContextVar
import time
import json

from app.storage.repository import Repository
from app.storage.repository import stable_id
from app.storage.control import ControlStore
from app.llm.client import generate_structured
from app.llm.client import ModelClient, ModelClientError, ModelProviderError, ModelResponseError
from app.domain.workflow import MemoryFact, SearchResult
from app.domain.schemas import EmailDraft
from app.agent.components.writer import validate_email_content
from app.storage.events import atrace as trace
from app.services.limits import Limits
from app.connectors.gmail.client import GmailTool
from app.connectors.search import SearchTool, ToolError
from app.services.cancellation import acheck_cancelled as check_cancelled


# A new review/revision is new work even when the resulting email is identical.
# Context-local scope also keeps concurrently processed prospects independent.
model_cache_scope = ContextVar('model_cache_scope', default='')


class ManagedModelClient:
    """Reserve calls and estimated cost, bound duration, and record outcomes."""

    def __init__(self, client: ModelClient, repository: Repository, run_id: str, limits: Limits):
        self.client, self.repository, self.run_id, self.limits = client, repository, run_id, limits
        self.semaphore = asyncio.Semaphore(limits.concurrency)
        self.consecutive_failures = 0
        self.store = ControlStore(repository.engine)

    @property
    def supports_task_routing(self):
        return getattr(self.client, 'supports_task_routing', False)

    async def generate_structured(self, *, instructions, input_text, response_model):
        async with self.semaphore:
            await check_cancelled(self.repository, self.run_id)
            key = 'model:result:' + self.run_id + ':' + stable_id(
                model_cache_scope.get(), response_model.__name__, instructions, input_text,
                json.dumps(response_model.model_json_schema(), sort_keys=True))
            saved = await asyncio.to_thread(self.store.get, key)
            if saved is not None:
                result = response_model.model_validate(saved)
                try:
                    if isinstance(result, EmailDraft): validate_email_content(result)
                except ModelResponseError:
                    # An earlier incomplete body must not trap explicit retry
                    # in a permanently reused bad result. Counters stay spent.
                    await asyncio.to_thread(self.store.delete, key)
                else:
                    await trace(self.repository, self.run_id, 'model_cache_hit', task=response_model.__name__)
                    return result
            if self.consecutive_failures >= 3:
                raise ModelClientError("Model requests were stopped after repeated failures.")
            # Transport/server failures get one retry. Configuration failures,
            # rate limits, invalid output, and refusals need owner action or time.
            for attempt in range(2):
                await check_cancelled(self.repository, self.run_id)
                await asyncio.to_thread(self.repository.reserve_call, self.run_id, "model", self.limits)
                started = time.monotonic()
                route = self.client.route_info(response_model) if hasattr(self.client, 'route_info') else {}
                await trace(self.repository, self.run_id, "model_start", task=response_model.__name__, attempt=attempt, **route)
                try:
                    async with asyncio.timeout(self.limits.model_timeout):
                        result = await generate_structured(client=self.client,
                            instructions=instructions, input_text=input_text, response_model=response_model,
                        )
                    if isinstance(result, EmailDraft): validate_email_content(result)
                    # A node may process several prospects before checkpointing.
                    # Retain each validated answer so a later stop does not
                    # repeat the already completed, paid calls in that node.
                    await asyncio.to_thread(self.store.put, key, result.model_dump(mode='json'))
                    self.consecutive_failures = 0
                    await trace(self.repository, self.run_id, "model_end", task=response_model.__name__,
                          seconds=time.monotonic() - started, usage=getattr(self.client, "last_usage", {}),
                          model=getattr(self.client, "model_name", None), role=route.get('role'))
                    return result
                except (ModelClientError, TimeoutError) as error:
                    self.consecutive_failures += 1
                    details = ({"provider": error.provider, "reason": error.reason,
                                "http_status": error.status_code, "message": error.public_message}
                               if isinstance(error, ModelProviderError) else {})
                    await trace(self.repository, self.run_id, "model_failure", task=response_model.__name__,
                          error_type=type(error).__name__, seconds=time.monotonic() - started,
                          usage=getattr(self.client, 'last_usage', {}), **route, **details)
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
        await check_cancelled(self.repository, self.run_id)
        store = ControlStore(self.repository.engine)
        key = 'search:result:' + self.run_id + ':' + stable_id(query)
        saved = await asyncio.to_thread(store.get, key)
        if saved is not None:
            await trace(self.repository, self.run_id, 'search_cache_hit')
            return [SearchResult.model_validate(item) for item in saved['results']]
        for attempt in range(2):
            await check_cancelled(self.repository, self.run_id)
            await asyncio.to_thread(self.repository.reserve_call, self.run_id, "search", self.limits)
            started = time.monotonic()
            await trace(self.repository, self.run_id, "search_start", attempt=attempt)
            try:
                async with asyncio.timeout(self.limits.search_timeout):
                    results = await self.tool.search(query)
                await trace(self.repository, self.run_id, "search_end", count=len(results), seconds=time.monotonic() - started)
                await asyncio.to_thread(store.put, key, {'results': [item.model_dump(mode='json') for item in results[:self.limits.max_search_results]]})
                return results[:self.limits.max_search_results]
            except (ToolError, TimeoutError) as error:
                await trace(self.repository, self.run_id, "search_failure", error_type=type(error).__name__)
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
