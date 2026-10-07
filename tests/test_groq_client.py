"""Check Groq requests and provider selection without calling any live service."""

import asyncio
from contextlib import asynccontextmanager
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.llm.client import FakeModelClient, ModelClientError, ModelRefusalError, ModelResponseError, generate_structured
from app.llm.groq_client import DEFAULT_GROQ_MODEL, GroqModelClient
from app.domain.schemas import Qualification
from app.services.runs import real_model_client
from app.settings import Settings


def completion(content, *, finish_reason="stop", refusal=None):
    return {"choices": [{"finish_reason": finish_reason, "message": {
        "content": content, "refusal": refusal,
    }}], "usage": {"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42}}


def test_groq_requests_schema_and_returns_a_validated_record(records):
    expected = records[Qualification]
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=completion(expected.model_dump_json()))
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            client = GroqModelClient(model=DEFAULT_GROQ_MODEL, api_key="test-only-groq-key",
                                     http_client=http, max_output_tokens=4000)
            result = await generate_structured(instructions="Assess this prospect.", input_text="Evidence",
                                              response_model=Qualification, client=client)
            assert result == expected
            assert client.last_usage == {"input_tokens": 30, "output_tokens": 12, "total_tokens": 42}
            await client.aclose()
            assert not http.is_closed  # The injected connection belongs to this test.
    asyncio.run(exercise())
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.method == "POST" and request.headers["Authorization"] == "Bearer test-only-groq-key"
    body = json.loads(request.content)
    assert body["model"] == DEFAULT_GROQ_MODEL and body["max_completion_tokens"] == 4000
    assert body["messages"][0]["content"] == "Assess this prospect."
    schema = body["response_format"]["json_schema"]
    assert body["response_format"]["type"] == "json_schema" and schema["strict"] is False
    assert schema["schema"]["properties"]["score"]["maximum"] == 100


@pytest.mark.parametrize("payload", [
    [], {}, {"choices": []}, {"choices": [None]},
    {"choices": [{"message": None}]},
    completion(None), completion(""), completion("not JSON"),
    completion('{"prospect_id":"p1","score":101,"qualified":true,"reasons":[]}'),
    completion('{"prospect_id":"p1","score":86,"qualified":true,"reasons":[],"extra":1}'),
    completion('{}', finish_reason="length"),
])
def test_groq_invalid_or_truncated_outputs_stop_before_use(payload):
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as http:
            client = GroqModelClient(model=DEFAULT_GROQ_MODEL, api_key="test-only", http_client=http)
            with pytest.raises(ModelResponseError):
                await client.generate_structured(instructions="Assess", input_text="Evidence", response_model=Qualification)
    asyncio.run(exercise())


@pytest.mark.parametrize("payload", [completion(None, refusal="Private provider text"), completion(None, finish_reason="content_filter")])
def test_groq_refusals_are_detected_without_returning_private_provider_text(payload):
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as http:
            client = GroqModelClient(model=DEFAULT_GROQ_MODEL, api_key="test-only", http_client=http)
            with pytest.raises(ModelRefusalError) as failure:
                await client.generate_structured(instructions="Assess", input_text="Evidence", response_model=Qualification)
            assert "Private" not in str(failure.value)
    asyncio.run(exercise())


@pytest.mark.parametrize("status", [401, 429, 500, "timeout"])
def test_groq_adapter_makes_one_attempt_and_hides_credentials(status):
    requests = []
    def handle(request):
        requests.append(request)
        if status == "timeout":
            raise httpx.ReadTimeout("Private transport text", request=request)
        return httpx.Response(status, json={"error": "Private provider text"})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            client = GroqModelClient(model=DEFAULT_GROQ_MODEL, api_key="test-only-secret", http_client=http)
            with pytest.raises(ModelClientError) as failure:
                await client.generate_structured(instructions="Assess", input_text="Evidence", response_model=Qualification)
            assert str(failure.value) == "Groq model request failed."
    asyncio.run(exercise())
    assert len(requests) == 1


def test_groq_configuration_requires_its_key_and_uses_the_default_model(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        GroqModelClient.from_env()
    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    async def exercise():
        async with GroqModelClient.from_env() as client:
            assert client.model_name == DEFAULT_GROQ_MODEL
        assert client._http.is_closed
    asyncio.run(exercise())


def test_settings_select_groq_without_openai_configuration(monkeypatch):
    monkeypatch.setenv("OUTREACH_MODEL_PROVIDER", "groq")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert Settings.from_env().model_provider == "groq"
    monkeypatch.setenv("OUTREACH_MODEL_PROVIDER", "unsupported")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_complete_run_uses_groq_and_resumes_without_another_model_call(make_run_manager, workflow_data, monkeypatch):
    settings = Settings(model_provider="groq", checkpoint_backend="memory")
    setup = make_run_manager(settings=settings)
    client = FakeModelClient(workflow_data.responses)
    client.last_usage = {"total_tokens": 42}
    client.model_name = DEFAULT_GROQ_MODEL
    client.aclose = AsyncMock()
    factory_calls = []
    def groq_factory(**kwargs):
        factory_calls.append(kwargs)
        return client
    monkeypatch.setattr("app.services.runs.GroqModelClient.from_env", groq_factory)
    setup.manager.client_factory = lambda: real_model_client(settings)
    async def exercise():
        response = await setup.manager.start(workflow_data.request)
        assert response.awaiting_approval and len(client.calls) == 6
        approval = response.state.approval_requests[0]
        from app.domain.workflow import ApprovalSubmission
        response = await setup.manager.resume(response.state.run_id, ApprovalSubmission(decisions=[{
            "prospect_id": "p1", "version": approval.version, "fingerprint": approval.fingerprint, "action": "approve",
        }]))
        assert response.state.outcomes["p1"].status == "approved" and len(client.calls) == 6
    asyncio.run(exercise())
    assert factory_calls == [{"max_output_tokens": settings.limits.max_output_tokens, "timeout": settings.limits.model_timeout}]
    client.aclose.assert_awaited_once()


def test_missing_groq_configuration_returns_saved_run_identifier(make_run_manager, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    settings = Settings(model_provider="groq", checkpoint_backend="memory")
    setup = make_run_manager(settings=settings)
    setup.manager.client_factory = lambda: real_model_client(settings)
    with TestClient(create_app(manager=setup.manager)) as api:
        response = api.post('/runs', json={"goal": "Find research collaborators."})
        assert response.status_code == 503 and "GROQ_API_KEY" in response.json()["detail"]
        saved = api.get('/runs/'+response.json()['run_id'])
        assert saved.status_code == 200 and saved.json()['state']['current_step'] == "failed"


def test_live_evaluation_selects_groq_with_locally_supplied_responses(monkeypatch):
    # Exercise --live's provider selection while keeping every response local.
    from pathlib import Path
    from evals.run import evaluate, scripted_client
    import evals.run as runner
    cases = json.loads(Path(runner.__file__).with_name('cases.json').read_text())
    clients = [scripted_client(case) for case in cases]
    for client in clients:
        client.last_usage = {}
        client.model_name = DEFAULT_GROQ_MODEL
        client.aclose = AsyncMock()
    waiting = iter(clients)
    monkeypatch.setenv('OUTREACH_MODEL_PROVIDER', 'groq')
    monkeypatch.setattr('app.services.runs.GroqModelClient.from_env', lambda **kwargs: next(waiting))
    report = asyncio.run(evaluate(live=True))
    assert report['mode'] == 'live_model' and len(report['results']) == 4
    assert all(len(client.calls) == 6 for client in clients)
    for client in clients:
        client.aclose.assert_awaited_once()
