"""Normal Telegram messages use the real conversation graph and fake providers."""
import asyncio
from contextlib import asynccontextmanager
import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.browser.client import FakeBrowser
from app.connectors.search import FakeSearchTool
from app.connectors.telegram.bot import TelegramBot
from app.connectors.telegram.client import FakeTelegram
from app.domain.browser import PageEvidence
from app.domain.workflow import SearchResult
from app.llm.client import FakeModelClient, ModelResponseError
from app.llm.groq_client import DEFAULT_GROQ_MODEL, GroqModelClient
from app.services.application import AgentService
from app.services.limits import Limits
from app.services.runs import RunConflict
from app.settings import Settings
from app.storage.control import JobRow, OutboxRow
from app.storage.database import create_database
from app.storage.repository import Repository


def incoming(number, text, owner=123):
    return {'update_id': number, 'message': {'from': {'id': owner},
            'chat': {'id': owner, 'type': 'private'}, 'text': text}}


async def dispatch(bot, number, text):
    bot.store.accept_updates([incoming(number, text)], bot.owner)
    assert await bot.process_one()


async def deliver(bot):
    while await bot.deliver_one():
        pass
    return [p['text'] for method, p in bot.client.calls if method == 'sendMessage']


def result(service, job):
    saved = service.store.get('chat:result:' + job['run_id'])
    assert saved is not None, service.store.jobs()
    return saved


def test_plain_messages_and_followups_survive_database_reopen_without_new(make_run_manager, tmp_path):
    database = f'sqlite:///{tmp_path / "chat.sqlite3"}'
    repository = Repository(create_database(database))
    setup = make_run_manager(repository=repository, settings=Settings(telegram_owner_id=123), responses=[
        {'action': 'reply', 'text': 'Hello! What would you like to work on?'},
        {'action': 'reply', 'text': 'Yes, we can discuss API observability.'}])
    async def check():
        service = AgentService(setup.manager)
        bot = TelegramBot(service, FakeTelegram())
        await dispatch(bot, 1, 'Hi, I work on API observability.')
        assert setup.client.calls == []  # The Telegram handler never calls a model.
        await service.execute_one()
        assert service.list_runs()['items'] == []  # A greeting is not outreach.
        repository.engine.dispose()
        setup.manager.repository = Repository(create_database(database))
        fresh = AgentService(setup.manager)
        bot = TelegramBot(fresh, FakeTelegram())
        await dispatch(bot, 2, 'Can we discuss that?')
        await fresh.execute_one()
        prompt = json.loads(setup.client.calls[-1].input_text)
        assert prompt['history'][0]['user'] == 'Hi, I work on API observability.'
        assert 'Hello!' in prompt['history'][0]['assistant']
        assert any('discuss API observability' in text for text in await deliver(bot))
        assert setup.gmail.calls == []
        assert fresh.overview()['stats']['model_calls'] == 2
        assert fresh.overview()['stats']['runs'] == 0
    try:
        asyncio.run(check())
    finally:
        setup.manager.repository.engine.dispose()


def test_queue_pause_duplicate_updates_and_multiple_messages_keep_order(make_run_manager):
    setup = make_run_manager(settings=Settings(telegram_owner_id=123), responses=[
        {'action': 'reply', 'text': 'First answer.'}, {'action': 'reply', 'text': 'Second answer.'}])
    service = AgentService(setup.manager)
    bot = TelegramBot(service, FakeTelegram())
    async def check():
        service.store.put('queue', {'paused': True})
        await dispatch(bot, 1, 'First question')
        bot.store.accept_updates([incoming(1, 'First question'), incoming(2, 'Follow-up')], 123)
        assert await bot.process_one()
        assert not await bot.process_one()
        assert len(service.store.jobs()) == 2
        assert not await service.execute_one()
        await dispatch(bot, 3, '/help')  # Commands remain responsive while paused.
        service.store.put('queue', {'paused': False})
        assert await service.execute_one() and await service.execute_one()
        assert not await service.execute_one()
        assert json.loads(setup.client.calls[1].input_text)['history'][0]['assistant'] == 'First answer.'
        assert sum(text == 'First answer.' for text in await deliver(bot)) == 1
    asyncio.run(check())


def test_new_is_optional_reset_and_old_wizards_can_be_left(make_run_manager):
    setup = make_run_manager(settings=Settings(telegram_owner_id=123), responses=[
        {'action': 'reply', 'text': 'Hello'}, {'action': 'reply', 'text': 'Fresh start'}])
    service = AgentService(setup.manager)
    bot = TelegramBot(service, FakeTelegram())
    async def check():
        # An old deployment's implicit wizard must not trap the first new message.
        service.store.put('telegram_conversation', {'stage': 'background', 'id': 'old', 'request': {}})
        await dispatch(bot, 1, 'Hello')
        await service.execute_one()
        await dispatch(bot, 2, '/new')
        await dispatch(bot, 3, 'A different topic')
        await service.execute_one()
        assert json.loads(setup.client.calls[-1].input_text)['history'] == []
        await dispatch(bot, 4, '/guided')
        assert service.store.get('telegram_conversation')['mode'] == 'guided'
        await dispatch(bot, 5, '/start')
        assert service.store.get('telegram_conversation')['mode'] == 'chat'
        await dispatch(bot, 6, '/guided')
        await dispatch(bot, 7, '/chat')
        assert service.store.get('telegram_conversation')['stage'] == 'chat'
    asyncio.run(check())


def test_update_replay_between_enqueue_and_ack_reuses_history_identity(make_run_manager, monkeypatch):
    setup = make_run_manager(settings=Settings(telegram_owner_id=123), responses=[{'action': 'reply', 'text': 'Hi'}])
    service = AgentService(setup.manager)
    bot = TelegramBot(service, FakeTelegram())
    finish = service.store.finish_update
    def crash(*args):
        raise RuntimeError('Simulated crash after enqueue')
    async def check():
        service.store.accept_updates([incoming(1, 'Hello')], 123)
        monkeypatch.setattr(service.store, 'finish_update', crash)
        with pytest.raises(RuntimeError):
            await bot.process_one()
        job = service.store.jobs()[0]
        expected = service.conversations.retry_payload(job['run_id'])['session_id']
        monkeypatch.setattr(service.store, 'finish_update', finish)
        assert await TelegramBot(service, FakeTelegram()).process_one()
        assert len(service.store.jobs()) == 1
        assert service.store.get('telegram_conversation')['id'] == expected
    asyncio.run(check())


def test_file_caption_is_a_question_and_followup_has_cited_evidence(make_run_manager, tmp_path):
    setup = make_run_manager(settings=Settings(data_dir=tmp_path, telegram_owner_id=123), responses=[])
    service = AgentService(setup.manager)
    client = FakeTelegram()
    client.files['notes'] = b'The evaluation found a 23 percent reduction in latency.'
    saved = service.documents.save('notes.txt', client.files['notes'])
    document_id = saved['document']['id']
    setup.client._responses.extend([
        {'action': 'read_file', 'document_id': document_id},
        {'action': 'reply', 'text': 'Latency fell by 23 percent.', 'sources': [f'document:{document_id}#page=1']},
        {'action': 'reply', 'text': 'That number is the measured latency reduction.'}])
    bot = TelegramBot(service, client)
    async def check():
        update = incoming(1, '')
        update['message'].update(document={'file_id': 'notes', 'file_name': 'notes.txt'}, caption='Summarize this file')
        service.store.accept_updates([update], 123)
        assert await bot.process_one()
        assert await service.execute_one()  # Real local text extraction.
        assert await service.execute_one()  # Model reads that saved text.
        prompt = json.loads(setup.client.calls[1].input_text)
        assert '23 percent' in prompt['observations'][0]['content']
        texts = await deliver(bot)
        assert any('notes.txt, page 1' in text for text in texts)
        assert all(document_id not in text for text in texts)
        await dispatch(bot, 2, 'What does that number mean?')
        await service.execute_one()
        assert '23 percent' in json.dumps(json.loads(setup.client.calls[2].input_text)['previous_evidence'])
        assert service.list_runs()['items'] == []
    asyncio.run(check())


def test_unattached_file_cannot_be_read(make_run_manager, tmp_path):
    setup = make_run_manager(settings=Settings(data_dir=tmp_path), responses=[])
    service = AgentService(setup.manager)
    saved = service.documents.save('private.txt', b'PRIVATE FILE CONTENT')
    setup.client._responses.extend([{'action': 'read_file', 'document_id': saved['document']['id']},
                                    {'action': 'reply', 'text': 'Please attach the file.'}])
    async def check():
        await service.execute_one()
        job = service.conversations.queue('Read a file', 'session', [], 'one')
        await service.execute_one()
        assert 'Please attach' in result(service, job)['text']
        assert 'PRIVATE FILE CONTENT' not in setup.client.calls[-1].input_text
        assert 'error' in json.loads(setup.client.calls[-1].input_text)['observations'][0]
    asyncio.run(check())


def test_background_file_can_be_discussed_without_becoming_prospect_evidence(make_run_manager, tmp_path):
    setup = make_run_manager(settings=Settings(data_dir=tmp_path), responses=[])
    service = AgentService(setup.manager)
    saved = service.documents.save('resume.txt', b'My private experience building observability tools.')
    document_id = saved['document']['id']
    setup.client._responses.extend([
        {'action': 'read_file', 'document_id': document_id},
        {'action': 'reply', 'text': 'Your resume describes observability experience.'},
        {'action': 'outreach', 'request': {'goal': 'Find relevant researchers'}}])
    async def check():
        await service.execute_one()
        attachments = [{'document_id': document_id, 'purpose': 'background'}]
        service.conversations.queue('Explain my resume', 'session', attachments, 'one')
        await service.execute_one()
        job = service.conversations.queue('Prepare researcher outreach', 'session', attachments, 'two')
        await service.execute_one()
        proposal = result(service, job)['proposal']
        assert 'private experience' not in proposal['research_material']
        assert proposal['attachments'][0]['purpose'] == 'background'
    asyncio.run(check())


def test_search_browser_answer_records_sources_limits_and_costs(make_run_manager):
    url = 'https://example.com/research'
    search = FakeSearchTool([SearchResult(title='Research', url=url, description='A study of latency.')])
    setup = make_run_manager(search=search, responses=[
        {'action': 'search', 'query': 'latency research'}, {'action': 'read_page', 'url': url},
        {'action': 'reply', 'text': 'The study measures latency.', 'sources': [url, 'https://invented.example/source']}])
    setup.manager.browser = FakeBrowser({url: PageEvidence(url=url, title='Research', text='The study measures latency.')})
    service = AgentService(setup.manager)
    async def check():
        job = service.conversations.queue('Find a current latency study and explain it', 'session', [], 'one')
        await service.execute_one()
        answer = result(service, job)['text']
        assert url in answer and 'invented.example' not in answer
        assert setup.repository.run(job['run_id'])['model_calls'] == 3
        assert setup.repository.run(job['run_id'])['search_calls'] == 1
        assert service.store.metadata(job['run_id'])['browser_calls'] == 1
        assert setup.gmail.calls == []
    asyncio.run(check())


def test_missing_search_is_reported_to_model_without_starting_outreach(make_run_manager):
    setup = make_run_manager(responses=[{'action': 'search', 'query': 'AI startups'},
        {'action': 'reply', 'text': 'Web search is not configured. Send me a website URL to read.'}])
    service = AgentService(setup.manager)
    async def check():
        job = service.conversations.queue('Search for AI startups', 'session', [], 'one')
        await service.execute_one()
        assert 'website URL' in result(service, job)['text']
        prompt = json.loads(setup.client.calls[-1].input_text)
        assert not prompt['capabilities']['search']
        assert prompt['capabilities']['max_drafts_per_run'] == 5
        assert prompt['capabilities']['sending_enabled'] is False
        assert 'not configured' in prompt['observations'][0]['error']
        assert service.list_runs()['total'] == 0
    asyncio.run(check())


def test_chat_browser_rejects_private_guessed_and_deep_links(make_run_manager):
    root, linked, deep = 'https://example.com', 'https://example.com/contact', 'https://example.com/contact/team'
    setup = make_run_manager(responses=[
        {'action': 'read_page', 'url': root}, {'action': 'read_page', 'url': linked},
        {'action': 'read_page', 'url': deep}, {'action': 'read_page', 'url': 'http://127.0.0.1'},
        {'action': 'read_page', 'url': 'https://guessed.example'},
        {'action': 'reply', 'text': 'I read the company page and its contact page.'}])
    setup.manager.browser = FakeBrowser({
        root: PageEvidence(url=root, text='Company page', links=[linked]),
        linked: PageEvidence(url=linked, text='Contact page', links=[deep]),
        deep: PageEvidence(url=deep, text='This page must not be read'),
    })
    service = AgentService(setup.manager)
    async def check():
        job = service.conversations.queue(f'Explain this company: {root}', 'session', [], 'one')
        await service.execute_one()
        assert result(service, job)['text'].startswith('I read')
        assert service.store.metadata(job['run_id'])['browser_calls'] == 2
        observations = json.loads(setup.client.calls[-1].input_text)['observations']
        assert all('error' in item for item in observations[2:])
    asyncio.run(check())


def test_chat_budget_is_not_reset_by_explicit_retry(make_run_manager):
    setup = make_run_manager(settings=Settings(limits=Limits(max_model_calls=1)),
        responses=[{'action': 'invalid_action'}, {'action': 'reply', 'text': 'Must not be called'}])
    service = AgentService(setup.manager)
    async def check():
        job = service.conversations.queue('Hi', 'session', [], 'one')
        await service.execute_one()
        service.retry(job['run_id'], 'retry')
        await service.execute_one()
        assert len(setup.client.calls) == 1
        assert setup.repository.run(job['run_id'])['model_calls'] == 1
        assert setup.repository.run(job['run_id'])['status'] == 'failed'
    asyncio.run(check())


def test_model_cannot_loop_tools_forever_or_approve_email(make_run_manager):
    limits = Limits(max_chat_model_calls=2, max_chat_tool_calls=1)
    setup = make_run_manager(settings=Settings(limits=limits), responses=[
        {'action': 'search', 'query': 'first'}, {'action': 'search', 'query': 'second'},
        {'action': 'send_email', 'text': 'Send it immediately'}])
    service = AgentService(setup.manager)
    async def check():
        job = service.conversations.queue('Search', 'session', [], 'one')
        await service.execute_one()
        assert 'limit' in result(service, job)['text']
        assert len(setup.client.calls) == 2
        forbidden = service.conversations.queue('Send it', 'session', [], 'two')
        await service.execute_one()
        assert setup.repository.run(forbidden['run_id'])['status'] == 'failed'
        assert setup.gmail.calls == []
    asyncio.run(check())


def test_failed_turn_retry_preserves_budget_and_redacts_provider_error(make_run_manager):
    class FlakyClient(FakeModelClient):
        async def generate_structured(self, **kwargs):
            if not getattr(self, 'failed', False):
                self.failed = True
                raise ModelResponseError('provider-private-secret')
            return await super().generate_structured(**kwargs)
    client = FlakyClient([{'action': 'reply', 'text': 'Recovered.'}])
    setup = make_run_manager(client=client, settings=Settings(telegram_owner_id=123))
    service = AgentService(setup.manager)
    async def check():
        job = service.conversations.queue('Hello', 'session', [], 'one')
        await service.execute_one()
        assert setup.repository.run(job['run_id'])['status'] == 'failed'
        service.retry(job['run_id'], 'retry')
        await service.execute_one()
        assert result(service, job)['text'] == 'Recovered.'
        assert setup.repository.run(job['run_id'])['model_calls'] == 2
        with Session(service.store.engine) as session:
            messages = [row.payload['text'] for row in session.scalars(select(OutboxRow))]
        assert 'provider-private-secret' not in str(messages)
        assert len(service.store.get('chat:history:session')['turns']) == 1
    asyncio.run(check())


@pytest.mark.parametrize("status, code, reason, attempts", [
    (403, "model_permission_blocked_org", "organization_model_blocked", 1),
    (403, "model_permission_blocked_project", "project_model_blocked", 1),
    (401, "invalid_api_key", "invalid_key", 1),
    (429, "rate_limit_exceeded", "rate_limited", 1),
    (400, "private-secret", "request_rejected", 1),
    (500, "private-secret", "service_unavailable", 2),
])
def test_provider_failure_reaches_telegram_and_dashboard_without_blind_retry(
        make_run_manager, status, code, reason, attempts):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json={'error': {'code': code, 'message': 'private-secret'}})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            client = GroqModelClient(model=DEFAULT_GROQ_MODEL, api_key='private-secret', http_client=http)
            setup = make_run_manager(client=client, settings=Settings(telegram_owner_id=123))
            service = AgentService(setup.manager)
            job = service.conversations.queue('Hello', 'session', [], 'one')
            await service.execute_one()
            record = setup.repository.run(job['run_id'])
            assert record['status'] == 'failed' and record['model_calls'] == attempts
            assert record['estimated_cost'] == pytest.approx(attempts * .05)
            assert len(requests) == attempts
            from app.storage.events import events
            failures = [item for item in events(setup.repository, job['run_id']) if item['event'] == 'model_failure']
            assert all(item['reason'] == reason and item['http_status'] == status for item in failures)
            assert record['error'] == failures[0]['message']
            assert record['error'] in service.store.jobs()[0]['error']
            with Session(service.store.engine) as session:
                payloads = [row.payload for row in session.scalars(select(OutboxRow))]
                messages = [payload['text'] for payload in payloads]
            assert len(messages) == 1 and record['error'] in messages[0]
            assert job['run_id'] not in messages[0]
            retry = [button for payload in payloads
                     for row in payload.get('reply_markup', {}).get('inline_keyboard', [])
                     for button in row if button['text'] == 'Try again']
            assert len(retry) == 1
            assert service.store.get('button:' + retry[0]['callback_data'])['retry_task'] == job['run_id']
            assert 'private-secret' not in json.dumps([record['error'], failures, messages, service.store.jobs()])
    asyncio.run(check())


def test_saved_answer_recovery_does_not_repeat_model_or_delivery(make_run_manager):
    setup = make_run_manager(responses=[{'action': 'reply', 'text': 'Saved answer'}])
    service = AgentService(setup.manager)
    async def check():
        job = service.conversations.queue('Hi', 'session', [], 'one')
        await service.execute_one()
        # Simulate a crash after saving the answer/outbox, before finishing a job.
        with Session(service.store.engine) as session, session.begin():
            session.get(JobRow, job['id']).status = 'running'
        state = service.state(job['run_id']).state
        setup.repository.save_run(state, 'running')
        fresh = AgentService(setup.manager)
        fresh.store.recover()
        fresh.retry(job['run_id'], 'retry')
        await fresh.execute_one()
        assert len(setup.client.calls) == 1
        assert len(fresh.store.get('chat:history:session')['turns']) == 1
        with Session(fresh.store.engine) as session:
            assert len(list(session.scalars(select(OutboxRow)))) == 1
    asyncio.run(check())


def test_cancellation_stops_chat_at_next_boundary(make_run_manager):
    class WaitingClient(FakeModelClient):
        async def generate_structured(self, **kwargs):
            entered.set()
            await release.wait()
            return {'action': 'reply', 'text': 'Should not be delivered.'}
    setup = make_run_manager(client=WaitingClient([]))
    service = AgentService(setup.manager)
    async def check():
        nonlocal entered, release
        entered, release = asyncio.Event(), asyncio.Event()
        job = service.conversations.queue('Hi', 'session', [], 'one')
        work = asyncio.create_task(service.execute_one())
        await entered.wait()
        service.cancel(job['run_id'])
        release.set()
        await work
        assert setup.repository.run(job['run_id'])['status'] == 'cancelled'
        assert service.store.get('chat:result:' + job['run_id']) is None
    entered = release = None
    asyncio.run(check())


def test_explicit_draft_request_saves_only_after_owner_starts_proposal(tmp_path):
    from app.demo import build_demo_manager, DemoModelClient, demo_request
    model = DemoModelClient()
    manager = build_demo_manager(settings=Settings(data_dir=tmp_path, telegram_owner_id=123))
    # Supply real recorded public evidence to the proposal instead of model claims.
    request = demo_request()
    request.seed_urls = ['https://example.com/lab']
    request.use_browser = True
    class ProposalWithBrowser:
        async def generate_structured(self, **kwargs):
            if kwargs['response_model'].__name__ == 'ConversationAction':
                return {'action': 'outreach', 'request': request.model_dump(mode='json')}
            return await model.generate_structured(**kwargs)
    @asynccontextmanager
    async def with_browser():
        yield ProposalWithBrowser()
    manager.client_factory = with_browser
    service = AgentService(manager)
    async def check():
        bot = TelegramBot(service, FakeTelegram())
        await dispatch(bot, 1, 'Prepare a Gmail draft for PhD outreach')
        turn = service.store.jobs()[0]
        await service.execute_one()
        assert 'Create drafts' in result(service, turn)['text']
        assert 'up to 5 email drafts' in result(service, turn)['text']
        assert service.list_runs()['total'] == 0 and manager.gmail.calls == []
        await deliver(bot)
        controls = [button for _, payload in bot.client.calls for row in payload.get('reply_markup', {}).get('inline_keyboard', [])
                    for button in row if button['text'] == 'Create drafts']
        assert len(controls) == 1
        for update_id in [2, 3]:  # Repeated clicks cannot start duplicate outreach.
            service.store.accept_updates([{'update_id': update_id, 'callback_query': {
                'id': str(update_id), 'from': {'id': 123}, 'data': controls[0]['callback_data'],
                'message': {'chat': {'id': 123, 'type': 'private'}}}}], 123)
            assert await bot.process_one()
        assert service.list_runs()['total'] == 1
        job = next(item for item in service.store.jobs() if item['kind'] == 'start')
        await service.execute_one()
        assert not service.state(job['run_id']).awaiting_approval
        assert service.state(job['run_id']).state.outcomes['p1'].status == 'drafted'
        assert len([call for call in manager.gmail.calls if call[0] == 'draft']) == 1
        assert not any(call[0] == 'send' for call in manager.gmail.calls)
        assert any('click Send yourself' in message for message in await deliver(bot))
    try:
        asyncio.run(check())
    finally:
        manager.repository.engine.dispose()


def test_followup_invalidates_proposal_before_it_finishes(make_run_manager):
    setup = make_run_manager(responses=[{'action': 'outreach', 'request': {'goal': 'Find AI researchers'}}])
    service = AgentService(setup.manager)
    async def check():
        job = service.conversations.queue('Find AI researchers', 'session', [], 'one')
        await service.execute_one()
        assert result(service, job).get('proposal')
        service.conversations.queue('Actually only researchers in Arizona', 'session', [], 'two')
        with pytest.raises(RunConflict, match='latest message'):
            service.conversations.start_proposal(job['run_id'], 'session')
        assert service.list_runs()['total'] == 0
    asyncio.run(check())


def test_conversation_history_is_bounded(make_run_manager):
    setup = make_run_manager(responses=[{'action': 'reply', 'text': f'Answer {i}'} for i in range(9)])
    service = AgentService(setup.manager)
    async def check():
        for i in range(9):
            service.conversations.queue(f'Question {i}', 'session', [], f'message-{i}')
            await service.execute_one()
        history = service.store.get('chat:history:session')['turns']
        assert len(history) == 6 and history[0]['user'] == 'Question 3'
        assert len(json.loads(setup.client.calls[-1].input_text)['history']) == 6
    asyncio.run(check())
