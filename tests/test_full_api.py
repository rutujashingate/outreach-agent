"""Exercise validation, saved runs, and approval through the actual HTTP routes."""

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.settings import Settings
from app.security.limits import Limits


def decision_body(response, action="approve"):
    request = response["state"]["approval_requests"][0]
    return {"decisions": [{"prospect_id": request["prospect"]["id"], "version": request["version"],
                           "fingerprint": request["fingerprint"], "action": action}]}


def test_full_api_creates_inspects_and_resumes_same_run(make_run_manager, workflow_data):
    setup = make_run_manager()
    with TestClient(create_app(manager=setup.manager)) as client:
        created = client.post("/runs", json=workflow_data.request.model_dump(mode="json"))
        assert created.status_code == 201
        initial = created.json()
        run_id = initial["state"]["run_id"]
        assert initial["awaiting_approval"] is True
        assert client.get(f"/runs/{run_id}").json() == initial
        resumed = client.post(f"/runs/{run_id}/decisions", json=decision_body(initial))
        assert resumed.status_code == 200
        assert resumed.json()["state"]["run_id"] == run_id
        assert resumed.json()["state"]["outcomes"]["p1"]["status"] == "approved"
        assert resumed.json()["awaiting_approval"] is False
        assert client.post(f"/runs/{run_id}/decisions", json=decision_body(initial)).status_code == 409
        assert client.get(f"/runs/{run_id}/events").status_code == 200
        assert client.get("/contacts/contact@example.com").json()["history"][0]["kind"] == "approved"


@pytest.mark.parametrize("updates", [
    {"goal": " "}, {"unknown": True}, {"use_search": "true"},
    {"recipients": {"p1": {"email": "invalid"}}}, {"gmail_action": "automatic"},
    {"sender": {"name": "User\nBcc: other@example.com", "email": "user@example.com"}},
])
def test_invalid_full_request_stops_before_model(make_run_manager, workflow_data, updates):
    setup = make_run_manager()
    payload = {**workflow_data.request.model_dump(mode="json"), **updates}
    with TestClient(create_app(manager=setup.manager)) as client:
        assert client.post("/runs", json=payload).status_code == 422
    assert setup.client.calls == setup.gmail.calls == []


@pytest.mark.parametrize("change", ["version", "fingerprint", "missing", "duplicate"])
def test_stale_or_incomplete_approval_does_not_resume(make_run_manager, workflow_data, change):
    setup = make_run_manager()
    with TestClient(create_app(manager=setup.manager)) as client:
        initial = client.post("/runs", json=workflow_data.request.model_dump(mode="json")).json()
        run_id = initial["state"]["run_id"]
        body = decision_body(initial)
        if change == "version":
            body["decisions"][0]["version"] += 1
        elif change == "fingerprint":
            body["decisions"][0]["fingerprint"] = "another-message"
        elif change == "missing":
            body["decisions"] = []
        else:
            body["decisions"] *= 2
        assert client.post(f"/runs/{run_id}/decisions", json=body).status_code == 422
        assert client.get(f"/runs/{run_id}").json()["awaiting_approval"] is True
        assert len(setup.client.calls) == 6


def test_unknown_and_malformed_run_identifiers(make_run_manager):
    setup = make_run_manager()
    with TestClient(create_app(manager=setup.manager)) as client:
        assert client.get("/runs/" + "f" * 32).status_code == 404
        assert client.get("/runs/not-an-id").status_code == 422


def test_api_key_protects_runs_and_memory_and_legacy_endpoint(make_run_manager, workflow_data):
    setup = make_run_manager(settings=Settings(checkpoint_backend="memory", api_key="test-only-key"))
    with TestClient(create_app(manager=setup.manager)) as client:
        for path in ("/runs/" + "f" * 32, "/contacts/contact@example.com"):
            assert client.get(path).status_code == 401
        assert client.post("/outreach", json={"goal": "A goal"}).status_code == 401
        assert client.post("/runs", json=workflow_data.request.model_dump(mode="json"),
                           headers={"X-API-Key": "test-only-key"}).status_code == 201


def test_request_limit_is_enforced(make_run_manager):
    setup = make_run_manager(settings=Settings(checkpoint_backend="memory", limits=Limits(max_requests_per_minute=2)))
    with TestClient(create_app(manager=setup.manager)) as client:
        assert client.get("/contacts/contact@example.com").status_code == 200
        assert client.get("/contacts/contact@example.com").status_code == 200
        assert client.get("/contacts/contact@example.com").status_code == 429


def test_reply_api_blocks_contact_without_external_services(make_run_manager):
    setup = make_run_manager(responses=[])
    with TestClient(create_app(manager=setup.manager)) as client:
        response = client.post("/replies", json={"contact_email": "contact@example.com", "source": "message-1", "body": "Do not contact me."})
        assert response.status_code == 200
        assert response.json()["classification"]["category"] == "opt_out"
        contact = client.get("/contacts/contact@example.com").json()
        assert contact["contact"]["opted_out"] is True
        assert client.put("/contacts/contact@example.com/policy", json={"source": "human:1", "evidence_quote": "Conversation ended", "active_conversation": False}).status_code == 200
        assert client.get("/contacts/contact@example.com").json()["contact"]["opted_out"] is True
    assert setup.client.calls == setup.gmail.calls == []


def test_openapi_documents_new_workflow_and_decisions(make_run_manager):
    setup = make_run_manager()
    with TestClient(create_app(manager=setup.manager)) as client:
        spec = client.get("/openapi.json").json()
        assert spec["paths"]["/runs"]["post"]["responses"]["201"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/RunResponse"}
        assert "/runs/{run_id}/decisions" in spec["paths"]
        assert "/replies" in spec["paths"]
        assert client.get("/docs").status_code == 200


def test_failed_invocation_returns_saved_identifier_for_inspection(make_run_manager, workflow_data):
    setup = make_run_manager(settings=Settings(checkpoint_backend="memory", limits=Limits(max_model_calls=1)))
    with TestClient(create_app(manager=setup.manager)) as client:
        response = client.post("/runs", json=workflow_data.request.model_dump(mode="json"))
        assert response.status_code == 429
        run_id = response.json()["run_id"]
        saved = client.get(f"/runs/{run_id}")
        assert saved.status_code == 200
        assert saved.json()["state"]["current_step"] == "failed"
