"""Check progress updates and preservation of existing workflow information."""

import asyncio

from app.orchestration.state import OutreachState
from app.orchestration.workflow import run_workflow


def test_workflow_returns_ready_state():
    state = OutreachState(goal="Find AI startups")

    # The workflow is asynchronous. asyncio.run lets this regular test wait
    # for that function to complete and obtain its result.
    result = asyncio.run(run_workflow(state))

    assert result.goal == "Find AI startups"
    assert result.current_step == "skeleton_ready"
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

    assert result.current_step == "skeleton_ready"
    assert result.model_dump(exclude={"current_step"}) == original
