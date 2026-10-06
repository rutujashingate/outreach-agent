"""The node passes inputs to the component and returns partial state updates."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langgraph.runtime import Runtime
import pytest

from app.models.client import ModelResponseError
from app.models.schemas import Prospect
from app.orchestration.nodes.research import ResearchContext, research


def test_node_delegates_and_updates_only_research_fields(populated_state, research_material, records):
    before = populated_state.model_dump()
    component = SimpleNamespace(research=AsyncMock(return_value=[records[Prospect]]))
    runtime = Runtime(context=ResearchContext(component, research_material))

    updates = asyncio.run(research(populated_state, runtime))

    component.research.assert_awaited_once_with(goal=populated_state.goal, research_material=research_material)
    assert updates == {"prospects": [records[Prospect]], "current_step": "research_complete"}
    assert populated_state.model_dump() == before


def test_node_replaces_old_prospects_when_new_material_has_no_matches(populated_state, research_material):
    component = SimpleNamespace(research=AsyncMock(return_value=[]))

    updates = asyncio.run(research(populated_state, Runtime(context=ResearchContext(component, research_material))))

    assert updates == {"prospects": [], "current_step": "research_complete"}
    assert populated_state.prospects


def test_node_propagates_research_failure_without_updates(populated_state, research_material):
    before = populated_state.model_dump()
    component = SimpleNamespace(research=AsyncMock(side_effect=ModelResponseError("Invalid research")))

    with pytest.raises(ModelResponseError, match="Invalid research"):
        asyncio.run(research(populated_state, Runtime(context=ResearchContext(component, research_material))))

    assert populated_state.model_dump() == before
