"""Check the execution path and state updates without external services."""

import asyncio

from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError
import pytest

from app.agents.researcher import Researcher
from app.models.client import FakeModelClient
from app.models.schemas import Prospect
from app.orchestration.graph import build_graph, outreach_graph
from app.orchestration.nodes.research import ResearchContext, research
from app.orchestration.state import OutreachState


def test_graph_compiles_with_existing_state_and_only_research():
    graph = build_graph()

    assert isinstance(graph, CompiledStateGraph)
    assert graph.get_input_schema() is OutreachState
    # Check the executable path so later functionality cannot appear unnoticed.
    diagram = graph.get_graph()
    assert set(diagram.nodes) == {START, "research", END}
    assert {(edge.source, edge.target) for edge in diagram.edges} == {
        (START, "research"), ("research", END),
    }
    assert graph.checkpointer is None


def test_research_without_material_returns_only_a_progress_update(populated_state):
    before = populated_state.model_dump()

    update = asyncio.run(research(populated_state, Runtime()))

    assert update == {"current_step": "research_complete"}
    assert populated_state.model_dump() == before


def test_graph_invocation_preserves_populated_state(populated_state):
    before = populated_state.model_dump()

    output = asyncio.run(outreach_graph.ainvoke(populated_state))
    result = OutreachState.model_validate(output)

    assert isinstance(output, dict)
    assert result.current_step == "research_complete"
    assert result.model_dump(exclude={"current_step"}) == {
        field: value for field, value in before.items() if field != "current_step"
    }
    # The graph returns updates; the application wrapper applies them later.
    assert populated_state.model_dump() == before


def test_graph_accepts_dictionary_input_and_preserves_defaults():
    output = asyncio.run(outreach_graph.ainvoke({"goal": "Find professors researching wearable AI"}))
    result = OutreachState.model_validate(output)

    assert result.model_dump() == OutreachState(
        goal="Find professors researching wearable AI", current_step="research_complete"
    ).model_dump()


@pytest.mark.parametrize("goal", ["   ", 42])
def test_graph_uses_existing_goal_validation(goal):
    with pytest.raises(ValidationError):
        asyncio.run(outreach_graph.ainvoke({"goal": goal}))


def test_shared_graph_keeps_concurrent_requests_separate(populated_state):
    empty_state = OutreachState(goal="Find potential open-source partners")

    async def run():
        return await asyncio.gather(
            outreach_graph.ainvoke(populated_state),
            outreach_graph.ainvoke(empty_state),
        )

    populated_output, empty_output = asyncio.run(run())
    populated_result = OutreachState.model_validate(populated_output)
    empty_result = OutreachState.model_validate(empty_output)

    assert populated_result.prospects == populated_state.prospects
    assert empty_result.model_dump() == OutreachState(
        goal=empty_state.goal, current_step="research_complete"
    ).model_dump()
    populated_result.prospects.clear()
    assert empty_result.prospects == []
    # Reusing the compiled path must not retain a previous request's results.
    next_output = asyncio.run(outreach_graph.ainvoke(OutreachState(goal="Another request")))
    assert next_output["prospects"] == []


def test_graph_runs_researcher_with_fake_model(records, research_material, populated_state):
    before = populated_state.model_dump()
    prospect = records[Prospect]
    client = FakeModelClient([{"prospects": [prospect.model_dump()]}])
    context = ResearchContext(researcher=Researcher(client=client), research_material=research_material)

    output = asyncio.run(outreach_graph.ainvoke(populated_state, context=context))
    result = OutreachState.model_validate(output)

    assert result.prospects == [prospect]
    assert result.current_step == "research_complete"
    assert result.model_dump(exclude={"current_step", "prospects"}) == populated_state.model_dump(
        exclude={"current_step", "prospects"}
    )
    assert populated_state.model_dump() == before
    assert len(client.calls) == 1


def test_graph_context_does_not_leak_between_requests(records, research_material):
    first_client = FakeModelClient([{"prospects": [records[Prospect].model_dump()]}])
    second_client = FakeModelClient([{"prospects": []}])

    async def run():
        return await asyncio.gather(
            outreach_graph.ainvoke(
                OutreachState(goal="Find API infrastructure companies"),
                context=ResearchContext(Researcher(client=first_client), research_material),
            ),
            outreach_graph.ainvoke(
                OutreachState(goal="Find professors researching wearable AI"),
                context=ResearchContext(Researcher(client=second_client), research_material),
            ),
        )

    first, second = asyncio.run(run())

    assert len(first["prospects"]) == 1
    assert second["prospects"] == []
    assert len(first_client.calls) == len(second_client.calls) == 1
