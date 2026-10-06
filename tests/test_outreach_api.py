"""Test the request-to-response path without starting an external web server.

TestClient sends simulated HTTP requests directly to the application. Tests
substitute a fake workflow when they need to inspect coordination or isolation.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi.testclient import TestClient

from app.api.outreach import get_research_client
from app.main import app
from app.models.client import FakeModelClient, ModelClientError
from app.models.schemas import Prospect
from app.orchestration.graph import outreach_graph
from app.orchestration.state import OutreachState


@pytest.fixture
def client():
    """Give each test an application client and close it after the test."""
    with TestClient(app) as test_client:
        # yield hands the client to the test; the context closes when it finishes.
        yield test_client


def test_outreach_returns_ready_state(client):
    # Exercise the real endpoint and coordinator with an example JSON request.
    response = client.post("/outreach", json={"goal": "Find AI startups"})

    assert response.status_code == 200
    assert response.json() == {
        "goal": "Find AI startups",
        "prospects": [],
        "qualification_results": [],
        "qualified_prospects": [],
        "strategies": {},
        "drafts": {},
        "reviews": {},
        "current_step": "research_complete",
    }


def test_outreach_reaches_langgraph_through_existing_workflow(client, monkeypatch):
    # Wrap the real graph call so this checks the complete path through the API.
    graph_call = AsyncMock(wraps=outreach_graph.ainvoke)
    monkeypatch.setattr(
        "app.orchestration.workflow.outreach_graph",
        SimpleNamespace(ainvoke=graph_call),
    )
    goal = "Find professors researching wearable AI and prepare PhD outreach."

    response = client.post("/outreach", json={"goal": goal})

    assert response.status_code == 200
    assert response.json() == OutreachState(
        goal=goal, current_step="research_complete"
    ).model_dump(mode="json")
    graph_call.assert_awaited_once()
    assert isinstance(graph_call.await_args.args[0], OutreachState)


def test_invalid_request_never_reaches_graph(client, monkeypatch):
    graph_call = AsyncMock()
    monkeypatch.setattr(
        "app.orchestration.workflow.outreach_graph",
        SimpleNamespace(ainvoke=graph_call),
    )

    response = client.post("/outreach", json={"goal": "   "})

    assert response.status_code == 422
    graph_call.assert_not_called()


@pytest.mark.parametrize(
    "goal",
    ["x", "x" * 2000, " \t" + "x" * 2000 + "\n "],
    ids=["minimum", "maximum", "trim-before-length"],
)
def test_outreach_accepts_goal_boundaries(client, goal):
    response = client.post("/outreach", json={"goal": goal})

    assert response.status_code == 200
    assert response.json()["goal"] == goal.strip()


def test_outreach_passes_validated_state_and_returns_workflow_result(
    client, monkeypatch, populated_state
):
    workflow_result = populated_state
    workflow_result.goal = "Find  AI startups"
    workflow_result.current_step = "skeleton_ready"
    # AsyncMock behaves like an awaitable function and remembers its calls.
    workflow = AsyncMock(return_value=workflow_result)
    # Replace the function used by the endpoint for this test. pytest restores
    # the original automatically after the test.
    monkeypatch.setattr("app.api.outreach.run_workflow", workflow)

    response = client.post("/outreach", json={"goal": " \tFind  AI startups\n"})

    assert response.status_code == 200
    assert response.json() == workflow_result.model_dump(mode="json")
    workflow.assert_awaited_once()
    # Inspect the first argument the endpoint supplied when awaiting the mock.
    passed_state = workflow.await_args.args[0]
    assert isinstance(passed_state, OutreachState)
    assert passed_state.goal == "Find  AI startups"
    assert passed_state.current_step == "initialized"
    assert passed_state.prospects == []
    assert passed_state.qualification_results == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"goal": None},
        {"goal": ""},
        {"goal": " \t\n "},
        {"goal": 42},
        {"goal": 3.14},
        {"goal": True},
        {"goal": ["Find startups"]},
        {"goal": {"text": "Find startups"}},
        {"goal": "x" * 2001},
        {"goal": "Find startups", "unexpected": "value"},
        {"goal": "Find startups", "current_step": "skeleton_ready"},
    ],
    ids=[
        "missing", "null", "empty", "whitespace", "integer", "float",
        "boolean", "list", "object", "too-long", "extra-field", "supplied-state",
    ],
)
def test_invalid_requests_stop_before_workflow(client, monkeypatch, payload):
    workflow = AsyncMock()
    monkeypatch.setattr("app.api.outreach.run_workflow", workflow)

    response = client.post("/outreach", json=payload)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    # Invalid input must stop at validation, before any workflow work begins.
    workflow.assert_not_called()


def test_requests_have_independent_state(client, monkeypatch, outreach_results):
    states = []

    # This fake coordinator adds results to the first request only. If the
    # second request receives those results, the application is sharing state.
    async def workflow(state):
        states.append(state)
        if len(states) == 1:
            state.prospects.extend(outreach_results["prospects"])
            state.qualification_results.extend(outreach_results["qualification_results"])
            state.qualified_prospects.extend(outreach_results["qualified_prospects"])
            state.strategies.update(outreach_results["strategies"])
            state.drafts.update(outreach_results["drafts"])
            state.reviews.update(outreach_results["reviews"])
        state.current_step = "skeleton_ready"
        return state

    monkeypatch.setattr("app.api.outreach.run_workflow", workflow)

    first = client.post("/outreach", json={"goal": "First request"})
    second = client.post("/outreach", json={"goal": "Second request"})

    assert first.status_code == second.status_code == 200
    assert first.json() == states[0].model_dump(mode="json")
    assert first.json()["prospects"][0]["id"] == "p1"
    assert first.json()["qualification_results"][0]["score"] == 86
    assert second.json() == {
        "goal": "Second request",
        "prospects": [],
        "qualification_results": [],
        "qualified_prospects": [],
        "strategies": {},
        "drafts": {},
        "reviews": {},
        "current_step": "skeleton_ready",
    }
    assert states[0] is not states[1]


def test_openapi_documents_request_and_response(client):
    # OpenAPI is the machine-readable description used to build the /docs page.
    response = client.get("/openapi.json")

    assert response.status_code == 200
    specification = response.json()
    operation = specification["paths"]["/outreach"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/OutreachRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/OutreachState"
    }
    request_schema = specification["components"]["schemas"]["OutreachRequest"]
    assert request_schema["required"] == ["goal"]
    assert request_schema["additionalProperties"] is False
    assert request_schema["properties"]["goal"]["minLength"] == 1
    assert request_schema["properties"]["goal"]["maxLength"] == 2000

    # A $ref points to a named schema. Verify that result collections reference
    # the intended records rather than accepting arbitrary dictionaries.
    components = specification["components"]["schemas"]
    state_properties = components["OutreachState"]["properties"]
    for field, model in [
        ("prospects", "Prospect"),
        ("qualification_results", "Qualification"),
        ("qualified_prospects", "Prospect"),
    ]:
        assert state_properties[field]["items"] == {
            "$ref": f"#/components/schemas/{model}"
        }
    for field, model in [
        ("strategies", "OutreachStrategy"),
        ("drafts", "EmailDraft"),
        ("reviews", "ReviewResult"),
    ]:
        assert state_properties[field]["additionalProperties"] == {
            "$ref": f"#/components/schemas/{model}"
        }
    qualification_score = components["Qualification"]["properties"]["score"]
    assert qualification_score["type"] == "integer"
    assert qualification_score["minimum"] == 0
    assert qualification_score["maximum"] == 100


def test_api_documentation_is_available(client):
    response = client.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_api_research_with_injected_fake_client(client, monkeypatch, records, research_material):
    fake = FakeModelClient([{"prospects": [records[Prospect].model_dump()]}])
    monkeypatch.setitem(app.dependency_overrides, get_research_client, lambda: fake)

    response = client.post("/outreach", json={"goal": "Find AI startups", "research_material": research_material})

    assert response.status_code == 200
    assert response.json() == OutreachState(
        goal="Find AI startups", prospects=[records[Prospect]], current_step="research_complete",
    ).model_dump(mode="json")
    assert len(fake.calls) == 1
    assert "research_material" not in response.json()


def test_api_reports_missing_research_configuration(client, monkeypatch, research_material):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    response = client.post("/outreach", json={"goal": "Find AI startups", "research_material": research_material})

    assert response.status_code == 503
    assert "OPENAI_MODEL" in response.json()["detail"]


@pytest.mark.parametrize("material", [None, 42, True, [], {}])
def test_invalid_material_is_rejected_before_client_creation(client, monkeypatch, material):
    factory = Mock(side_effect=AssertionError("The client must not be created"))
    monkeypatch.setattr("app.api.outreach.OpenAIModelClient.from_env", factory)

    response = client.post("/outreach", json={"goal": "Find AI startups", "research_material": material})

    assert response.status_code == 422
    factory.assert_not_called()


def test_invalid_goal_with_material_stops_before_client_creation(client, monkeypatch, research_material):
    factory = Mock(side_effect=AssertionError("The client must not be created"))
    monkeypatch.setattr("app.api.outreach.OpenAIModelClient.from_env", factory)

    response = client.post("/outreach", json={"goal": " ", "research_material": research_material})

    assert response.status_code == 422
    factory.assert_not_called()


@pytest.mark.parametrize("material", ["", " \n\t "])
def test_blank_material_needs_no_model_configuration(client, monkeypatch, material):
    factory = Mock(side_effect=AssertionError("The client must not be created"))
    monkeypatch.setattr("app.api.outreach.OpenAIModelClient.from_env", factory)

    response = client.post("/outreach", json={"goal": "Find AI startups", "research_material": material})

    assert response.status_code == 200
    assert response.json()["prospects"] == []
    assert response.json()["current_step"] == "research_complete"
    factory.assert_not_called()


@pytest.mark.parametrize("failure", ["request", "output"])
def test_api_model_failure_returns_error_instead_of_success(client, monkeypatch, research_material, failure):
    if failure == "request":
        fake = SimpleNamespace(generate_structured=AsyncMock(side_effect=ModelClientError("Private failure details")))
    else:
        fake = FakeModelClient([{"prospects": [{}]}])
    monkeypatch.setitem(app.dependency_overrides, get_research_client, lambda: fake)

    response = client.post("/outreach", json={"goal": "Find AI startups", "research_material": research_material})

    assert response.status_code == 502
    assert response.json() == {"detail": "Research could not complete."}


@pytest.mark.parametrize("valid_output", [True, False])
def test_api_owned_client_is_closed_on_success_and_failure(
    client, monkeypatch, research_material, records, valid_output
):
    payload = {"prospects": [records[Prospect].model_dump()]} if valid_output else {"prospects": [{}]}
    fake = FakeModelClient([payload])
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=fake)
    manager.__aexit__ = AsyncMock(return_value=False)
    factory = Mock(return_value=manager)
    monkeypatch.setattr("app.api.outreach.OpenAIModelClient.from_env", factory)

    response = client.post("/outreach", json={"goal": "Find AI startups", "research_material": research_material})

    assert response.status_code == (200 if valid_output else 502)
    factory.assert_called_once_with()
    manager.__aenter__.assert_awaited_once()
    manager.__aexit__.assert_awaited_once()


def test_openapi_documents_optional_material_and_research_status(client):
    components = client.get("/openapi.json").json()["components"]["schemas"]

    request = components["OutreachRequest"]
    assert request["required"] == ["goal"]
    assert request["properties"]["research_material"]["type"] == "string"
    assert request["properties"]["research_material"]["default"] == ""
    assert "research_complete" in components["OutreachState"]["properties"]["current_step"]["enum"]
