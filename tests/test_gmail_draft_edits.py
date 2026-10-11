"""Existing Gmail drafts change only after approval, using the same ID."""
import asyncio
import base64
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import json
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from app.connectors.gmail.client import GmailClient, FakeGmailClient, encode_message
from app.connectors.gmail.drafts import snapshot
from app.connectors.search import ToolError
from app.connectors.telegram.bot import TelegramBot
from app.connectors.telegram.client import FakeTelegram
from app.domain.schemas import EmailDraft
from app.domain.workflow import Sender, Recipient
from app.services.application import AgentService
from app.services.runs import RunConflict
from app.settings import Settings
from test_conversation import dispatch, deliver
from test_full_api import client_for, execute
from test_supabase_storage import postgres_cluster, postgres_url


class Connected(FakeGmailClient):
    identity = 'owner-account'
    def status(self):
        return {'connected': True, 'account_id': self.identity, 'email': 'owner@example.com'}


def seed(gmail, body='This is the original email.'):
    # Existing Gmail drafts may be empty even though our generated drafts may not.
    message = EmailMessage()
    message['From'], message['To'], message['Subject'] = 'owner@example.com', 'friend@example.com', 'Original'
    message.set_content(body)
    gmail.drafts['saved-draft'] = {'id': 'saved-draft', 'message': {'threadId': 'thread-1',
        'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}}


def responses():
    return [{'action': 'read_gmail_draft', 'query': 'latest'},
            {'action': 'edit_draft', 'draft_id': 'saved-draft', 'query': 'Add: This is a test email, please ignore.'},
            {'prospect_id': 'draft', 'subject': 'Original', 'body': 'This is a test email, please ignore.'},
            {'prospect_id': 'draft', 'approved': True, 'score': 0.95, 'issues': []}]


async def prepare(setup):
    service = AgentService(setup.manager)
    chat = service.conversations.queue('Edit the latest email draft and add test content.', 'session', [], 'edit')
    await service.execute_one()
    cached = service.store.get('chat:result:' + chat['run_id'])
    edit_id = cached['started_edit_run_id']
    await service.execute_one()
    assert service.state(edit_id).awaiting_approval
    return service, edit_id, service.draft_edits.proposal(edit_id)


def test_telegram_preview_approval_restart_and_repeated_clicks_update_same_draft(make_run_manager):
    gmail = Connected(); seed(gmail)
    setup = make_run_manager(gmail=gmail, responses=responses(), settings=Settings(telegram_owner_id=123))
    async def check():
        service, edit_id, proposal = await prepare(setup)
        assert not any(kind in {'draft', 'send', 'update_draft'} for kind, _ in gmail.calls)
        # A new service loads the same pending proposal from saved records.
        fresh = AgentService(setup.manager)
        client = FakeTelegram(); bot = TelegramBot(fresh, client)
        texts = await deliver(bot)
        assert any('Gmail has not been changed' in text and 'This is a test email' in text for text in texts)
        button = next(button for _, payload in client.calls for row in payload.get('reply_markup', {}).get('inline_keyboard', [])
                      for button in row if button['text'] == 'Approve changes')
        for number in (1, 2):
            fresh.store.accept_updates([{'update_id': number, 'callback_query': {'id': str(number),
                'from': {'id': 123}, 'data': button['callback_data'], 'message': {'chat': {'id': 123, 'type': 'private'}}}}], 123)
            assert await bot.process_one()
        assert len([job for job in fresh.store.jobs() if job['kind'] == 'draft_edit_apply']) == 1
        await fresh.execute_one()
        assert [kind for kind, _ in gmail.calls if kind == 'update_draft'] == ['update_draft']
        assert list(gmail.drafts) == ['saved-draft']
        assert 'This is a test email' in snapshot(gmail.drafts['saved-draft'])['body']
        assert not any(kind in {'draft', 'send'} for kind, _ in gmail.calls)
        assert fresh.state(edit_id).state.outcomes['draft'].status == 'updated'
        assert fresh.overview()['stats']['drafts'] == 0  # An update is not a creation.
        assert fresh.overview()['stats']['pending_approvals'] == 0
        fresh.draft_edits.decide(edit_id, proposal['fingerprint'], 'approve')
        assert not await fresh.execute_one()
    asyncio.run(check())


@pytest.mark.parametrize('body', ['', '—'])
def test_empty_or_placeholder_original_can_be_repaired_after_approval(make_run_manager, body):
    gmail = Connected(); seed(gmail, body=body)
    setup = make_run_manager(gmail=gmail, responses=responses())
    async def check():
        service, edit_id, proposal = await prepare(setup)
        service.draft_edits.decide(edit_id, proposal['fingerprint'], 'approve')
        await service.execute_one()
        assert snapshot(gmail.drafts['saved-draft'])['body'].strip() == 'This is a test email, please ignore.'
    asyncio.run(check())


def test_reject_and_stale_approval_leave_gmail_unchanged(make_run_manager):
    gmail = Connected(); seed(gmail)
    setup = make_run_manager(gmail=gmail, responses=responses())
    async def check():
        service, edit_id, proposal = await prepare(setup)
        with pytest.raises(RunConflict): service.draft_edits.decide(edit_id, '0'*64, 'approve')
        service.draft_edits.decide(edit_id, proposal['fingerprint'], 'reject')
        with pytest.raises(RunConflict): service.draft_edits.decide(edit_id, proposal['fingerprint'], 'approve')
        assert not await service.execute_one()
        assert snapshot(gmail.drafts['saved-draft'])['body'].strip() == 'This is the original email.'
    asyncio.run(check())


def test_manual_gmail_change_after_preview_blocks_update(make_run_manager):
    gmail = Connected(); seed(gmail)
    setup = make_run_manager(gmail=gmail, responses=responses())
    async def check():
        service, edit_id, proposal = await prepare(setup)
        seed(gmail, body='Changes the owner made in Gmail.')
        service.draft_edits.decide(edit_id, proposal['fingerprint'], 'approve')
        await service.execute_one()
        assert service.draft_edits.proposal(edit_id)['status'] == 'blocked'
        assert not any(kind == 'update_draft' for kind, _ in gmail.calls)
        assert 'owner made' in snapshot(gmail.drafts['saved-draft'])['body']
    asyncio.run(check())


def test_account_change_blocks_old_preview(make_run_manager):
    gmail = Connected(); seed(gmail)
    setup = make_run_manager(gmail=gmail, responses=responses())
    async def check():
        service, edit_id, proposal = await prepare(setup)
        gmail.identity = 'different-account'
        with pytest.raises(RunConflict, match='account changed'):
            service.draft_edits.decide(edit_id, proposal['fingerprint'], 'approve')
        assert not any(kind == 'update_draft' for kind, _ in gmail.calls)
    asyncio.run(check())


def test_uncertain_update_is_not_replayed(make_run_manager):
    class LostResponse(Connected):
        async def update_draft(self, *args):
            await super().update_draft(*args)
            raise ToolError('Confirmation was lost.')
    gmail = LostResponse(); seed(gmail)
    setup = make_run_manager(gmail=gmail, responses=responses())
    async def check():
        service, edit_id, proposal = await prepare(setup)
        service.draft_edits.decide(edit_id, proposal['fingerprint'], 'approve')
        await service.execute_one()
        assert service.draft_edits.proposal(edit_id)['status'] == 'uncertain'
        fresh = AgentService(setup.manager)
        fresh.draft_edits.decide(edit_id, proposal['fingerprint'], 'approve')
        assert not await fresh.execute_one()
        with pytest.raises(RunConflict): fresh.draft_edits.retry(edit_id, 'unsafe-retry')
        assert len([kind for kind, _ in gmail.calls if kind == 'update_draft']) == 1
    asyncio.run(check())


def test_rest_update_preserves_attachment_recipients_and_thread():
    original = EmailMessage()
    original['From'], original['To'] = 'owner@example.com', 'friend@example.com'
    original['Cc'], original['Subject'], original['In-Reply-To'] = 'other@example.com', 'Original', '<reply-id>'
    original.set_content('Original body')
    original.add_alternative('<p>Original body</p>', subtype='html')
    original.add_attachment(b'unchanged file bytes', maintype='application', subtype='octet-stream', filename='notes.bin')
    raw = base64.urlsafe_b64encode(original.as_bytes()).decode()
    payload = {'id': 'stable-draft', 'message': {'raw': raw, 'threadId': 'thread-9'}}
    captured = snapshot(payload)
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=payload if request.method == 'GET' else {'id': 'stable-draft', 'message': {'id': 'new-message'}})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            await GmailClient(http, 'test-token').update_draft('stable-draft', captured['baseline_hash'],
                EmailDraft(prospect_id='draft', subject='Updated', body='New approved email content.'))
    asyncio.run(check())
    assert [request.method for request in requests] == ['GET', 'PUT']
    assert requests[1].url.path.endswith('/drafts/stable-draft')
    data = json.loads(requests[1].content)
    updated = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(data['message']['raw']))
    assert data['message']['threadId'] == 'thread-9'
    assert updated['Cc'] == 'other@example.com' and updated['In-Reply-To'] == '<reply-id>'
    assert updated.get_body(preferencelist=('plain',)).get_content().strip() == 'New approved email content.'
    assert 'New approved email content.' in updated.get_body(preferencelist=('html',)).get_content()
    assert next(updated.iter_attachments()).get_payload(decode=True) == b'unchanged file bytes'


def test_dashboard_decision_is_authenticated_and_shared_with_telegram(make_run_manager):
    gmail = Connected(); seed(gmail)
    setup = make_run_manager(gmail=gmail, responses=responses(), settings=Settings(owner_password='test-password'))
    service, edit_id, proposal = asyncio.run(prepare(setup))
    with client_for(setup) as client:
        path = f'/api/runs/{edit_id}/gmail-edit'
        body = {'fingerprint': proposal['fingerprint'], 'action': 'approve'}
        detail = client.get(f'/api/runs/{edit_id}').json()
        assert detail['draft_edit']['before']['body'].strip() == 'This is the original email.'
        assert 'raw' not in json.dumps(detail['draft_edit'])
        client.headers.pop('X-API-Key')
        assert client.post(path, json=body).status_code == 401
        login = client.post('/auth/login', json={'password': 'test-password'}).json()
        assert client.post(path, json=body).status_code == 403
        client.headers['X-CSRF-Token'] = login['csrf']
        assert client.post(path, json={**body, 'action': 'send'}).status_code == 422
        first = client.post(path, json=body)
        assert first.status_code == 202
        assert service.draft_edits.entries(edit_id) == []
        duplicate = service.draft_edits.decide(edit_id, proposal['fingerprint'], 'approve')
        assert duplicate['job_id'] == first.json()['job_id']
        execute(client)
        assert client.get(f'/api/runs/{edit_id}').json()['draft_edit']['status'] == 'updated'
    assert len([kind for kind, _ in gmail.calls if kind == 'update_draft']) == 1


def test_continuing_pending_edit_cannot_approve_it(make_run_manager):
    gmail = Connected(); seed(gmail)
    setup = make_run_manager(gmail=gmail, responses=responses())
    async def check():
        service, edit_id, _ = await prepare(setup)
        result = await service.tasks.continue_task('session', 'continue')
        assert result['run_id'] == edit_id and result['needs'] == 'review'
        assert not await service.execute_one()
        assert not any(kind == 'update_draft' for kind, _ in gmail.calls)
    asyncio.run(check())


def test_a_new_edit_request_requires_its_own_approval(make_run_manager):
    gmail = Connected(); seed(gmail)
    setup = make_run_manager(gmail=gmail, responses=responses() * 2)
    async def check():
        service, first_id, first = await prepare(setup)
        service.draft_edits.decide(first_id, first['fingerprint'], 'approve')
        await service.execute_one()
        # The owner restores the original in Gmail, then requests the edit anew.
        seed(gmail)
        chat = service.conversations.queue('Edit the latest email draft and add test content.', 'session', [], 'edit-again')
        await service.execute_one()
        second_id = service.store.get('chat:result:' + chat['run_id'])['started_edit_run_id']
        await service.execute_one()
        second = service.draft_edits.proposal(second_id)
        assert first['fingerprint'] != second['fingerprint']
        with pytest.raises(RunConflict): service.draft_edits.decide(second_id, first['fingerprint'], 'approve')
        service.draft_edits.decide(second_id, second['fingerprint'], 'approve')
        await service.execute_one()
        assert len([kind for kind, _ in gmail.calls if kind == 'update_draft']) == 2
    asyncio.run(check())


def test_cancelling_approved_queued_edit_prevents_gmail_write(make_run_manager):
    gmail = Connected(); seed(gmail)
    setup = make_run_manager(gmail=gmail, responses=responses())
    async def check():
        service, edit_id, proposal = await prepare(setup)
        service.draft_edits.decide(edit_id, proposal['fingerprint'], 'approve')
        service.cancel(edit_id)
        await service.execute_one()
        assert not any(kind == 'update_draft' for kind, _ in gmail.calls)
        assert service.state(edit_id).state.current_step == 'cancelled'
    asyncio.run(check())


def test_ambiguous_recipient_returns_choices_without_proposing_an_edit(make_run_manager):
    gmail = Connected(); seed(gmail)
    gmail.drafts['other-draft'] = {**gmail.drafts['saved-draft'], 'id': 'other-draft'}
    service = AgentService(make_run_manager(gmail=gmail).manager)
    result = asyncio.run(service.draft_edits.read('friend@example.com', 'session'))
    assert len(result['choices']) == 2 and 'snapshot_key' not in result
    assert not any(kind == 'update_draft' for kind, _ in gmail.calls)


def test_native_edit_routes_read_write_and_review_to_the_correct_models(make_run_manager):
    from test_model_routing import completion, tool, router_for
    from app.llm.xai_routing import configured_models
    gmail = Connected(); seed(gmail)
    requests = []
    replies = iter([
        completion({'action': 'reply', 'text': 'Who should I send the test email to?'}),
        tool('read_gmail_draft', {'query': 'latest'}, 'read-draft-1'),
        completion(responses()[1]), completion(responses()[2]), completion(responses()[3])])
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=next(replies))
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            setup = make_run_manager(gmail=gmail, settings=Settings(model_provider='xai'))
            @asynccontextmanager
            async def factory(): yield router_for(http)
            setup.manager.client_factory = factory
            service, edit_id, proposal = await prepare(setup)
            assert not any(kind == 'update_draft' for kind, _ in gmail.calls)
            assert len(proposal['draft']['body']) > 1
    asyncio.run(check())
    models = configured_models()
    assert [item['model'] for item in requests] == [models[role] for role in [
        'instruction', 'reasoning', 'reasoning', 'instruction', 'reasoning']]
    assert requests[1]['tool_choice'] == 'required'
    assert [item['name'] for item in requests[1]['tools']] == ['read_gmail_draft']
    assert requests[2]['input'][-2]['call_id'] == requests[2]['input'][-1]['call_id'] == 'read-draft-1'


def test_postgres_restart_and_concurrent_approvals_update_once(postgres_url, tmp_path):
    from app.services.runtime import open_runtime
    from app.llm.client import FakeModelClient
    gmail = Connected(); seed(gmail)
    fake = FakeModelClient(responses())
    @asynccontextmanager
    async def factory(): yield fake
    settings = Settings(supabase_database_url=postgres_url, data_dir=tmp_path, browser_enabled=False)
    async def check():
        async with open_runtime(settings) as manager:
            manager.gmail, manager.client_factory = gmail, factory
            service, edit_id, proposal = await prepare(SimpleNamespace(manager=manager))
        async with open_runtime(settings) as manager:
            manager.gmail, manager.client_factory = gmail, factory
            service = AgentService(manager)
            assert service.draft_edits.proposal(edit_id)['status'] == 'pending'
            with ThreadPoolExecutor(max_workers=2) as pool:
                def approve(_): return service.draft_edits.decide(edit_id, proposal['fingerprint'], 'approve')
                results = await asyncio.to_thread(lambda: list(pool.map(approve, [1, 2])))
            assert results[0]['job_id'] == results[1]['job_id']
            assert len([job for job in service.store.jobs() if job['kind'] == 'draft_edit_apply']) == 1
            await service.execute_one()
            assert service.state(edit_id).state.outcomes['draft'].status == 'updated'
        assert len(fake.calls) == 4 and len([kind for kind, _ in gmail.calls if kind == 'update_draft']) == 1
    asyncio.run(check())
