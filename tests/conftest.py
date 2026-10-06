"""Shared example data that pytest automatically makes available to tests.

A fixture is a function that prepares data for a test. These fixtures use
function scope by default, so each test gets fresh examples. The company and
contact below are test data, not the results of actual research.
"""

import json

import pytest

from app.models.schemas import (
    EmailDraft,
    OutreachStrategy,
    Prospect,
    Qualification,
    ReviewResult,
)
from app.orchestration.state import OutreachState


@pytest.fixture
def records():
    """Fresh, complete domain records for each test."""
    # Model classes are dictionary keys: records[Prospect] gives its example.
    return {
        Prospect: Prospect(
            id="p1",
            company_name="Example AI",
            website="https://example.com",
            industry="Developer infrastructure",
            decision_maker_name="Example Contact",
            decision_maker_role="Head of Engineering",
            signals=["Hiring platform engineers"],
            sources=["https://example.com/careers"],
        ),
        Qualification: Qualification(
            prospect_id="p1",
            score=86,
            qualified=True,
            reasons=["Developer infrastructure fit", "Platform hiring signal"],
        ),
        OutreachStrategy: OutreachStrategy(
            prospect_id="p1",
            trigger="Hiring platform engineers",
            pain_hypothesis="Platform complexity may be increasing",
            value_proposition="API observability as the platform scales",
            personalization_hook="Recent platform hiring",
            call_to_action="A short technical conversation",
        ),
        EmailDraft: EmailDraft(
            prospect_id="p1",
            subject="API observability for Example AI",
            body="Hi Example Contact,\n\nWould a short technical conversation help?\n",
        ),
        ReviewResult: ReviewResult(
            prospect_id="p1",
            approved=True,
            score=0.9,
            issues=[],
        ),
    }


@pytest.fixture
def outreach_results(records):
    """Arrange the example records into the collections a state expects."""
    # pytest supplies the records fixture because this function requests it
    # by name. All results here refer to the same example prospect, p1.
    return {
        "prospects": [records[Prospect]],
        "qualification_results": [records[Qualification]],
        "qualified_prospects": [records[Prospect]],
        "strategies": {"p1": records[OutreachStrategy]},
        "drafts": {"p1": records[EmailDraft]},
        "reviews": {"p1": records[ReviewResult]},
    }


@pytest.fixture
def populated_state(outreach_results):
    """Provide a complete state to test JSON conversion and preservation."""
    # ** expands dictionary entries into named arguments, such as prospects=...
    return OutreachState(goal="Find AI startups", **outreach_results)


@pytest.fixture
def research_material(records):
    """Source-backed sample notes, supplied locally instead of using search."""
    return json.dumps(records[Prospect].model_dump(mode="json"), ensure_ascii=False, indent=2)
