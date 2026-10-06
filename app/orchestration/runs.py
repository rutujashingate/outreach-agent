"""Start, inspect, and resume the same checkpointed outreach execution."""

from contextlib import asynccontextmanager
from asyncio import CancelledError
from uuid import uuid4

from langgraph.types import Command
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from openai import AsyncOpenAI

from app.memory.repository import Repository
from app.models.client import OpenAIModelClient
from app.models.groq_client import GroqModelClient
from app.models.workflow import ApprovalSubmission, RunResponse, WorkflowRequest, WorkflowState
from app.observability import events, trace
from app.orchestration.context import ManagedModelClient, ManagedSearchTool, WorkflowContext
from app.orchestration.checkpoints import checkpoint_serializer
from app.orchestration.full_graph import build_full_graph
from app.orchestration.nodes.approval import validate_decisions
from app.settings import Settings
from app.tools.gmail import GmailTool
from app.tools.search import SearchTool


class ConfigurationError(RuntimeError):
    pass


class RunNotFound(LookupError):
    pass


class RunConflict(RuntimeError):
    pass


@asynccontextmanager
async def real_model_client(settings: Settings):
    """Open the SDK lazily: approving or rejecting may need no model call."""
    import os
    sdk = None
    groq = None
    class LazyClient:
        last_usage = {}
        model_name = None

        async def generate_structured(self, **kwargs):
            nonlocal sdk, groq
            if settings.model_provider == "groq":
                if groq is None:
                    try:
                        groq = GroqModelClient.from_env(
                            max_output_tokens=settings.limits.max_output_tokens,
                            timeout=settings.limits.model_timeout,
                        )
                    except ValueError as error:
                        raise ConfigurationError("Configure GROQ_API_KEY and a supported GROQ_MODEL for complete runs.") from error
                result = await groq.generate_structured(**kwargs)
                self.last_usage = groq.last_usage
                self.model_name = groq.model_name
                return result
            api_key, model = os.getenv("OPENAI_API_KEY", ""), os.getenv("OPENAI_MODEL", "")
            if not api_key.strip() or not model.strip():
                raise ConfigurationError("Configure OPENAI_API_KEY and OPENAI_MODEL for complete runs.")
            if sdk is None:
                # SDK retries are disabled: the wrapper counts and limits each
                # attempt, rather than hiding extra requests inside the SDK.
                sdk = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=settings.limits.model_timeout)
            client = OpenAIModelClient(model=model, sdk_client=sdk,
                                       max_output_tokens=settings.limits.max_output_tokens)
            result = await client.generate_structured(**kwargs)
            self.last_usage = client.last_usage
            self.model_name = model
            return result
    try:
        yield LazyClient()
    finally:
        if groq is not None:
            await groq.aclose()
        if sdk is not None:
            await sdk.close()


class RunManager:
    """Own graph execution; APIs translate HTTP requests into these operations."""

    def __init__(self, repository: Repository, checkpointer, *, settings: Settings | None = None,
                 client_factory=None, search: SearchTool | None = None, gmail: GmailTool | None = None,
                 memory_retriever=None):
        self.repository, self.settings = repository, settings or Settings()
        if isinstance(checkpointer.serde, JsonPlusSerializer):
            checkpointer.serde = checkpoint_serializer()
        self.graph = build_full_graph(checkpointer)
        self.client_factory = client_factory or (lambda: real_model_client(self.settings))
        self.search, self.gmail = search, gmail
        self.memory_retriever = memory_retriever

    def config(self, run_id: str):
        return {"configurable": {"thread_id": run_id}, "recursion_limit": self.settings.limits.max_graph_steps}

    @asynccontextmanager
    async def context(self, run_id: str):
        async with self.client_factory() as client:
            yield WorkflowContext(
                client=ManagedModelClient(client, self.repository, run_id, self.settings.limits),
                repository=self.repository, limits=self.settings.limits,
                search=ManagedSearchTool(self.search, self.repository, run_id, self.settings.limits) if self.search else None,
                gmail=self.gmail, read_gmail=self.settings.read_gmail, sending_enabled=self.settings.sending_enabled,
                memory_retriever=self.memory_retriever,
            )

    async def start(self, request: WorkflowRequest) -> RunResponse:
        if self.settings.read_gmail and self.gmail is None:
            raise ConfigurationError("Gmail reading was requested; configure GMAIL_ACCESS_TOKEN.")
        if request.use_search and self.search is None:
            raise ConfigurationError("Search was requested; configure BRAVE_SEARCH_API_KEY or inject a search tool.")
        if request.gmail_action != "none" and (self.gmail is None or request.sender.email is None):
            raise ConfigurationError("Gmail actions require Gmail configuration and a sender email.")
        if request.gmail_action == "send" and not self.settings.sending_enabled:
            raise RunConflict("Sending is disabled. It requires explicit enablement and human approval.")
        state = WorkflowState(run_id=uuid4().hex, **request.model_dump())
        self.repository.save_run(state, "running")
        return await self._execute(state.run_id, state)

    def get(self, run_id: str) -> RunResponse:
        record = self.repository.run(run_id)
        if record is None:
            raise RunNotFound("Unknown run identifier.")
        return RunResponse(state=WorkflowState.model_validate(record["state"]),
                           awaiting_approval=record["status"] == "paused", error=record["error"])

    async def resume(self, run_id: str, submission: ApprovalSubmission) -> RunResponse:
        return await self._execute(run_id, Command(resume=submission.model_dump(mode="json")), submission=submission)

    async def retry(self, run_id: str) -> RunResponse:
        return await self._execute(run_id, None, retry=True)

    async def _execute(self, run_id: str, input_value, *, submission=None, retry=False) -> RunResponse:
        previous = self.repository.run(run_id)
        if previous is None:
            raise RunNotFound("Unknown run identifier.")
        limits = self.settings.limits
        lease_seconds = int(limits.max_model_calls * limits.model_timeout +
                            limits.max_search_calls * limits.search_timeout +
                            limits.max_qualified * limits.tool_timeout * 12 + 120)
        if not self.repository.acquire_run(run_id, lease_seconds):
            raise RunConflict("This run is already being processed.")
        try:
            # Read again after acquiring the lease to reject stale concurrent
            # approvals rather than using a snapshot read before the lock.
            previous = self.repository.run(run_id)
            state = WorkflowState.model_validate(previous["state"])
            if submission is not None:
                if previous["status"] != "paused":
                    raise RunConflict("This run is not waiting for approval.")
                snapshot = await self.graph.aget_state(self.config(run_id))
                if not snapshot.values:
                    raise RunConflict("This run's checkpoint is unavailable.")
                state = WorkflowState.model_validate(snapshot.values)
                validate_decisions(state, submission)
            if retry:
                if previous["status"] != "failed":
                    raise RunConflict("Only a failed execution can be retried.")
                snapshot = await self.graph.aget_state(self.config(run_id))
                if not snapshot.values or not snapshot.next:
                    raise RunConflict("There is no resumable failed checkpoint.")
            self.repository.save_run(state, "running")
            trace(self.repository, run_id, "resume" if submission is not None else "retry" if retry else "run_start")
            try:
                async with self.context(run_id) as context:
                    await self.graph.ainvoke(input_value, self.config(run_id), context=context)
                snapshot = await self.graph.aget_state(self.config(run_id))
                result = WorkflowState.model_validate(snapshot.values)
                paused = any(task.interrupts for task in snapshot.tasks)
                self.repository.save_run(result, "paused" if paused else "completed")
                trace(self.repository, run_id, "run_paused" if paused else "run_end", current_step=result.current_step)
                return RunResponse(state=result, awaiting_approval=paused)
            except (Exception, CancelledError) as error:
                snapshot = await self.graph.aget_state(self.config(run_id))
                result = WorkflowState.model_validate(snapshot.values) if snapshot.values else state
                result.current_step = "failed"
                self.repository.save_run(result, "failed", "Workflow execution failed; inspect execution events.")
                trace(self.repository, run_id, "run_failure", error_type=type(error).__name__)
                # Let HTTP callers inspect or retry the persisted execution
                # instead of losing its identifier when an invocation fails.
                error.run_id = run_id
                raise
        finally:
            self.repository.release_run(run_id)

    def execution_events(self, run_id: str) -> list[dict]:
        self.get(run_id)
        return events(self.repository, run_id)
