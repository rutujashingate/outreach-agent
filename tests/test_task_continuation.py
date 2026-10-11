"""Stop, reopen storage, and continue the original task without repeating reads."""
import asyncio
from contextlib import asynccontextmanager
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.browser.client import FakeBrowser
from app.connectors.telegram.bot import TelegramBot
from app.connectors.telegram.client import FakeTelegram
from app.domain.browser import PageEvidence
from app.llm.client import FakeModelClient, ModelResponseError
from app.main import create_app
from app.services.application import AgentService
from app.services.limits import Limits
from app.services.runs import RunConflict, RunManager
from app.settings import Settings
from app.storage.checkpoints import open_checkpointer
from app.storage.control import JobRow, OutboxRow
from app.storage.database import create_database
from app.storage.repository import Repository


async def message(bot, number, text):
    bot.store.accept_updates([{'update_id': number, 'message': {'text': text,
        'from': {'id': 123}, 'chat': {'id': 123, 'type': 'private'}}}], 123)
    assert await bot.process_one()


def messages(service):
    with Session(service.store.engine) as session:
        return [row.payload['text'] for row in session.scalars(select(OutboxRow))]


def test_sqlite_restart_then_plain_continue_keeps_sources_task_and_budget(tmp_path):
    class FirstClient(FakeModelClient):
        async def generate_structured(self, **kwargs):
            if len(self.calls) == 1:
                raise ModelResponseError('Simulated interruption after reading.')
            return await super().generate_structured(**kwargs)
    first_client = FirstClient([{'action': 'read_page', 'url': 'https://example.com'}])
    second_client = FakeModelClient([{'action': 'reply', 'text': 'The saved page describes API observability.',
                                      'sources': ['https://example.com']}])
    settings = Settings(data_dir=tmp_path, checkpoint_backend='sqlite', telegram_owner_id=123)
    database = f'sqlite:///{tmp_path / "records.sqlite3"}'
    page = PageEvidence(url='https://example.com', text='API observability helps engineers.')
    async def exercise():
        engine = create_database(database)
        @asynccontextmanager
        async def first_factory(): yield first_client
        async with open_checkpointer(settings) as saver:
            manager = RunManager(Repository(engine), saver, settings=settings, client_factory=first_factory,
                                 browser=FakeBrowser({'https://example.com': page}))
            service = AgentService(manager)
            bot = TelegramBot(service, FakeTelegram())
            await message(bot, 1, 'Read https://example.com and explain it')
            job = service.store.jobs()[0]
            await service.execute_one()
            assert manager.repository.run(job['run_id'])['status'] == 'failed'
            snapshot = await service.conversations.graph.aget_state(service.conversations.config(job['run_id']))
            assert snapshot.next == ('decide',)
            assert 'API observability' in snapshot.values['observations'][0]['content']
            assert service.store.metadata(job['run_id'])['browser_calls'] == 1
        engine.dispose()
        engine = create_database(database)
        @asynccontextmanager
        async def second_factory(): yield second_client
        try:
            async with open_checkpointer(settings) as saver:
                browser = FakeBrowser({})
                manager = RunManager(Repository(engine), saver, settings=settings, client_factory=second_factory, browser=browser)
                service = AgentService(manager)
                service.store.recover()
                bot = TelegramBot(service, FakeTelegram())
                await message(bot, 2, 'continue')
                assert len(service.store.jobs()) == 2
                assert {j['run_id'] for j in service.store.jobs()} == {job['run_id']}
                assert any("I'll pick up where we left off." in text for text in messages(service))
                await service.execute_one()
                record = manager.repository.run(job['run_id'])
                assert record['status'] == 'completed' and record['model_calls'] == 3
                assert service.store.metadata(job['run_id'])['browser_calls'] == 1
                assert browser.calls == []
                prompt = json.loads(second_client.calls[0].input_text)
                assert prompt['message'] == 'Read https://example.com and explain it'
                assert 'API observability' in prompt['observations'][0]['content']
                assert service.store.get('chat:result:' + job['run_id'])['text'].endswith('https://example.com')
                await message(bot, 3, 'continue')
                assert len(service.store.jobs()) == 2  # Completed work isn't restarted.
        finally:
            engine.dispose()
    asyncio.run(exercise())


def test_stop_during_read_saves_result_and_continue_does_not_repeat_it(make_run_manager):
    setup = make_run_manager(settings=Settings(telegram_owner_id=123), responses=[
        {'action': 'read_page', 'url': 'https://example.com'}, {'action': 'reply', 'text': 'Continued with saved evidence.'}])
    service = AgentService(setup.manager)
    calls = []
    class Browser:
        async def read(self, url, **kwargs):
            calls.append(url)
            await message(bot, 2, 'stop')
            return PageEvidence(url=url, text='Saved page')
    setup.manager.browser = Browser()
    bot = TelegramBot(service, FakeTelegram())
    async def exercise():
        await message(bot, 1, 'Read https://example.com')
        job = service.store.jobs()[0]
        await service.execute_one()
        assert setup.repository.run(job['run_id'])['status'] == 'stopped'
        assert service.store.get('resume:' + job['run_id']) == {'next_steps': ['decide'], 'completed_tools': 1}
        await message(bot, 3, 'please continue')
        await service.execute_one()
        assert setup.repository.run(job['run_id'])['status'] == 'completed'
        assert len(calls) == 1 and len(setup.client.calls) == 2
        assert setup.gmail.calls == []
    asyncio.run(exercise())


def test_tool_cache_closes_gap_before_graph_checkpoint(make_run_manager):
    setup = make_run_manager(responses=[{'action': 'read_page', 'url': 'https://example.com'}, {'action': 'reply', 'text': 'Recovered'}])
    browser = FakeBrowser({'https://example.com': PageEvidence(url='https://example.com', text='Retained text')})
    setup.manager.browser = browser
    service = AgentService(setup.manager)
    original = service.conversations.read_tool
    async def interrupted(*args):
        await original(*args)
        raise RuntimeError('Crash before checkpoint')
    service.conversations.read_tool = interrupted
    async def exercise():
        job = service.conversations.queue('Read https://example.com', 's', [], 'start')
        await service.execute_one()
        fresh = AgentService(setup.manager)
        await fresh.tasks.continue_task('s', 'continue')
        await fresh.execute_one()
        assert setup.repository.run(job['run_id'])['status'] == 'completed'
        assert len(browser.calls) == 1
        assert fresh.store.metadata(job['run_id'])['browser_calls'] == 1
    asyncio.run(exercise())


def test_stopped_queued_work_and_duplicate_continuation_keep_one_job(make_run_manager):
    setup = make_run_manager(responses=[{'action': 'reply', 'text': 'Finished'}])
    service = AgentService(setup.manager)
    async def exercise():
        job = service.conversations.queue('A saved task', 's', [], 'start')
        service.tasks.stop(job['run_id'])
        assert not await service.execute_one()
        first = await service.tasks.continue_task('s', 'same-update')
        second = await service.tasks.continue_task('s', 'same-update')
        assert first['job']['id'] == second['job']['id']
        await service.execute_one()
        assert len(setup.client.calls) == 1
    asyncio.run(exercise())


def test_continue_never_submits_pending_approval(make_run_manager, workflow_data):
    setup = make_run_manager()
    service = AgentService(setup.manager)
    job = service.start(workflow_data.request, 'start')
    service.tasks.remember('s', job['run_id'])
    async def exercise():
        await service.execute_one()
        result = await service.tasks.continue_task('s', 'continue')
        assert result['needs'] == 'review' and 'job' not in result
        assert job['run_id'] not in result['message']
        assert service.state(job['run_id']).awaiting_approval
        assert len(service.store.jobs()) == 1 and setup.gmail.calls == []
    asyncio.run(exercise())


def test_outreach_stop_and_resume_preserves_completed_model_work(make_run_manager, workflow_data):
    setup = make_run_manager()
    service = AgentService(setup.manager)
    original = setup.client.generate_structured
    stopped = False
    async def stop_after_qualification(**kwargs):
        nonlocal stopped
        result = await original(**kwargs)
        if kwargs['response_model'].__name__ == 'Qualification' and not stopped:
            stopped = True
            service.tasks.stop(job['run_id'])
        return result
    setup.client.generate_structured = stop_after_qualification
    job = service.start(workflow_data.request.model_copy(update={'gmail_action': 'draft'}), 'start')
    service.tasks.remember('s', job['run_id'])
    async def exercise():
        await service.execute_one()
        assert setup.repository.run(job['run_id'])['status'] == 'stopped'
        await service.tasks.continue_task('s', 'continue')
        await service.execute_one()
        assert service.state(job['run_id']).state.outcomes['p1'].status == 'drafted'
        assert len(setup.client.calls) == 6
        assert len([c for c in setup.gmail.calls if c[0] == 'draft']) == 1
        assert not any(c[0] == 'send' for c in setup.gmail.calls)
    asyncio.run(exercise())


def test_multiple_tasks_require_selection_and_new_sessions_do_not_inherit_tasks(make_run_manager):
    setup = make_run_manager(responses=[])
    service = AgentService(setup.manager)
    first = service.conversations.queue('Task one', 's', [], 'one')
    second = service.conversations.queue('Task two', 's', [], 'two')
    async def exercise():
        with pytest.raises(RunConflict, match='Several tasks'):
            await service.tasks.continue_task('s', 'ambiguous')
        with pytest.raises(RunConflict, match='no saved task'):
            await service.tasks.continue_task('new-session', 'unknown')
        selected = await service.tasks.continue_task('s', 'selected', second['run_id'])
        assert selected['run_id'] == second['run_id'] and 'already queued' in selected['message']
        assert first['run_id'] != second['run_id'] and setup.client.calls == []
    asyncio.run(exercise())


def test_continue_keeps_exhausted_budget_and_permanent_cancellation(make_run_manager):
    setup = make_run_manager(responses=[{'action': 'search', 'query': 'query'}], settings=Settings(limits=Limits(max_model_calls=1)))
    service = AgentService(setup.manager)
    async def exercise():
        job = service.conversations.queue('Research', 's', [], 'one')
        # Simulate an interrupted model attempt that already consumed its budget.
        setup.repository.reserve_call(job['run_id'], 'model', setup.manager.settings.limits)
        service.tasks.stop(job['run_id'])
        await service.tasks.continue_task('s', 'continue')
        await service.execute_one()
        assert setup.repository.run(job['run_id'])['status'] == 'failed'
        assert setup.client.calls == []
        service.cancel(job['run_id'])
        result = await service.tasks.continue_task('s', 'cancelled')
        assert 'cancelled' in result['message'] and 'job' not in result
        with pytest.raises(RunConflict):
            service.retry(job['run_id'], 'force')
    asyncio.run(exercise())


def test_stop_and_continue_api_requires_owner(make_run_manager):
    setup = make_run_manager(responses=[{'action': 'reply', 'text': 'Done'}], settings=Settings(api_key='owner'))
    with TestClient(create_app(manager=setup.manager, background=False)) as client:
        service = client.app.state.service
        job = service.conversations.queue('Saved task', 's', [], 'one')
        for action in ('stop', 'continue'):
            assert client.post(f'/api/runs/{job["run_id"]}/{action}').status_code == 401
        headers = {'X-API-Key': 'owner'}
        assert client.post(f'/api/runs/{job["run_id"]}/stop', headers=headers).status_code == 202
        continued = client.post(f'/api/runs/{job["run_id"]}/continue', headers=headers)
        assert continued.status_code == 202 and continued.json()['job']['run_id'] == job['run_id']


def test_finished_model_answer_survives_failure_before_node_checkpoint(make_run_manager, monkeypatch):
    from app.agent.context import trace as original_trace
    setup = make_run_manager(responses=[{'action': 'read_page', 'url': 'https://example.com'},
                                       {'action': 'reply', 'text': 'Recovered evidence'}])
    browser = FakeBrowser({'https://example.com': PageEvidence(url='https://example.com', text='Evidence')})
    setup.manager.browser = browser
    service = AgentService(setup.manager)
    crashed = False
    async def fail_after_cache(repository, run_id, event, **kwargs):
        nonlocal crashed
        if event == 'model_end' and not crashed:
            crashed = True
            raise RuntimeError('Stopped before graph checkpoint')
        await original_trace(repository, run_id, event, **kwargs)
    monkeypatch.setattr('app.agent.context.trace', fail_after_cache)
    async def exercise():
        job = service.conversations.queue('Read https://example.com', 's', [], 'one')
        await service.execute_one()
        assert setup.repository.run(job['run_id'])['status'] == 'failed'
        await service.tasks.continue_task('s', 'continue')
        await service.execute_one()
        assert setup.repository.run(job['run_id'])['status'] == 'completed'
        assert setup.repository.run(job['run_id'])['model_calls'] == 2
        assert len(setup.client.calls) == 2 and len(browser.calls) == 1
    asyncio.run(exercise())


def test_continue_reports_missing_recipient_without_selecting_one(make_run_manager, workflow_data):
    setup = make_run_manager()
    service = AgentService(setup.manager)
    request = workflow_data.request.model_copy(update={'recipients': {}, 'discover_emails': True})
    job = service.start(request, 'one')
    service.tasks.remember('s', job['run_id'])
    async def exercise():
        await service.execute_one()
        assert service.state(job['run_id']).awaiting_recipients
        result = await service.tasks.continue_task('s', 'continue')
        assert result['needs'] == 'recipients' and job['run_id'] not in result['message']
        assert 'job' not in result and setup.gmail.calls == []
    asyncio.run(exercise())


def test_stop_during_gmail_records_action_then_continue_never_drafts_twice(make_run_manager, workflow_data):
    setup = make_run_manager()
    service = AgentService(setup.manager)
    job = service.start(workflow_data.request.model_copy(update={'gmail_action': 'draft'}), 'start')
    service.tasks.remember('s', job['run_id'])
    original = setup.gmail.create_draft
    async def stop_during_write(*args):
        service.tasks.stop(job['run_id'])
        return await original(*args)
    setup.gmail.create_draft = stop_during_write
    async def exercise():
        await service.execute_one()
        assert setup.repository.run(job['run_id'])['status'] == 'stopped'
        assert service.overview()['stats']['drafts'] == 1
        await service.tasks.continue_task('s', 'continue')
        await service.execute_one()
        assert setup.repository.run(job['run_id'])['status'] == 'completed'
        assert len([call for call in setup.gmail.calls if call[0] == 'draft']) == 1
        assert service.details(job['run_id'])['saved_progress']['next_steps'] == []
    asyncio.run(exercise())


def test_unfinished_task_is_retained_after_many_completed_questions(make_run_manager):
    setup = make_run_manager(responses=[])
    service = AgentService(setup.manager)
    stopped = service.conversations.queue('Keep this task for later', 's', [], 'stopped')
    service.tasks.stop(stopped['run_id'])
    for index in range(55):
        job = service.conversations.queue(f'Unrelated question {index}', 's', [], str(index))
        setup.repository.save_run(service.state(job['run_id']).state, 'completed')
    run_id, record = service.tasks.select('s')
    assert run_id == stopped['run_id'] and record['status'] == 'stopped'


def test_continue_old_task_makes_its_new_proposal_current_again(make_run_manager):
    setup = make_run_manager(responses=[{'action': 'reply', 'text': 'Hello'},
        {'action': 'outreach', 'request': {'goal': 'Create outreach drafts'}}])
    service = AgentService(setup.manager)
    async def exercise():
        old = service.conversations.queue('Create outreach drafts', 's', [], 'old')
        service.tasks.stop(old['run_id'])
        service.conversations.queue('Hi', 's', [], 'new')
        await service.execute_one()
        await service.tasks.continue_task('s', 'continue')
        await service.execute_one()
        job = service.conversations.start_proposal(old['run_id'], 's')
        assert job['kind'] == 'start' and setup.gmail.calls == []
    asyncio.run(exercise())
