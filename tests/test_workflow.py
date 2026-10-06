"""Check progress updates and preservation of existing workflow information."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.agents.researcher import Researcher
from app.models.client import FakeModelClient
from app.models.schemas import EmailDraft, Prospect
from app.orchestration.state import OutreachState
from app.orchestration.workflow import run_workflow


def test_workflow_returns_ready_state():
    state = OutreachState(goal="Find AI startups")

    # The workflow is asynchronous. asyncio.run lets this regular test wait
    # for that function to complete and obtain its result.
    result = asyncio.run(run_workflow(state))

    assert result.goal == "Find AI startups"
    assert result.current_step == "research_complete"
    assert result.prospects == []
    assert result.qualification_results == []
    assert result.qualified_prospects == []
    assert result.strategies == {}
    assert result.drafts == {}
    assert result.reviews == {}


def test_workflow_preserves_existing_results(populated_state):
    # Compare everything except progress, which the workflow intentionally changes.
    original = populated_state.model_dump(exclude={"current_step"})

    result = asyncio.run(run_workflow(populated_state))

    assert result.current_step == "research_complete"
    assert result.model_dump(exclude={"current_step"}) == original


def test_workflow_delegates_and_validates_graph_output(monkeypatch, populated_state):
    state = OutreachState(goal=populated_state.goal)
    expected = populated_state.model_copy(update={"current_step": "skeleton_ready"})
    # Replace the graph at the application boundary. JSON-shaped data proves
    # the wrapper restores typed records rather than returning a raw dictionary.
    graph = SimpleNamespace(ainvoke=AsyncMock(return_value=expected.model_dump(mode="json")))
    monkeypatch.setattr("app.orchestration.workflow.outreach_graph", graph)

    result = asyncio.run(run_workflow(state))

    graph.ainvoke.assert_awaited_once_with(state)
    assert result is state
    assert result == expected
    assert isinstance(result.prospects[0], Prospect)
    assert isinstance(result.drafts["p1"], EmailDraft)


def test_workflow_preserves_original_record_behavior(populated_state):
    result = asyncio.run(run_workflow(populated_state))

    assert result is populated_state
    assert populated_state.current_step == "research_complete"


def test_failed_graph_does_not_mark_state_ready(monkeypatch, populated_state):
    before = populated_state.model_dump()
    graph = SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("Graph failed")))
    monkeypatch.setattr("app.orchestration.workflow.outreach_graph", graph)

    with pytest.raises(RuntimeError, match="Graph failed"):
        asyncio.run(run_workflow(populated_state))

    assert populated_state.model_dump() == before


def test_workflow_accepts_injected_researcher(records, research_material):
    state = OutreachState(goal="Find AI startups")
    client = FakeModelClient([{"prospects": [records[Prospect].model_dump()]}])

    result = asyncio.run(run_workflow(
        state, researcher=Researcher(client=client), research_material=research_material,
    ))

    assert result is state
    assert result.prospects == [records[Prospect]]
    assert result.current_step == "research_complete"


def test_invalid_graph_output_does_not_change_original_state(monkeypatch, populated_state):
    before = populated_state.model_dump()
    output = {**before, "current_step": "unknown_step"}
    graph = SimpleNamespace(ainvoke=AsyncMock(return_value=output))
    monkeypatch.setattr("app.orchestration.workflow.outreach_graph", graph)

    # LangGraph output is a dictionary. The wrapper must validate it before
    # copying any updates into the application record.
    with pytest.raises(ValidationError):
        asyncio.run(run_workflow(populated_state))

    assert populated_state.model_dump() == before
