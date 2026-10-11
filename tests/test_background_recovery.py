"""A temporary database failure must not silently disable the Telegram bot."""
import asyncio

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, TimeoutError as PoolTimeout
from sqlalchemy.orm import Session

from app.connectors.telegram.bot import TelegramBot
from app.connectors.telegram.client import FakeTelegram
from app.connectors.search import ToolError
from app.main import create_app
from app.services.application import AgentService
from app.services import background
from app.settings import Settings
from app.storage.control import InboxRow, OutboxRow


@pytest.fixture
def short_waits(monkeypatch):
    original = background.wait_or_stop

    async def short(stop, seconds):
        await original(stop, min(seconds, 0.001))

    monkeypatch.setattr(background, 'wait_or_stop', short)
    monkeypatch.setattr('app.connectors.telegram.bot.wait_or_stop', short)


def update():
    return {'update_id': 1, 'message': {'from': {'id': 123},
        'chat': {'id': 123, 'type': 'private'}, 'text': '/help'}}


def test_worker_recovers_from_failed_queue_read(make_run_manager, monkeypatch, short_waits, caplog):
    setup = make_run_manager(responses=[{'action': 'reply', 'text': 'Recovered'}])
    service = AgentService(setup.manager)
    job = service.conversations.queue('Hello', 'session', [], 'first')
    claim, finish = service.store.claim, service.store.finish_job
    attempts = 0

    def claim_once_unavailable():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PoolTimeout('PRIVATE DATABASE URL')
        return claim()

    def finish_and_stop(*args):
        finish(*args)
        service.stopping.set()

    monkeypatch.setattr(service.store, 'claim', claim_once_unavailable)
    monkeypatch.setattr(service.store, 'finish_job', finish_and_stop)
    asyncio.run(asyncio.wait_for(service.worker(), timeout=3))
    assert service.store.jobs()[0]['status'] == 'completed'
    assert setup.repository.run(job['run_id'])['status'] == 'completed'
    assert len(setup.client.calls) == 1
    assert service.background_health['outreach-worker']['status'] == 'running'
    assert 'PRIVATE DATABASE URL' not in caplog.text


def test_poller_does_not_acknowledge_unsafely_or_duplicate_saved_update(make_run_manager, monkeypatch, short_waits):
    setup = make_run_manager(settings=Settings(telegram_owner_id=123))
    service = AgentService(setup.manager)
    client = FakeTelegram()
    bot = TelegramBot(service, client)
    original_call, accept = client.call, service.store.accept_updates
    offsets = []
    attempts = 0

    async def replay_until_acknowledged(method, **payload):
        if method == 'getUpdates':
            offsets.append(payload['offset'])
            if payload['offset'] > 1:
                bot.stop.set()
                return []
            return [update()]
        return await original_call(method, **payload)

    def connection_lost_after_commit(*args):
        nonlocal attempts
        accept(*args)
        attempts += 1
        if attempts == 1:
            raise OperationalError(None, None, RuntimeError('private connection details'))

    monkeypatch.setattr(client, 'call', replay_until_acknowledged)
    monkeypatch.setattr(service.store, 'accept_updates', connection_lost_after_commit)
    asyncio.run(asyncio.wait_for(bot.poll(), timeout=3))
    assert offsets == [0, 0, 2]
    with Session(service.store.engine) as session:
        assert len(list(session.scalars(select(InboxRow)))) == 1
    assert service.store.get('telegram_offset')['next'] == 2
    assert service.background_health['telegram-poller']['status'] == 'running'


def test_handler_retries_conversation_save_without_repeating_command(make_run_manager, monkeypatch, short_waits):
    setup = make_run_manager(settings=Settings(telegram_owner_id=123))
    service, client = AgentService(setup.manager), FakeTelegram()
    bot = TelegramBot(service, client)
    service.store.accept_updates([update()], 123)
    finish, command = service.store.finish_update, bot._command
    commands, saves = [], []

    def count_command(*args):
        commands.append(args[0])
        command(*args)

    def finish_after_reconnection(*args):
        saves.append(args[0])
        finish(*args)
        if len(saves) == 1:
            raise PoolTimeout('connection unavailable after commit')
        bot.stop.set()

    monkeypatch.setattr(bot, '_command', count_command)
    monkeypatch.setattr(service.store, 'finish_update', finish_after_reconnection)
    asyncio.run(asyncio.wait_for(bot.handle(), timeout=3))
    assert commands == ['/help']
    assert saves == [1, 1]
    assert len([m for m, _ in client.calls if m == 'sendMessage']) == 1
    assert service.store.next_update() is None


def test_temporary_telegram_startup_failure_recovers(make_run_manager, monkeypatch, short_waits):
    setup = make_run_manager(settings=Settings(telegram_owner_id=123))
    service, client = AgentService(setup.manager), FakeTelegram()
    bot = TelegramBot(service, client)
    original_call, identities = client.call, []

    async def temporarily_offline(method, **payload):
        if method == 'getMe':
            identities.append(method)
            if len(identities) == 1:
                raise ToolError('Temporary network failure')
        if method == 'getUpdates':
            bot.stop.set()
        return await original_call(method, **payload)

    monkeypatch.setattr(client, 'call', temporarily_offline)
    asyncio.run(asyncio.wait_for(bot.poll(), timeout=3))
    assert len(identities) == 2
    assert service.store.get('telegram_status')['health'] == 'connected'


def test_delivery_save_failure_never_resends_uncertain_message(make_run_manager, monkeypatch, short_waits):
    setup = make_run_manager(settings=Settings(telegram_owner_id=123))
    service, client = AgentService(setup.manager), FakeTelegram()
    bot = TelegramBot(service, client)
    bot.say('Saved answer')
    reads = 0

    def idle_inbox():
        nonlocal reads
        reads += 1
        if reads == 2:
            bot.stop.set()
        return None

    def failed_save(*args):
        raise OperationalError(None, None, RuntimeError('database unavailable'))

    monkeypatch.setattr(service.store, 'next_update', idle_inbox)
    monkeypatch.setattr(bot, '_finish_delivery', failed_save)
    asyncio.run(asyncio.wait_for(bot.handle(), timeout=3))
    assert len([m for m, _ in client.calls if m == 'sendMessage']) == 1
    with Session(service.store.engine) as session:
        assert session.scalar(select(OutboxRow.status)) == 'sending'
    service.store.recover()
    with Session(service.store.engine) as session:
        assert session.scalar(select(OutboxRow.status)) == 'uncertain'
    assert not asyncio.run(bot.deliver_one())


def test_health_reports_dead_background_task_without_private_exception(make_run_manager, caplog):
    setup = make_run_manager()
    setup.manager.settings.api_key = 'test-key'
    with TestClient(create_app(manager=setup.manager, background=False)) as client:
        async def fail():
            raise RuntimeError('PRIVATE TOKEN')

        async def simulate_failure():
            service = client.app.state.service
            task = asyncio.create_task(fail(), name='telegram-poller')
            client.app.state.tasks.append(task)
            task.add_done_callback(lambda done: background.observe_task(done, service.background_health, service.stopping))
            await asyncio.gather(task, return_exceptions=True)

        client.portal.call(simulate_failure)
        response = client.get('/health')
        assert response.status_code == 503
        assert response.json()['components']['telegram-poller'] == 'stopped'
        assert client.app.state.service.background_health['telegram-poller']['error_type'] == 'RuntimeError'
        assert 'PRIVATE TOKEN' not in caplog.text + response.text


def test_shutdown_interrupts_database_backoff():
    async def exercise():
        stop, health = asyncio.Event(), {}

        async def unavailable():
            stop.set()
            raise PoolTimeout('database unavailable')

        await asyncio.wait_for(background.run_loop('test', stop, unavailable, health), timeout=0.2)
        assert health['test']['status'] == 'retrying'

    asyncio.run(exercise())
