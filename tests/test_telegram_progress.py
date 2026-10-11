"""Visible stages and typing must work without changing workflow outcomes."""
import asyncio
from threading import Event

from app.connectors.search import ToolError
from app.connectors.telegram.bot import TelegramBot
from app.connectors.telegram.client import FakeTelegram, RateLimited
from app.connectors.telegram.progress import TelegramProgress
from app.services.application import AgentService
from app.services.progress import ProgressTracker, publish
from app.settings import Settings


def job(kind='chat'):
    return {'id': 'job-one', 'run_id': 'saved-run', 'kind': kind, 'status': 'queued'}


def test_one_status_message_changes_stages_and_typing_expires():
    moment = [0.0]
    clock = lambda: moment[0]
    tracker, client = ProgressTracker(clock), FakeTelegram()
    reporter = TelegramProgress(tracker, client, 123, clock=clock)
    saved = job('start')
    tracker.queued(saved)

    async def exercise():
        await reporter.tick()
        assert 'Queued' in client.calls[0][1]['text']
        assert not any(m == 'sendChatAction' for m, _ in client.calls)
        message_id = reporter.sent[saved['id']]['message_id']
        with tracker.track(saved):
            publish('model_start', task='ConversationInstruction', prompt='PRIVATE INPUT')
            moment[0] = 4
            await reporter.tick()
            publish('browser_start', url='https://private-example.invalid')
            moment[0] = 8
            await reporter.tick()
            publish('node_start', node='writing', body='PRIVATE DRAFT')
            moment[0] = 12
            await reporter.tick()
            publish('node_start', node='review')
            moment[0] = 16
            await reporter.tick()
        tracker.finish(saved['id'], 'completed')
        moment[0] = 20
        await reporter.tick()
        assert len([m for m, _ in client.calls if m == 'sendMessage']) == 1
        edits = [p for m, p in client.calls if m == 'editMessageText']
        assert all(p['message_id'] == message_id for p in edits)
        assert {p['text'] for p in edits} == {'Typing…', 'Researching…'}
        assert any(m == 'deleteMessage' and p['message_id'] == message_id for m, p in client.calls)
        assert not any('Task:' in str(p) or 'Elapsed:' in str(p) or 'Finished —' in str(p) for _, p in client.calls)
        assert all('PRIVATE' not in str(p) and 'private-example' not in str(p) for _, p in client.calls)
        count = len(client.calls)
        moment[0] = 40
        await reporter.tick()
        assert len(client.calls) == count and tracker.snapshot() == []
    asyncio.run(exercise())


def test_long_stage_renews_typing_without_repeating_status_messages():
    moment = [0.0]
    clock = lambda: moment[0]
    tracker, client = ProgressTracker(clock), FakeTelegram()
    reporter = TelegramProgress(tracker, client, 123, clock=clock)
    async def exercise():
        with tracker.track(job()):
            await reporter.tick()
            for second in (1, 2, 3, 4, 8, 12, 15, 16):
                moment[0] = second
                await reporter.tick()
            edits = [p for m, p in client.calls if m == 'editMessageText']
            assert edits == []
            assert [p['text'] for m, p in client.calls if m == 'sendMessage'] == ['Typing…']
            assert len([m for m, _ in client.calls if m == 'sendChatAction']) == 5
    asyncio.run(exercise())


def test_progress_honors_retry_after_and_suppresses_uncertain_duplicate_send():
    moment = [0.0]
    clock = lambda: moment[0]
    tracker, client = ProgressTracker(clock), FakeTelegram()
    reporter = TelegramProgress(tracker, client, 123, clock=clock)
    original = client.call
    attempts = []
    async def fail_once(method, **payload):
        attempts.append(method)
        if len(attempts) == 1: raise RateLimited(10)
        return await original(method, **payload)
    client.call = fail_once
    async def exercise():
        tracker.queued(job())
        await reporter.tick()
        moment[0] = 9
        await reporter.tick()
        assert attempts == ['sendMessage']
        moment[0] = 10
        await reporter.tick()
        assert attempts == ['sendMessage', 'sendMessage']
        tracker.finish('job-one', 'completed')
        moment[0] = 14
        await reporter.tick()
        other = job(); other['id'] = 'uncertain'
        tracker.queued(other)
        async def lost_response(method, **payload):
            attempts.append(method)
            raise ToolError('Connection lost after Telegram may have accepted it')
        client.call = lost_response
        moment[0] = 20
        await reporter.tick()
        count = len(attempts)
        moment[0] = 25
        await reporter.tick()
        assert len(attempts) == count
    asyncio.run(exercise())


def test_progress_failure_does_not_fail_chat_or_repeat_model(make_run_manager):
    setup = make_run_manager(responses=[{'action': 'reply', 'text': 'Your answer'}],
                             settings=Settings(telegram_owner_id=123))
    service = AgentService(setup.manager)
    client, statuses = FakeTelegram(), FakeTelegram()
    bot = TelegramBot(service, client)
    async def unavailable(*args, **kwargs): raise ToolError('Status unavailable')
    statuses.call = unavailable
    reporter = TelegramProgress(service.progress, statuses, 123)
    async def exercise():
        queued = service.conversations.queue('Hello', 'session', [], 'first')
        await reporter.tick()
        await service.execute_one()
        while await bot.deliver_one(): pass
        assert setup.repository.run(queued['run_id'])['status'] == 'completed'
        assert len(setup.client.calls) == 1
        assert any(p.get('text') == 'Your answer' for m, p in client.calls if m == 'sendMessage')
    asyncio.run(exercise())


def test_typing_and_status_continue_while_database_read_waits(make_run_manager, monkeypatch):
    setup = make_run_manager(settings=Settings(telegram_owner_id=123))
    service = AgentService(setup.manager)
    client = FakeTelegram()
    bot = TelegramBot(service, client)
    entered, release = Event(), Event()
    def slow_inbox():
        entered.set()
        assert release.wait(5), 'The test must release its database read'
        return None
    monkeypatch.setattr(service.store, 'next_update', slow_inbox)
    async def exercise():
        with service.progress.track(job()):
            pending = asyncio.create_task(bot.process_one())
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                await asyncio.wait_for(bot.progress.tick(), timeout=1)
                assert not pending.done()
                assert any(m == 'sendChatAction' for m, _ in client.calls)
            finally:
                release.set()
                await pending
    asyncio.run(exercise())


def test_real_worker_publishes_status_while_waiting_for_model(make_run_manager):
    from app.llm.client import FakeModelClient
    entered, release = asyncio.Event(), asyncio.Event()
    class SlowModel(FakeModelClient):
        async def generate_structured(self, **kwargs):
            entered.set()
            await release.wait()
            return await super().generate_structured(**kwargs)
    model = SlowModel([{'action': 'reply', 'text': 'Finished answering'}])
    setup = make_run_manager(client=model, settings=Settings(telegram_owner_id=123))
    service = AgentService(setup.manager)
    client = FakeTelegram()
    reporter = TelegramProgress(service.progress, client, 123)
    async def exercise():
        queued = service.conversations.queue('Hello', 'session', [], 'one')
        pending = asyncio.create_task(service.execute_one())
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            await reporter.tick()
            assert any(p.get('text') == 'Typing…' for _, p in client.calls)
            assert any(m == 'sendChatAction' for m, _ in client.calls)
        finally:
            release.set()
            await pending
        assert setup.repository.run(queued['run_id'])['status'] == 'completed'
        assert len(model.calls) == 1
    asyncio.run(exercise())
