"""Known recipients need writing and review, rather than prospect discovery."""
import asyncio
from datetime import timedelta
import json

import pytest

from app.connectors.gmail.client import FakeGmailClient
from app.connectors.telegram.bot import TelegramBot
from app.connectors.telegram.client import FakeTelegram
from app.domain.workflow import WorkflowRequest, utc_now
from app.services.application import AgentService
from app.services.limits import Limits
from app.services.runs import RunConflict
from app.settings import Settings


class ConnectedGmail(FakeGmailClient):
    def status(self):
        return {'connected': True, 'email': 'owner@example.com', 'account_id': 'test-owner'}


def request(**changes):
    return WorkflowRequest.model_validate({'goal': 'Write a short test email with subject Hello.',
        'draft_mode': 'direct', 'sender': {'name': 'Alex', 'email': 'owner@example.com'},
        'recipients': {'recipient': {'email': 'friend@example.com'}}, 'gmail_action': 'draft', **changes})


def model_results(*, approved=True):
    return [{'prospect_id': 'recipient', 'subject': 'Hello', 'body': 'Hi,\n\nThis is a quick test email.\n\nAlex'},
        {'prospect_id': 'recipient', 'approved': approved, 'score': 0.9 if approved else 0.2,
         'issues': [] if approved else ['Remove an unsupported statement.']}]


def test_known_recipient_gets_reviewed_gmail_draft_without_research(make_run_manager):
    setup = make_run_manager(responses=model_results(), gmail=ConnectedGmail())
    result = asyncio.run(setup.manager.start(request()))
    state = result.state
    assert state.current_step == 'completed' and state.outcomes['recipient'].status == 'drafted'
    assert [call.response_model.__name__ for call in setup.client.calls] == ['EmailDraft', 'ReviewResult']
    assert state.qualification_results == [] and state.pages == [] and state.search_results == []
    assert state.prospects[0].website is None and state.prospects[0].industry is None
    assert state.prospects[0].company_name == 'friend@example.com'
    assert state.human_decisions == {} and not result.awaiting_approval
    assert [kind for kind, _ in setup.gmail.calls if kind == 'draft'] == ['draft']
    assert not any(kind == 'send' for kind, _ in setup.gmail.calls)
    for call in setup.client.calls:
        assert json.loads(call.input_text)['direct_email_brief']['goal'] == request().goal


def test_requested_followup_is_not_blocked_as_new_cold_outreach(make_run_manager):
    setup = make_run_manager(responses=model_results())
    timestamp = utc_now().isoformat()
    setup.repository.update_contact('friend@example.com', active_conversation=True,
        last_contact_at=timestamp, reconnect_at=(utc_now() + timedelta(days=3)).isoformat())
    result = asyncio.run(setup.manager.start(request()))
    assert result.state.outcomes['recipient'].status == 'drafted'
    assert setup.repository.contact('friend@example.com')['last_contact_at'] == timestamp


def test_direct_drafting_still_respects_opt_out(make_run_manager):
    setup = make_run_manager(responses=[])
    setup.repository.update_contact('friend@example.com', opted_out=True)
    result = asyncio.run(setup.manager.start(request()))
    assert result.state.outcomes['recipient'].status == 'blocked'
    assert setup.client.calls == [] and not any(kind == 'draft' for kind, _ in setup.gmail.calls)


@pytest.mark.parametrize('changes,question', [
    ({'recipients': {}}, 'who should I address'),
    ({'recipients': {str(i): {'email': f'friend{i}@example.com'} for i in range(6)}}, 'up to 5'),
    ({'use_search': True}, 'information already supplied'),
])
def test_incomplete_or_oversized_direct_request_stops_before_models(make_run_manager, changes, question):
    setup = make_run_manager(responses=[])
    with pytest.raises(RunConflict, match=question):
        asyncio.run(setup.manager.start(request(**changes)))
    assert setup.client.calls == [] and setup.gmail.calls == []


@pytest.mark.parametrize('failure', ['review', 'budget'])
def test_direct_draft_never_reaches_gmail_without_passing_review_and_budget(make_run_manager, failure):
    settings = Settings(limits=Limits(max_revisions=0, max_model_calls=1 if failure == 'budget' else 40))
    setup = make_run_manager(responses=model_results(approved=False), settings=settings)
    result = asyncio.run(setup.manager.start(request()))
    assert result.state.outcomes['recipient'].status in {'manual_review', 'failed'}
    assert not any(kind in {'draft', 'send'} for kind, _ in setup.gmail.calls)


def test_app_only_direct_draft_keeps_human_review(make_run_manager):
    setup = make_run_manager(responses=model_results())
    result = asyncio.run(setup.manager.start(request(gmail_action='none')))
    assert result.awaiting_approval and result.state.approval_requests[0].recipient.email == 'friend@example.com'
    assert not any(kind in {'draft', 'send'} for kind, _ in setup.gmail.calls)


def test_duplicate_recipients_create_one_direct_draft(make_run_manager):
    setup = make_run_manager(responses=model_results())
    result = asyncio.run(setup.manager.start(request(recipients={
        'recipient': {'email': 'friend@example.com'}, 'duplicate': {'email': 'FRIEND@example.com'}})))
    assert result.state.outcomes['duplicate'].status == 'blocked'
    assert len([kind for kind, _ in setup.gmail.calls if kind == 'draft']) == 1


def test_direct_draft_continues_after_stop_without_rewriting(make_run_manager):
    setup = make_run_manager(responses=model_results())
    service = AgentService(setup.manager)
    job = service.start(request(), 'first')
    service.tasks.remember('session', job['run_id'])
    original = setup.client.generate_structured
    stopped = False

    async def stop_after_writing(**kwargs):
        nonlocal stopped
        result = await original(**kwargs)
        if kwargs['response_model'].__name__ == 'EmailDraft' and not stopped:
            stopped = True
            service.tasks.stop(job['run_id'])
        return result

    setup.client.generate_structured = stop_after_writing

    async def exercise():
        await service.execute_one()
        assert setup.repository.run(job['run_id'])['status'] == 'stopped'
        fresh = AgentService(setup.manager)
        await fresh.tasks.continue_task('session', 'continue')
        await fresh.execute_one()
        assert fresh.state(job['run_id']).state.outcomes['recipient'].status == 'drafted'
        assert len(setup.client.calls) == 2
        assert len([kind for kind, _ in setup.gmail.calls if kind == 'draft']) == 1

    asyncio.run(exercise())


def test_telegram_direct_draft_has_friendly_confirmation_and_one_gmail_write(make_run_manager):
    proposal = {'action': 'outreach', 'request': request().model_dump(mode='json')}
    setup = make_run_manager(responses=[proposal, *model_results()], gmail=ConnectedGmail(),
                             settings=Settings(telegram_owner_id=123))
    service, client = AgentService(setup.manager), FakeTelegram()
    bot = TelegramBot(service, client)

    async def exercise():
        service.store.accept_updates([{'update_id': 1, 'message': {'from': {'id': 123},
            'chat': {'id': 123, 'type': 'private'}, 'text': 'Write a short test email to friend@example.com with subject Hello.'}}], 123)
        await bot.process_one()
        await service.execute_one()
        assert not any(kind == 'draft' for kind, _ in setup.gmail.calls)
        while await bot.deliver_one(): pass
        texts = [payload['text'] for method, payload in client.calls if method == 'sendMessage']
        assert 'friend@example.com' in texts[0] and 'Create draft' in texts[0]
        assert not any(term in texts[0] for term in ('Web search:', 'Batch limit:', 'qualification', 'Run:', 'not supplied'))
        button = next(button for _, payload in client.calls for row in payload.get('reply_markup', {}).get('inline_keyboard', [])
                      for button in row if button['text'] == 'Create draft')
        for number in (2, 3):
            service.store.accept_updates([{'update_id': number, 'callback_query': {'id': str(number),
                'from': {'id': 123}, 'data': button['callback_data'],
                'message': {'chat': {'id': 123, 'type': 'private'}}}}], 123)
            await bot.process_one()
        await service.execute_one()
        while await bot.deliver_one(): pass
        assert len([kind for kind, _ in setup.gmail.calls if kind == 'draft']) == 1
        texts = [payload['text'] for method, payload in client.calls if method == 'sendMessage']
        assert any('Your draft is ready in Gmail.' in text and 'Subject: Hello' in text for text in texts)
        assert all('Run:' not in text and 'no_matches' not in text and 'Outreach started:' not in text for text in texts)
        assert json.loads(setup.client.calls[0].input_text)['connected_email'] == 'owner@example.com'
        stats = service.overview()['stats']
        assert stats['drafts'] == 1 and stats['qualified'] == 0

    asyncio.run(exercise())


def test_missing_address_becomes_question_instead_of_empty_research(make_run_manager):
    setup = make_run_manager(responses=[{'action': 'outreach', 'request': request(recipients={}).model_dump(mode='json')}],
                             gmail=ConnectedGmail(), settings=Settings(telegram_owner_id=123))
    service = AgentService(setup.manager)

    async def exercise():
        job = service.conversations.queue('Write a test email', 'session', [], 'first')
        await service.execute_one()
        reply = service.store.get('chat:result:' + job['run_id'])
        assert 'who should I address' in reply['text'] and 'proposal' not in reply
        assert service.list_runs()['total'] == 0 and setup.gmail.calls == []

    asyncio.run(exercise())


def test_edit_button_remembers_subject_and_body_across_messages(make_run_manager):
    setup = make_run_manager(responses=model_results(), settings=Settings(telegram_owner_id=123))
    service, client = AgentService(setup.manager), FakeTelegram()
    bot = TelegramBot(service, client)

    async def exercise():
        job = service.start(request(gmail_action='none'), 'start')
        await service.execute_one()
        bot._review(job['run_id'])
        while await bot.deliver_one(): pass
        edit = next(button for _, payload in client.calls for row in payload.get('reply_markup', {}).get('inline_keyboard', [])
                    for button in row if button['text'] == 'Edit')
        service.store.accept_updates([{'update_id': 1, 'callback_query': {'id': '1', 'from': {'id': 123},
            'data': edit['callback_data'], 'message': {'chat': {'id': 123, 'type': 'private'}}}}], 123)
        await bot.process_one()
        assert service.store.get('telegram_conversation')['stage'] == 'edit_subject'
        for number, text in [(2, 'A new subject'), (3, 'The revised body')]:
            service.store.accept_updates([{'update_id': number, 'message': {'from': {'id': 123},
                'chat': {'id': 123, 'type': 'private'}, 'text': text}}], 123)
            await bot.process_one()
        selected = service.choices(job['run_id'])['recipient']
        assert selected['action'] == 'edit'
        assert selected['edited_draft']['subject'] == 'A new subject'
        assert selected['edited_draft']['body'] == 'The revised body'
        assert not any(kind in {'draft', 'send'} for kind, _ in setup.gmail.calls)

    asyncio.run(exercise())


def test_retry_button_queues_one_attempt_and_hides_ids(make_run_manager):
    from app.llm.client import ModelProviderError
    setup = make_run_manager(responses=[{'action': 'reply', 'text': 'Here you go!'}],
                             settings=Settings(telegram_owner_id=123))
    service, client = AgentService(setup.manager), FakeTelegram()
    bot = TelegramBot(service, client)
    original, attempts = setup.client.generate_structured, []

    async def unavailable_once(**kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise ModelProviderError(provider='xAI', reason='invalid_key', status_code=401)
        return await original(**kwargs)

    setup.client.generate_structured = unavailable_once

    async def exercise():
        job = service.conversations.queue('Hello', 'session', [], 'start')
        await service.execute_one()
        while await bot.deliver_one(): pass
        retry = next(button for _, payload in client.calls for row in payload.get('reply_markup', {}).get('inline_keyboard', [])
                     for button in row if button['text'] == 'Try again')
        for number in (2, 3):
            service.store.accept_updates([{'update_id': number, 'callback_query': {'id': str(number),
                'from': {'id': 123}, 'data': retry['callback_data'],
                'message': {'chat': {'id': 123, 'type': 'private'}}}}], 123)
            await bot.process_one()
        assert len(service.store.jobs()) == 2
        await service.execute_one()
        while await bot.deliver_one(): pass
        texts = [payload['text'] for method, payload in client.calls if method == 'sendMessage']
        assert 'Here you go!' in texts
        assert all(job['run_id'] not in text for text in texts)

    asyncio.run(exercise())
