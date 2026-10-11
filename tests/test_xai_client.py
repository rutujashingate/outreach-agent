"""Exercise Grok requests and real app paths with a local fake HTTP server."""

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.connectors.telegram.bot import TelegramBot
from app.connectors.telegram.client import FakeTelegram
from app.domain.schemas import Qualification
from app.domain.workflow import ApprovalSubmission, WorkflowRequest
from app.llm.client import ModelProviderError, ModelRefusalError, ModelResponseError
from app.llm.xai_client import DEFAULT_XAI_MODEL, XAIModelClient
from app.main import create_app
from app.services.application import AgentService
from app.services.runs import ConfigurationError, real_model_client
from app.settings import Settings
from app.storage.events import events


def completion(content, *, status="completed"):
    return {"status": status, "output": [{"type": "message", "role": "assistant",
        "status": "completed", "content": [{"type": "output_text", "text": content}]}],
        "usage": {"input_tokens": 30, "output_tokens": 12, "total_tokens": 42}}


def test_xai_sends_bounded_private_structured_request_and_validates_reply(records):
    requests = []
    expected = records[Qualification]
    def handle(request):
        requests.append(request)
        result = completion(expected.model_dump_json())
        result['output'].insert(0, {'type': 'reasoning', 'summary': []})
        return httpx.Response(200, json=result)
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            client = XAIModelClient(model=DEFAULT_XAI_MODEL, api_key='test-only', http_client=http,
                                    max_output_tokens=800)
            result = await client.generate_structured(instructions='Assess this prospect.',
                input_text='Evidence', response_model=Qualification)
            assert result == expected
            assert client.last_usage == {'input_tokens': 30, 'output_tokens': 12, 'total_tokens': 42}
            await client.aclose()
            assert not http.is_closed  # Injected connections belong to the caller.
    asyncio.run(check())
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == 'https://api.x.ai/v1/responses'
    assert request.method == 'POST' and request.headers['Authorization'] == 'Bearer test-only'
    body = json.loads(request.content)
    assert body['model'] == DEFAULT_XAI_MODEL
    assert body['instructions'] == 'Assess this prospect.' and body['input'] == 'Evidence'
    assert body['reasoning'] == {'effort': 'none'} and body['max_output_tokens'] == 800
    assert body['store'] is False and body['stream'] is False and 'tools' not in body
    schema = body['text']['format']
    assert schema['type'] == 'json_schema' and schema['strict'] is True
    assert schema['schema']['properties']['score']['maximum'] == 100


@pytest.mark.parametrize('payload', [
    [], {}, {'output': None}, {'status': 'completed', 'output': [None]},
    {'status': 'completed', 'output': [{'type': 'function_call'}]},
    {'status': 'completed', 'output': []},
    completion(None), completion(''), completion('not JSON'), completion('{}'),
    completion('{"prospect_id":"p1","score":101,"qualified":true,"reasons":[]}'),
    completion('{"prospect_id":"p1","score":86,"qualified":true,"reasons":[],"extra":1}'),
    completion('{}', status='incomplete'), completion('{}', status='failed'),
])
def test_invalid_incomplete_or_unexpected_outputs_cannot_enter_workflow(payload):
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as http:
            client = XAIModelClient(model=DEFAULT_XAI_MODEL, api_key='test-only', http_client=http)
            with pytest.raises(ModelResponseError):
                await client.generate_structured(instructions='Assess', input_text='Evidence', response_model=Qualification)
    asyncio.run(check())


def test_refusal_and_invalid_json_never_expose_provider_content():
    refusal = completion('')
    refusal['output'][0]['content'] = [{'type': 'refusal', 'refusal': 'private-secret'}]
    replies = iter([httpx.Response(200, json=refusal), httpx.Response(200, text='private-secret')])
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: next(replies))) as http:
            client = XAIModelClient(model=DEFAULT_XAI_MODEL, api_key='test-only', http_client=http)
            for expected in [ModelRefusalError, ModelResponseError]:
                with pytest.raises(expected) as error:
                    await client.generate_structured(instructions='Assess', input_text='Evidence', response_model=Qualification)
                assert 'private-secret' not in str(error.value)
    asyncio.run(check())


def test_usage_is_reset_and_only_nonnegative_integer_counts_are_saved(records):
    replies = [completion(records[Qualification].model_dump_json()) for _ in range(3)]
    replies[1]['usage'] = {'input_tokens': -5, 'output_tokens': True, 'total_tokens': 'private-secret'}
    replies[2].pop('usage')
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=replies.pop(0)))) as http:
            client = XAIModelClient(model=DEFAULT_XAI_MODEL, api_key='test-only', http_client=http)
            for expected in [{'input_tokens': 30, 'output_tokens': 12, 'total_tokens': 42}, {}, {}]:
                await client.generate_structured(instructions='Assess', input_text='Evidence', response_model=Qualification)
                assert client.last_usage == expected
    asyncio.run(check())


def test_configuration_reads_only_xai_and_closes_its_owned_connection(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'unused-other-provider')
    monkeypatch.setenv('OPENAI_API_KEY', 'unused-other-provider')
    with pytest.raises(ValueError, match='XAI_API_KEY'):
        XAIModelClient.from_env()
    monkeypatch.setenv('XAI_API_KEY', 'test-only')
    monkeypatch.setenv('OUTREACH_MODEL_PROVIDER', 'xai')
    assert Settings.from_env().model_provider == 'xai'
    async def check():
        async with XAIModelClient.from_env() as client:
            assert client.model_name == DEFAULT_XAI_MODEL and client._reasoning_effort == 'none'
        assert client._http.is_closed
        monkeypatch.setenv('XAI_MODEL', 'another-supported-model')
        monkeypatch.setenv('XAI_REASONING_EFFORT', 'low')
        async with XAIModelClient.from_env() as custom:
            assert custom.model_name == 'another-supported-model' and custom._reasoning_effort == 'low'
    asyncio.run(check())


@pytest.mark.parametrize('changes', [
    {'model': ' '}, {'reasoning_effort': 'unbounded'},
    {'max_output_tokens': 0}, {'max_output_tokens': True},
])
def test_invalid_configuration_is_rejected_before_creating_connection(changes):
    with pytest.raises(ValueError):
        XAIModelClient(**{'model': DEFAULT_XAI_MODEL, 'api_key': 'test-only', **changes})


def test_saved_outreach_uses_xai_and_approval_needs_no_more_model_calls(make_run_manager, workflow_data, monkeypatch):
    settings = Settings(model_provider='xai', xai_task_routing=False, checkpoint_backend='memory')
    setup = make_run_manager(settings=settings)
    replies, requests, factories = iter(workflow_data.responses), [], []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=completion(json.dumps(next(replies))))
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            adapter = XAIModelClient(model=DEFAULT_XAI_MODEL, api_key='test-only', http_client=http)
            adapter.aclose = AsyncMock(wraps=adapter.aclose)
            def factory(**kwargs):
                factories.append(kwargs)
                return adapter
            monkeypatch.setattr('app.services.runs.XAIModelClient.from_env', factory)
            setup.manager.client_factory = lambda: real_model_client(settings)
            response = await setup.manager.start(workflow_data.request)
            assert response.awaiting_approval and len(requests) == 6
            model_events = [item for item in events(setup.repository, response.state.run_id) if item['event'] == 'model_end']
            assert len(model_events) == 6
            assert all(item['usage']['total_tokens'] == 42 and item['model'] == DEFAULT_XAI_MODEL for item in model_events)
            approval = response.state.approval_requests[0]
            response = await setup.manager.resume(response.state.run_id, ApprovalSubmission(decisions=[{
                'prospect_id': 'p1', 'version': approval.version, 'fingerprint': approval.fingerprint, 'action': 'approve'}]))
            assert response.state.outcomes['p1'].status == 'approved' and len(requests) == 6
            adapter.aclose.assert_awaited_once()
    asyncio.run(check())
    assert factories == [{'max_output_tokens': settings.limits.max_output_tokens, 'timeout': settings.limits.model_timeout}]


def test_missing_xai_key_does_not_fall_back_to_another_provider(make_run_manager, monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'unused-other-provider')
    monkeypatch.setenv('OPENAI_API_KEY', 'unused-other-provider')
    settings = Settings(model_provider='xai', xai_task_routing=False, checkpoint_backend='memory')
    setup = make_run_manager(settings=settings)
    setup.manager.client_factory = lambda: real_model_client(settings)
    with pytest.raises(ConfigurationError, match='XAI_API_KEY') as error:
        asyncio.run(setup.manager.start(WorkflowRequest(goal='Find research collaborators.')))
    assert setup.manager.get(error.value.run_id).state.current_step == 'failed'


def test_dashboard_checks_selected_key_without_exposing_it(make_run_manager, monkeypatch):
    setup = make_run_manager(settings=Settings(model_provider='xai', xai_task_routing=False, api_key='test-dashboard'))
    monkeypatch.setenv('OPENAI_API_KEY', 'unused-other-provider')
    monkeypatch.setenv('GROQ_API_KEY', 'unused-other-provider')
    with TestClient(create_app(manager=setup.manager, background=False), headers={'X-API-Key': 'test-dashboard'}) as browser:
        for key, expected in [('', False), ('   ', False), ('private-secret', True)]:
            monkeypatch.setenv('XAI_API_KEY', key)
            response = browser.get('/api/connectors')
            assert response.status_code == 200
            assert response.json()['model'] == {'provider': 'xai', 'configured': expected}
            assert 'private-secret' not in response.text and 'unused-other-provider' not in response.text


@pytest.mark.parametrize('status, reason, attempts', [
    (400, 'request_rejected', 1), (401, 'invalid_key', 1), (402, 'credits_required', 1),
    (403, 'xai_access_denied', 1), (404, 'model_unavailable', 1),
    (429, 'rate_limited', 1), (503, 'service_unavailable', 2),
])
def test_chat_worker_saves_safe_xai_failures_with_bounded_attempts(make_run_manager, monkeypatch, status, reason, attempts):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, text='private-secret')
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            adapter = XAIModelClient(model=DEFAULT_XAI_MODEL, api_key='private-secret', http_client=http)
            monkeypatch.setattr('app.services.runs.XAIModelClient.from_env', lambda **kwargs: adapter)
            settings = Settings(model_provider='xai', xai_task_routing=False, telegram_owner_id=123)
            setup = make_run_manager(settings=settings)
            setup.manager.client_factory = lambda: real_model_client(settings)
            service = AgentService(setup.manager)
            bot = TelegramBot(service, FakeTelegram())
            job = service.conversations.queue('Hello', 'session', [], 'one')
            assert await service.execute_one()
            record = setup.repository.run(job['run_id'])
            assert record['status'] == 'failed' and record['model_calls'] == attempts == len(requests)
            assert record['estimated_cost'] == pytest.approx(attempts * .05)
            failures = [item for item in events(setup.repository, job['run_id']) if item['event'] == 'model_failure']
            assert all(item['provider'] == 'xAI' and item['reason'] == reason and item['http_status'] == status for item in failures)
            assert record['error'] == failures[0]['message']
            assert record['error'] in service.store.jobs()[0]['error']
            while await bot.deliver_one():
                pass
            messages = [payload['text'] for method, payload in bot.client.calls if method == 'sendMessage']
            assert len(messages) == 1 and record['error'] in messages[0]
            assert 'private-secret' not in json.dumps([record, failures, messages, service.store.jobs()])
    asyncio.run(check())


def test_telegram_greeting_reaches_xai_and_returns_one_answer_without_outreach(make_run_manager, monkeypatch):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=completion(json.dumps({'action': 'reply', 'text': 'Hello! How can I help?'})))
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            adapter = XAIModelClient(model=DEFAULT_XAI_MODEL, api_key='test-only', http_client=http)
            monkeypatch.setattr('app.services.runs.XAIModelClient.from_env', lambda **kwargs: adapter)
            settings = Settings(model_provider='xai', xai_task_routing=False, telegram_owner_id=123)
            setup = make_run_manager(settings=settings)
            setup.manager.client_factory = lambda: real_model_client(settings)
            service = AgentService(setup.manager)
            bot = TelegramBot(service, FakeTelegram())
            update = {'update_id': 1, 'message': {'from': {'id': 123}, 'chat': {'id': 123, 'type': 'private'}, 'text': 'Hi'}}
            bot.store.accept_updates([update, update], 123)
            assert await bot.process_one() and await service.execute_one()
            assert not await bot.process_one() and not await service.execute_one()
            while await bot.deliver_one():
                pass
            messages = [payload['text'] for method, payload in bot.client.calls if method == 'sendMessage']
            assert messages.count('Hello! How can I help?') == 1 and len(requests) == 1
            assert service.list_runs()['items'] == [] and setup.gmail.calls == []
            assert service.overview()['stats']['model_calls'] == 1
    asyncio.run(check())


def test_connection_errors_are_safe_and_adapter_itself_does_not_retry():
    requests = []
    def handle(request):
        requests.append(request)
        raise httpx.ConnectError('private-secret', request=request)
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            adapter = XAIModelClient(model=DEFAULT_XAI_MODEL, api_key='test-only', http_client=http)
            with pytest.raises(ModelProviderError) as error:
                await adapter.generate_structured(instructions='Assess', input_text='Evidence', response_model=Qualification)
            assert error.value.reason == 'connection_failed' and error.value.retryable
            assert 'private-secret' not in error.value.public_message
    asyncio.run(check())
    assert len(requests) == 1
