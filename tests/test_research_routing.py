"""A new research request must not continue a previous email task."""
import asyncio
from contextlib import asynccontextmanager
import json
import re

import httpx
import pytest

from app.agent.components.writer import validate_email_content
from app.connectors.search import PublicSearchTool, FakeSearchTool, ToolError
from app.domain.schemas import EmailDraft
from app.domain.workflow import SearchResult
from app.llm.client import ModelResponseError
from app.services.application import AgentService
from test_model_routing import completion, tool, router_for
from app.domain.conversation import ConversationAction


def test_latest_research_command_overrides_wrong_email_instruction(make_run_manager):
    requests = []
    replies = iter([
        completion({'action': 'reply', 'text': 'Who should I address the test email to?'}),
        tool('search', {'query': 'wearable hardware startup funding'}, 'search-1'),
        completion({'action': 'reply', 'text': 'I found a wearable startup. Its funding needs verification.', 'sources': ['https://example.com/company']}),
    ])
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=next(replies))
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            setup = make_run_manager(search=FakeSearchTool([SearchResult(title='Wearable startup', url='https://example.com/company', description='Wearable hardware company.')]))
            @asynccontextmanager
            async def factory(): yield router_for(http)
            setup.manager.client_factory = factory
            service = AgentService(setup.manager)
            service.store.put('chat:history:s', {'turns': [{'run_id': 'old', 'user': 'Draft a test email',
                'reply': 'Who should I address it to?', 'evidence': []}]})
            message = 'Find me 10 wearable hardware startups making necklaces or wristbands that have raised funding.'
            job = service.conversations.queue(message, 's', [], 'new')
            await service.execute_one()
            answer = service.store.get('chat:result:' + job['run_id'])
            assert 'wearable startup' in answer['text'] and 'test email' not in answer['text']
            assert setup.repository.run(job['run_id'])['search_calls'] == 1
            assert service.list_runs()['total'] == 0 and setup.gmail.calls == []
            assert requests[0]['input'][-1] == {'role': 'user', 'content': message}
            assert requests[1]['input'][-1] == {'role': 'user', 'content': message}
            assert requests[1]['tool_choice'] == 'required'
            assert [item['name'] for item in requests[1]['tools']] == ['search']
    asyncio.run(check())


def test_email_schema_allows_complete_multiline_text_under_full_match():
    pattern = EmailDraft.model_json_schema()['properties']['body']['pattern']
    body = 'Hi there,\n\nThis is a test email. Please ignore it.\n\nThanks!'
    assert re.fullmatch(pattern, body)
    assert not re.fullmatch(pattern, ' \n\t')
    assert EmailDraft(prospect_id='p', subject='Test', body=body).body == body


@pytest.mark.parametrize('body', ['T', 'I', '—', '...', '[body]', 'TODO'])
def test_fragments_and_placeholders_fail_before_gmail(body):
    with pytest.raises(ModelResponseError):
        validate_email_content(EmailDraft(prospect_id='p', subject='Test', body=body))


def test_keyless_search_is_bounded_and_keeps_public_sources():
    calls = []
    class Backend:
        def __init__(self, **kwargs): calls.append(kwargs)
        def text(self, query, **kwargs):
            calls.append({'query': query, **kwargs})
            return [{'title': 'Wearable startup', 'href': 'https://example.com', 'body': 'Public evidence'},
                    {'title': 'Private', 'href': 'http://127.0.0.1/private'},
                    {'title': 'Duplicate', 'href': 'https://example.com', 'body': ''}]
    results = asyncio.run(PublicSearchTool(count=3, timeout=5, factory=Backend).search('wearable hardware'))
    assert len(results) == 1 and results[0].url == 'https://example.com'
    assert calls == [{'timeout': 5}, {'query': 'wearable hardware', 'backend': 'duckduckgo', 'max_results': 3}]


def test_keyless_search_failure_is_safe_and_has_no_hidden_retries():
    calls = []
    class Backend:
        def __init__(self, **kwargs): pass
        def text(self, *args, **kwargs):
            calls.append(1)
            raise RuntimeError('PRIVATE PROVIDER RESPONSE')
    with pytest.raises(ToolError) as error:
        asyncio.run(PublicSearchTool(factory=Backend).search('startups'))
    assert 'PRIVATE' not in str(error.value) and calls == [1]


def test_provider_cannot_skip_a_required_reading_tool():
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
            httpx.Response(200, json=completion({'action': 'reply', 'text': 'Old email answer'})))) as http:
            router = router_for(http)
            with pytest.raises(ModelResponseError, match='requires a reading tool'):
                await router.generate_structured(instructions='Test', response_model=ConversationAction,
                    input_text=json.dumps({'message': 'Find wearable startups', 'tools_allowed': True,
                        'capabilities': {'search': True}, 'observations': []}))
    asyncio.run(check())


def test_gmail_rejects_fragment_without_a_write():
    from app.connectors.gmail.client import FakeGmailClient
    from app.domain.workflow import Sender, Recipient
    gmail = FakeGmailClient()
    with pytest.raises(ModelResponseError):
        asyncio.run(gmail.create_draft(Sender(email='owner@example.com'), Recipient(email='friend@example.com'),
            EmailDraft(prospect_id='p', subject='Test', body='T')))
    assert gmail.calls == []


def test_incomplete_model_body_is_not_cached_forever_on_explicit_retry(make_run_manager):
    from app.agent.context import ManagedModelClient
    setup = make_run_manager(responses=[
        {'prospect_id': 'p', 'subject': 'Test', 'body': 'T'},
        {'prospect_id': 'p', 'subject': 'Test', 'body': 'This is a complete test email. Please ignore it.'}])
    service = AgentService(setup.manager)
    job = service.conversations.queue('Test', 's', [], 'retry-check')
    async def check():
        managed = ManagedModelClient(setup.client, setup.repository, job['run_id'], setup.manager.settings.limits)
        kwargs = {'instructions': 'Write a test', 'input_text': '{}', 'response_model': EmailDraft}
        with pytest.raises(ModelResponseError): await managed.generate_structured(**kwargs)
        result = await managed.generate_structured(**kwargs)
        assert 'complete test email' in result.body
        assert setup.repository.run(job['run_id'])['model_calls'] == 2
        assert len(setup.client.calls) == 2
    asyncio.run(check())
