"""Shared example data that pytest automatically makes available to tests.

A fixture is a function that prepares data for a test. These fixtures use
function scope by default, so each test gets fresh examples. The company and
contact below are test data, not the results of actual research.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.models.schemas import (
    EmailDraft,
    OutreachStrategy,
    Prospect,
    Qualification,
    ReviewResult,
)
from app.orchestration.state import OutreachState


@pytest.fixture(autouse=True)
def isolated_application_settings(monkeypatch, tmp_path):
    """Tests use their own settings and data, even after you configure a real account."""
    import os
    for key in tuple(os.environ):
        if key.startswith(("OUTREACH_", "OPENAI_", "GROQ_")) or key in {"GMAIL_ACCESS_TOKEN", "BRAVE_SEARCH_API_KEY"}:
            monkeypatch.delenv(key)
    monkeypatch.setenv("OUTREACH_DATA_DIR", str(tmp_path / "application-data"))


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


@pytest.fixture
def workflow_data(records, research_material):
    """A complete six-call script, with evidence and an explicitly supplied address."""
    from app.models.workflow import WorkflowRequest
    goal = "Find AI startups"
    interpretation = {"raw_goal": goal, "goal_type": "sales", "objective": "Find relevant startups",
        "target_entity": "organization", "target_description": "AI startups",
        "desired_outcome": "A technical conversation"}
    responses = [interpretation, {"prospects": [records[Prospect].model_dump()]},
        records[Qualification].model_dump(), records[OutreachStrategy].model_dump(),
        records[EmailDraft].model_dump(), records[ReviewResult].model_dump()]
    request = WorkflowRequest(goal=goal, research_material=research_material,
        sender={"name": "Example User", "email": "user@example.com"},
        recipients={"p1": {"email": "contact@example.com"}})
    return SimpleNamespace(request=request, responses=responses)


@pytest.fixture
def make_run_manager(workflow_data):
    """Build real local graphs with replaceable clients and close test databases."""
    from langgraph.checkpoint.memory import InMemorySaver
    from app.db.database import create_database
    from app.memory.repository import Repository
    from app.models.client import FakeModelClient
    from app.orchestration.runs import RunManager
    from app.settings import Settings
    from app.tools.gmail import FakeGmailClient
    engines = []
    def make(*, responses=None, client=None, repository=None, settings=None,
             checkpointer=None, gmail=None, search=None):
        client = client or FakeModelClient(workflow_data.responses if responses is None else responses)
        if repository is None:
            repository = Repository(create_database())
            engines.append(repository.engine)
        @asynccontextmanager
        async def factory():
            yield client
        manager = RunManager(repository, checkpointer or InMemorySaver(), client_factory=factory,
            settings=settings or Settings(checkpoint_backend="memory"),
            gmail=gmail or FakeGmailClient(), search=search)
        return SimpleNamespace(manager=manager, client=client, gmail=manager.gmail, repository=repository)
    yield make
    for engine in engines:
        engine.dispose()
