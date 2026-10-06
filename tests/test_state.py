"""Check one request's state, nested records, and independence from other runs."""

import json

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    EmailDraft,
    OutreachStrategy,
    Prospect,
    Qualification,
    ReviewResult,
)
from app.orchestration.state import OutreachState


def test_state_starts_with_empty_results():
    state = OutreachState(goal="Find AI startups")

    # Check the full starting record, including every empty result collection.
    assert state.model_dump() == {
        "goal": "Find AI startups",
        "prospects": [],
        "qualification_results": [],
        "qualified_prospects": [],
        "strategies": {},
        "drafts": {},
        "reviews": {},
        "current_step": "initialized",
    }


def test_state_requires_a_goal():
    with pytest.raises(ValidationError):
        OutreachState()


def test_state_uses_the_same_goal_validation():
    assert OutreachState(goal="  Find AI startups\n").goal == "Find AI startups"

    with pytest.raises(ValidationError):
        OutreachState(goal="   ")


def test_state_collections_are_independent(outreach_results):
    first = OutreachState(goal="First request")
    second = OutreachState(goal="Second request")

    # Populate only the first request. The second request must stay empty.
    first.prospects.extend(outreach_results["prospects"])
    first.qualification_results.extend(outreach_results["qualification_results"])
    first.qualified_prospects.extend(outreach_results["qualified_prospects"])
    first.strategies.update(outreach_results["strategies"])
    first.drafts.update(outreach_results["drafts"])
    first.reviews.update(outreach_results["reviews"])

    assert second.prospects == []
    assert second.qualification_results == []
    assert second.qualified_prospects == []
    assert second.strategies == {}
    assert second.drafts == {}
    assert second.reviews == {}


def test_state_serializes_to_json():
    state = OutreachState(goal="Find AI startups")

    assert json.loads(state.model_dump_json()) == state.model_dump()


def test_state_converts_nested_data_to_domain_models(populated_state):
    # Incoming JSON-compatible dictionaries should become the appropriate
    # Pydantic records when a state is constructed from them.
    state = OutreachState.model_validate(populated_state.model_dump(mode="json"))

    assert isinstance(state.prospects[0], Prospect)
    assert isinstance(state.qualification_results[0], Qualification)
    assert isinstance(state.qualified_prospects[0], Prospect)
    assert isinstance(state.strategies["p1"], OutreachStrategy)
    assert isinstance(state.drafts["p1"], EmailDraft)
    assert isinstance(state.reviews["p1"], ReviewResult)


def test_populated_state_round_trips_json(populated_state):
    # Check that saving the state as JSON text and reading it back loses no data.
    serialized = populated_state.model_dump_json()
    restored = OutreachState.model_validate_json(serialized)

    assert restored == populated_state
    assert json.loads(serialized) == populated_state.model_dump(mode="json")


@pytest.mark.parametrize(
    "field",
    [
        "prospects", "qualification_results", "qualified_prospects",
        "strategies", "drafts", "reviews",
    ],
)
def test_state_rejects_incomplete_nested_records(field):
    value = [{}] if field in {
        "prospects", "qualification_results", "qualified_prospects"
    } else {"p1": {}}

    with pytest.raises(ValidationError):
        OutreachState.model_validate({"goal": "Find AI startups", field: value})
