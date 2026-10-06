"""Check structured model calls with preset data and an offline SDK transport.

The OpenAI tests use the real SDK's serialization and parsing, but MockTransport
supplies every HTTP response locally. No test contacts an external model.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel
import pytest

from app.models.client import (
    FakeModelClient,
    ModelClientError,
    ModelRefusalError,
    ModelResponseError,
    OpenAIModelClient,
    generate_structured,
)
from app.models.schemas import (
    EmailDraft,
    OutreachStrategy,
    Prospect,
    Qualification,
    ResearchResult,
    ReviewResult,
)

DOMAIN_MODELS = [Prospect, Qualification, OutreachStrategy, EmailDraft, ReviewResult]
PROMPT = {"instructions": "  Return the requested record.\n", "input_text": "Company research"}
QUALIFICATION = {"prospect_id": "p1", "score": 86, "qualified": True, "reasons": []}


def call(client, response_model=Qualification, **overrides):
    """Run the async entry point from an ordinary synchronous pytest test."""
    arguments = {**PROMPT, "response_model": response_model, **overrides}
    return asyncio.run(generate_structured(client=client, **arguments))


@pytest.mark.parametrize("model", DOMAIN_MODELS)
@pytest.mark.parametrize("representation", ["record", "dictionary", "json"])
def test_fake_returns_typed_records(model, representation, records, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    record = records[model]
    payload = {
        "record": record,
        "dictionary": record.model_dump(),
        "json": record.model_dump_json(),
    }[representation]
    client = FakeModelClient([payload])

    result = call(client, model)

    assert isinstance(result, model)
    assert result == record
    assert len(client.calls) == 1
    assert client.calls[0].instructions == PROMPT["instructions"]
    assert client.calls[0].input_text == PROMPT["input_text"]
    assert client.calls[0].response_model is model


def test_fake_snapshots_responses_and_returns_independent_records():
    payload = {**QUALIFICATION, "reasons": ["Original reason"]}
    client = FakeModelClient([payload, payload])
    payload["score"] = 1
    payload["reasons"].append("Changed after setup")

    first = call(client)
    first.reasons.append("Changed first result")
    second = call(client)

    assert first.score == second.score == 86
    assert second.reasons == ["Original reason"]
    assert first is not second


def test_fake_responses_are_consumed_in_order():
    client = FakeModelClient([QUALIFICATION, {**QUALIFICATION, "score": 90}])

    assert call(client).score == 86
    assert call(client).score == 90
    with pytest.raises(ModelClientError, match="no queued responses"):
        call(client)


@pytest.mark.parametrize(
    "payload",
    [
        {**QUALIFICATION, "score": 101},
        {**QUALIFICATION, "unexpected": "value"},
        "{invalid JSON",
        {"company_name": "Example AI"},
    ],
)
def test_shared_entry_point_rejects_invalid_output(payload):
    with pytest.raises(ModelResponseError, match="did not match Qualification"):
        call(FakeModelClient([payload]))


def test_existing_model_instances_are_revalidated():
    record = Qualification(**QUALIFICATION)
    record.score = 101

    with pytest.raises(ModelResponseError):
        call(FakeModelClient([record]))


def test_an_injected_mock_can_replace_the_client():
    mock = AsyncMock(return_value=QUALIFICATION)
    client = SimpleNamespace(generate_structured=mock)

    assert call(client).score == 86
    mock.assert_awaited_once_with(**PROMPT, response_model=Qualification)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"instructions": " "}, ValueError),
        ({"input_text": "\n"}, ValueError),
        ({"instructions": None}, TypeError),
        ({"input_text": 42}, TypeError),
        ({"response_model": dict}, TypeError),
        ({"response_model": BaseModel}, TypeError),
        ({"response_model": Qualification(**QUALIFICATION)}, TypeError),
    ],
)
def test_invalid_arguments_stop_before_the_client(overrides, error):
    client = FakeModelClient([QUALIFICATION])

    with pytest.raises(error):
        call(client, **overrides)
    assert client.calls == []


def response_body(text=None, *, status="completed", refusal=None):
    """Construct a local Responses API reply for the SDK to parse."""
    content = []
    if text is not None:
        content = [{"type": "output_text", "text": text, "annotations": []}]
    if refusal is not None:
        content = [{"type": "refusal", "refusal": refusal}]
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "status": status,
        "model": "test-model",
        "error": None,
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "output": [{
            "id": "msg_test", "type": "message", "role": "assistant",
            "status": "completed", "content": content,
        }] if content else [],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
    }


def call_openai(body, *, model=Qualification, status_code=200, requests=None):
    """All SDK requests are intercepted; even error replies are local."""
    async def run():
        def handler(request):
            if requests is not None:
                requests.append(json.loads(request.content))
            return httpx.Response(status_code, json=body)

        async with AsyncOpenAI(
            api_key="test-key", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ) as sdk:
            client = OpenAIModelClient(model="test-model", sdk_client=sdk)
            return await generate_structured(client=client, response_model=model, **PROMPT)

    return asyncio.run(run())


@pytest.mark.parametrize("model", DOMAIN_MODELS)
def test_openai_sdk_parses_each_domain_model_offline(model, records):
    requests = []

    result = call_openai(response_body(records[model].model_dump_json()), model=model, requests=requests)

    assert result == records[model]
    assert len(requests) == 1
    request = requests[0]
    assert request["model"] == "test-model"
    assert request["instructions"] == PROMPT["instructions"]
    assert request["input"] == PROMPT["input_text"]
    assert request["store"] is False
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True


def test_openai_refusal_is_an_explicit_error():
    with pytest.raises(ModelRefusalError, match="Cannot provide this output"):
        call_openai(response_body(refusal="Cannot provide this output"))


def test_openai_sdk_parses_research_batch_offline(records):
    batch = ResearchResult(prospects=[records[Prospect]])

    result = call_openai(response_body(batch.model_dump_json()), model=ResearchResult)

    assert result == batch
    assert isinstance(result.prospects[0], Prospect)


@pytest.mark.parametrize("status", ["completed", "incomplete", "failed"])
def test_missing_or_unfinished_openai_output_is_rejected(status):
    with pytest.raises(ModelResponseError):
        call_openai(response_body(status=status))


@pytest.mark.parametrize("text", ["{invalid JSON", json.dumps({**QUALIFICATION, "score": 101})])
def test_invalid_openai_structured_output_is_rejected(text):
    with pytest.raises(ModelResponseError):
        call_openai(response_body(text))


@pytest.mark.parametrize("status", [401, 429, 500])
def test_openai_provider_errors_are_reported(status):
    body = {"error": {"message": "Simulated provider error", "type": "api_error"}}

    with pytest.raises(ModelClientError, match="OpenAI model request failed") as failure:
        call_openai(body, status_code=status)
    assert failure.value.__cause__ is not None


def test_real_client_requires_explicit_configuration(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_MODEL"):
        OpenAIModelClient.from_env()
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIModelClient.from_env()


def test_owned_sdk_is_closed_after_context(monkeypatch):
    sdk = SimpleNamespace(close=AsyncMock())
    factory = Mock(return_value=sdk)
    monkeypatch.setattr("app.models.client.AsyncOpenAI", factory)
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    async def run():
        async with OpenAIModelClient.from_env():
            pass

    asyncio.run(run())
    factory.assert_called_once_with(api_key="test-key")
    sdk.close.assert_awaited_once()


def test_injected_sdk_is_left_for_its_owner_to_close():
    sdk = SimpleNamespace(close=AsyncMock())

    async def run():
        async with OpenAIModelClient(model="test-model", sdk_client=sdk):
            pass

    asyncio.run(run())
    sdk.close.assert_not_called()
