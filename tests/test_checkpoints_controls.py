"""Check restart recovery, budgets, injected model routes, and parallel results."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy

import pytest

from app.db.database import create_database
from app.memory.repository import Repository
from app.models.client import FakeModelClient, ModelClientError
from app.models.router import ModelRouter, TaskMeasurement
from app.models.schemas import Qualification
from app.models.workflow import ApprovalSubmission, SearchResult
from app.orchestration.checkpoints import open_checkpointer
from app.orchestration.context import ManagedModelClient
from app.orchestration.runs import RunManager
from app.security.limits import LimitExceeded, Limits
from app.settings import Settings
from app.tools.search import FakeSearchTool


def test_sqlite_checkpoint_resumes_after_closing_and_reopening(tmp_path, workflow_data):
    repository = Repository(create_database(f"sqlite:///{tmp_path / 'relationships.sqlite3'}"))
    settings = Settings(data_dir=tmp_path, checkpoint_backend="sqlite")
    first_client = FakeModelClient(workflow_data.responses)
    second_client = FakeModelClient([])
    @asynccontextmanager
    async def first_factory():
        yield first_client
    @asynccontextmanager
    async def second_factory():
        yield second_client
    async def run():
        async with open_checkpointer(settings) as first_saver:
            first = RunManager(repository, first_saver, settings=settings, client_factory=first_factory)
            paused = await first.start(workflow_data.request)
        async with open_checkpointer(settings) as second_saver:
            second = RunManager(repository, second_saver, settings=settings, client_factory=second_factory)
            request = paused.state.approval_requests[0]
            return await second.resume(paused.state.run_id, ApprovalSubmission(decisions=[{
                "prospect_id": "p1", "version": request.version, "fingerprint": request.fingerprint, "action": "approve",
            }]))
    try:
        completed = asyncio.run(run())
        assert completed.state.outcomes["p1"].status == "approved"
        assert len(first_client.calls) == 6
        assert second_client.calls == []
        assert repository.run(completed.state.run_id)["model_calls"] == 6
    finally:
        repository.engine.dispose()


def test_model_call_limit_survives_retry_and_preserves_failed_checkpoint(make_run_manager, workflow_data):
    setup = make_run_manager(settings=Settings(checkpoint_backend="memory", limits=Limits(max_model_calls=1)))
    async def run():
        with pytest.raises(LimitExceeded):
            await setup.manager.start(workflow_data.request)
        # Find the identifier through the persisted execution trace boundary.
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from app.db.models import RunRow
        with Session(setup.repository.engine) as session:
            run_id = session.scalar(select(RunRow.id))
        assert setup.manager.get(run_id).state.current_step == "failed"
        with pytest.raises(LimitExceeded):
            await setup.manager.retry(run_id)
        assert setup.repository.run(run_id)["model_calls"] == 1
    asyncio.run(run())
    assert len(setup.client.calls) == 1


def test_estimated_cost_budget_stops_before_another_call(make_run_manager, workflow_data):
    setup = make_run_manager(settings=Settings(checkpoint_backend="memory", limits=Limits(
        max_estimated_cost_per_run=0.05, estimated_cost_per_call=0.05)))
    with pytest.raises(LimitExceeded):
        asyncio.run(setup.manager.start(workflow_data.request))
    assert len(setup.client.calls) == 1


def test_timeout_is_bounded_and_recorded(make_run_manager, workflow_data):
    class SlowClient:
        async def generate_structured(self, **kwargs):
            await asyncio.sleep(1)
    setup = make_run_manager(client=SlowClient(), settings=Settings(checkpoint_backend="memory", limits=Limits(model_timeout=0.01)))
    with pytest.raises(ModelClientError, match="time limit"):
        asyncio.run(setup.manager.start(workflow_data.request))


def test_search_is_injected_and_sources_reach_prospects(make_run_manager, workflow_data):
    prospect = workflow_data.responses[1]["prospects"][0]
    search = FakeSearchTool([SearchResult(title=prospect["company_name"], url=prospect["sources"][0], description=str(prospect))])
    setup = make_run_manager(search=search)
    request = workflow_data.request.model_copy(update={"use_search": True, "research_material": ""})
    result = asyncio.run(setup.manager.start(request))
    assert result.awaiting_approval
    assert search.queries == ["AI startups"]
    assert result.state.search_results[0].url == prospect["sources"][0]
    assert result.state.prospects[0].sources == prospect["sources"]


def test_model_routing_requires_measurements_and_keeps_shared_interface():
    default, routed = FakeModelClient([]), FakeModelClient([{"prospect_id": "p1", "score": 80, "qualified": True}])
    with pytest.raises(ValueError, match="measurements"):
        ModelRouter(default, {"Qualification": routed})
    router = ModelRouter(default, {"Qualification": routed}, {"Qualification": TaskMeasurement(
        quality=0.95, cost_usd=0.01, latency_seconds=0.1, source="Synthetic routing test, not a production measurement.")})
    result = asyncio.run(router.generate_structured(instructions="Assess", input_text="Prospect", response_model=Qualification))
    assert result["score"] == 80
    assert len(routed.calls) == 1 and default.calls == []


def test_parallel_qualification_keeps_results_associated_and_bounds_concurrency(make_run_manager, workflow_data):
    responses = deepcopy(workflow_data.responses)
    first = responses[1]["prospects"][0]
    second = {**first, "id": "p2", "company_name": "Another AI"}
    responses[1]["prospects"].append(second)
    # Deliberately complete p2 first. Results must still join by prospect ID.
    queued = FakeModelClient(responses[:2])
    class ParallelClient:
        def __init__(self):
            self.active = 0
            self.maximum = 0
        async def generate_structured(self, *, instructions, input_text, response_model):
            if response_model is not Qualification:
                return await queued.generate_structured(instructions=instructions, input_text=input_text, response_model=response_model)
            import json
            prospect = json.loads(input_text)["prospect"]
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            await asyncio.sleep(0.02 if prospect["id"] == "p1" else 0.001)
            self.active -= 1
            return {"prospect_id": prospect["id"], "score": 80 if prospect["id"] == "p1" else 90, "qualified": True}
    client = ParallelClient()
    setup = make_run_manager(client=client, settings=Settings(checkpoint_backend="memory", limits=Limits(concurrency=2)))
    request = workflow_data.request.model_copy(update={"research_material": str([first, second]), "recipients": {}})
    result = asyncio.run(setup.manager.start(request))
    assert client.maximum == 2
    assert [prospect.id for prospect in result.state.qualified_prospects] == ["p2", "p1"]
    assert {item.prospect_id: item.score for item in result.state.qualification_results} == {"p1": 80, "p2": 90}
    assert all(outcome.status == "blocked" for outcome in result.state.outcomes.values())


def test_estimated_budget_accepts_exact_boundary_without_float_rounding_loss(make_run_manager, workflow_data):
    setup = make_run_manager()
    from app.models.workflow import WorkflowState
    limits = Limits(max_model_calls=40, estimated_cost_per_call=0.05, max_estimated_cost_per_run=2.0)
    setup.repository.save_run(WorkflowState(run_id="budget", goal="Find prospects"), "running")
    for _ in range(40):
        setup.repository.reserve_call("budget", "model", limits)
    with pytest.raises(LimitExceeded):
        setup.repository.reserve_call("budget", "model", limits)
    assert setup.repository.run("budget")["model_calls"] == 40


def test_original_workflow_can_use_injected_search(make_run_manager, workflow_data):
    from app.agents.researcher import Researcher
    from app.orchestration.state import OutreachState
    from app.orchestration.workflow import run_workflow
    prospect = workflow_data.responses[1]["prospects"][0]
    client = FakeModelClient([{"prospects": [prospect]}])
    search = FakeSearchTool([SearchResult(title=prospect["company_name"], url=prospect["sources"][0], description=str(prospect))])
    result = asyncio.run(run_workflow(OutreachState(goal=workflow_data.request.goal), researcher=Researcher(client=client, search_tool=search)))
    assert result.prospects[0].id == "p1"
    assert len(search.queries) == len(client.calls) == 1


def test_parallel_full_preparation_isolates_a_failed_prospect(make_run_manager, workflow_data):
    import json
    responses = deepcopy(workflow_data.responses)
    first = responses[1]["prospects"][0]
    second = {**first, "id": "p2", "company_name": "Another AI"}
    class ScriptedClient:
        def __init__(self):
            self.active = 0
            self.maximum = 0
        async def generate_structured(self, *, instructions, input_text, response_model):
            name = response_model.__name__
            if name == "OutreachGoal":
                return responses[0]
            if name == "ResearchResult":
                return {"prospects": [first, second]}
            data = json.loads(input_text)
            prospect_id = data.get("prospect", data.get("research"))["id"]
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            await asyncio.sleep(0.01 if prospect_id == "p1" else 0.002)
            self.active -= 1
            template = {"Qualification": responses[2], "OutreachStrategy": responses[3],
                        "EmailDraft": responses[4], "ReviewResult": responses[5]}[name]
            result = {**template, "prospect_id": prospect_id}
            if name == "EmailDraft" and prospect_id == "p2":
                result["prospect_id"] = "wrong-prospect"
            return result
    client = ScriptedClient()
    setup = make_run_manager(client=client, settings=Settings(checkpoint_backend="memory", limits=Limits(concurrency=2)))
    request = workflow_data.request.model_copy(update={"research_material": str([first, second]),
        "recipients": {**workflow_data.request.recipients, "p2": workflow_data.request.recipients["p1"].model_copy(update={"email": "other@example.com"})}})
    result = asyncio.run(setup.manager.start(request))
    assert result.awaiting_approval
    assert client.maximum == 2
    assert set(result.state.drafts) == {"p1"}
    assert result.state.outcomes["p2"].status == "failed"
    assert result.state.failures["p2"] == "Writing failed."
    assert [item.prospect.id for item in result.state.approval_requests] == ["p1"]
    assert any(event["event"] == "prospect_failure" and event["prospect_id"] == "p2"
               for event in setup.manager.execution_events(result.state.run_id))
