"""Check role selection and real Responses payloads without paid API calls."""
import asyncio
from contextlib import asynccontextmanager
import json

import httpx
import pytest

from app.connectors.browser.client import FakeBrowser
from app.domain.browser import PageEvidence
from app.domain.conversation import ConversationAction
from app.llm.client import ModelResponseError
from app.llm.xai_client import XAIModelClient
from app.llm.xai_routing import XAITaskRouter, configured_models
from app.services.application import AgentService
from app.services.runs import real_model_client
from app.settings import Settings
from app.storage.events import events


def completion(data):
    return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
        'status': 'completed', 'content': [{'type': 'output_text', 'text': json.dumps(data)}]}],
        'usage': {'input_tokens': 50, 'output_tokens': 10, 'total_tokens': 60}}


def tool(name, arguments, call_id='call-1'):
    return {'status': 'completed', 'output': [{'type': 'function_call', 'name': name,
        'arguments': json.dumps(arguments), 'call_id': call_id, 'status': 'completed'}]}


def router_for(http):
    return XAITaskRouter(clients={role: XAIModelClient(model=model, api_key='test-key',
        http_client=http, reasoning_effort={'instruction': 'none', 'reasoning': None, 'research': 'low'}[role])
        for role, model in configured_models().items()})


def test_native_tools_research_and_results_flow_through_the_real_chat_graph(make_run_manager, monkeypatch):
    requests = []
    replies = iter([
        completion({'action': 'read_page', 'url': 'https://example.com'}),
        tool('read_page', {'url': 'https://example.com'}),
        tool('research', {'query': 'Explain this product'}, 'call-2'),
        completion({'summary': 'Example makes observability tools.', 'sources': ['https://example.com']}),
        completion({'action': 'reply', 'text': 'Example makes observability tools.', 'sources': ['https://example.com']}),
    ])
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=next(replies))
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            router = router_for(http)
            monkeypatch.setenv('XAI_API_KEY', 'test-key')
            monkeypatch.setattr('app.services.runs.XAITaskRouter', lambda **kwargs: router)
            setup = make_run_manager(settings=Settings(model_provider='xai'), responses=[])
            setup.manager.browser = FakeBrowser({'https://example.com': PageEvidence(
                url='https://example.com', text='Example makes observability tools.')})
            setup.manager.client_factory = lambda: real_model_client(setup.manager.settings)
            service = AgentService(setup.manager)
            job = service.conversations.queue('Research https://example.com', 's', [], 'one')
            await service.execute_one()
            assert setup.repository.run(job['run_id'])['status'] == 'completed', service.store.jobs()
            assert setup.repository.run(job['run_id'])['model_calls'] == 5
            assert setup.gmail.calls == []
            saved = service.store.get('chat:result:' + job['run_id'])
            assert 'https://example.com' in saved['text']
            logged = events(setup.repository, job['run_id'])
            assert [e['role'] for e in logged if e['event'] == 'model_end'] == [
                'instruction', 'reasoning', 'reasoning', 'research', 'reasoning']
            assert len([e for e in logged if e['event'] == 'tool_start']) == 2
    asyncio.run(check())
    models = configured_models()
    assert [body['model'] for body in requests] == [models[r] for r in ['instruction','reasoning','reasoning','research','reasoning']]
    assert requests[0]['reasoning'] == {'effort': 'none'}
    assert 'reasoning' not in requests[1]
    assert requests[3]['reasoning'] == {'effort': 'low'} and 'tools' not in requests[3]
    assert all(body['store'] is False for body in requests)
    assert requests[1]['parallel_tool_calls'] is False
    pair = requests[2]['input'][-2:]
    assert pair[0]['type'] == 'function_call' and pair[1]['type'] == 'function_call_output'
    assert pair[0]['call_id'] == pair[1]['call_id'] == 'call-1'
    assert 'observability' in pair[1]['output']
    assert {t['name'] for t in requests[1]['tools']} == {'read_page'}
    assert requests[1]['tool_choice'] == 'required'


def test_outreach_tasks_choose_all_three_roles(make_run_manager, workflow_data):
    requests, responses = [], iter(workflow_data.responses)
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=completion(next(responses)))
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            @asynccontextmanager
            async def factory():
                yield router_for(http)
            setup = make_run_manager()
            setup.manager.client_factory = factory
            result = await setup.manager.start(workflow_data.request)
            assert result.awaiting_approval
    asyncio.run(check())
    models = configured_models()
    assert [body['model'] for body in requests] == [models[r] for r in [
        'instruction', 'research', 'reasoning', 'reasoning', 'instruction', 'reasoning']]
    assert all('tools' not in body for body in requests)


@pytest.mark.parametrize('payload', [
    tool('send_email', {'to': 'someone@example.com'}),
    tool('search', {'query': 'query'}),  # Search isn't configured in this test.
    tool('read_page', {'url': 'https://example.com', 'shell': 'run something'}),
    tool('read_page', {'url': 123}),
    tool('read_page', {'url': ''}),
    tool('read_page', {'url': 'x' * 2049}),
    tool('read_page', {'url': 'https://example.com'}, ''),
    {'status': 'completed', 'output': [*tool('run_status', {'run_id': ''})['output']] * 2},
    completion({'action': 'read_page', 'url': 'https://example.com'}),
])
def test_unavailable_malformed_and_multiple_tool_calls_are_rejected(payload):
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as http:
            with pytest.raises(ModelResponseError):
                await router_for(http).generate_structured(instructions='Choose a tool',
                    input_text=json.dumps({'tools_allowed': True, 'capabilities': {'browser': True}}),
                    response_model=ConversationAction)
    asyncio.run(check())


def test_exhausted_tool_budget_exposes_no_functions():
    bodies = []
    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=tool('run_status', {'run_id': ''}))
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            with pytest.raises(ModelResponseError):
                await router_for(http).generate_structured(instructions='Answer now',
                    input_text=json.dumps({'tools_allowed': False}), response_model=ConversationAction)
    asyncio.run(check())
    assert 'tools' not in bodies[0]


def test_configured_role_names_can_be_changed_without_changing_keys(monkeypatch):
    monkeypatch.setenv('XAI_INSTRUCTION_MODEL', 'instruction-version')
    monkeypatch.setenv('XAI_REASONING_MODEL', 'reasoning-version')
    monkeypatch.setenv('XAI_RESEARCH_MODEL', 'research-version')
    assert configured_models() == {'instruction': 'instruction-version', 'reasoning': 'reasoning-version', 'research': 'research-version'}
