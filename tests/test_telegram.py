"""Telegram can drive the real graph with fake browser, model and Gmail tools."""
import asyncio
from copy import deepcopy
from sqlalchemy import select
from sqlalchemy.orm import Session
import pytest
from app.connectors.telegram.bot import TelegramBot
from app.connectors.telegram.client import FakeTelegram, RateLimited
from app.services.application import AgentService
from app.storage.control import InboxRow, OutboxRow
from app.settings import Settings


def incoming(update_id,text,owner=123):
    return {'update_id':update_id,'message':{'from':{'id':owner},'chat':{'id':owner,'type':'private'},'text':text}}


def callback(update_id, token, owner=123):
    return {'update_id':update_id,'callback_query':{'id':str(update_id),'from':{'id':owner},'data':token,
        'message':{'chat':{'id':owner,'type':'private'}}}}


def test_unauthorized_group_and_duplicate_updates_are_ignored(make_run_manager):
    setup=make_run_manager();store=AgentService(setup.manager).store
    group=incoming(2,'/new');group['message']['chat']['type']='group'
    allowed=incoming(3,'/new')
    store.accept_updates([incoming(1,'/new',999),group,allowed,allowed],123)
    with Session(store.engine) as session: assert len(list(session.scalars(select(InboxRow))))==1
    assert store.get('telegram_offset')['next']==4


def test_new_bot_instance_continues_saved_conversation(make_run_manager):
    setup=make_run_manager(settings=Settings(telegram_owner_id=123))
    service=AgentService(setup.manager)
    async def exercise():
        first=TelegramBot(service,FakeTelegram())
        service.store.accept_updates([incoming(1,'/new'),incoming(2,'Find AI startups')],123)
        assert await first.process_one() and await first.process_one()
        second=TelegramBot(AgentService(setup.manager),FakeTelegram())
        service.store.accept_updates([incoming(2,'Find AI startups'),incoming(3,'I build observability tools.')],123)
        assert await second.process_one()
        while await second.deliver_one(): pass
        texts=[payload.get('text','') for method,payload in second.client.calls if method=='sendMessage']
        assert any('research' in text.lower() for text in texts)
        assert not await second.process_one()
    asyncio.run(exercise())


@pytest.mark.parametrize('source_mode', ['public', 'file'])
def test_guided_telegram_browser_gmail_flow_and_dashboard_shared_choices(tmp_path, source_mode):
    from app.demo import build_demo_manager
    settings=Settings(data_dir=tmp_path,checkpoint_backend='memory',demo=True,telegram_owner_id=123)
    manager=build_demo_manager(settings=settings);service=AgentService(manager);client=FakeTelegram();bot=TelegramBot(service,client)
    counter=0
    async def dispatch(text=None, button=None, file=False):
        nonlocal counter
        counter+=1
        update=incoming(counter,text) if button is None else callback(counter,button)
        if file:
            update['message'].pop('text', None)
            update['message']['document']={'file_id':'notes','file_name':'notes.txt'}
        bot.store.accept_updates([update],123);await bot.process_one()
        while await bot.deliver_one(): pass
    def button(title):
        for method,payload in reversed(client.calls):
            for row in payload.get('reply_markup',{}).get('inline_keyboard',[]):
                for entry in row:
                    if entry['text']==title: return entry['callback_data']
        raise AssertionError(f'Missing button {title}')
    async def check():
        await dispatch('/new');await dispatch('Find professors studying AI observability');await dispatch('I am exploring PhD supervision.')
        if source_mode == 'file':
            client.files['notes']=b'Example University. Ada Example studies AI observability. https://example.com/lab'
            await dispatch(file=True)
            await dispatch(button=button('Use as research'))
            await dispatch(button=button('Uploaded files'))
            await dispatch('Example University | professor@example.com')
        else:
            await dispatch(button=button('Public URLs'));await dispatch('https://example.com/lab');await dispatch('-')
        await dispatch(button=button('Gmail draft'));await dispatch(button=button('Start run'))
        runs=service.list_runs()['items'];assert len(runs)==1
        run_id=runs[0]['run_id'];assert service.manager.repository.run(run_id)['status']=='queued'
        if source_mode == 'file': await service.execute_one()  # Reading is queued before outreach.
        await service.execute_one(); assert service.state(run_id).awaiting_approval
        if source_mode == 'file':
            assert service.state(run_id).state.documents[0].filename == 'notes.txt'
        await dispatch('/review '+run_id)
        approve=button('Approve draft');await dispatch(button=approve)
        assert service.details(run_id)['choices']['p1']['action']=='approve'
        # Dashboard submits the choice made in Telegram; no second research.
        service.submit_choices(run_id,'dashboard:submit');await service.execute_one()
        assert service.state(run_id).state.outcomes['p1'].status=='drafted'
        await dispatch(button=approve)
        assert len([c for c in manager.gmail.calls if c[0]=='draft'])==1
        assert manager.repository.run(run_id)['model_calls']==6
    try: asyncio.run(check())
    finally: manager.repository.engine.dispose()


def test_long_messages_fit_telegram_and_failed_part_blocks_approval_button(make_run_manager):
    setup=make_run_manager(settings=Settings(telegram_owner_id=123));service=AgentService(setup.manager)
    client=FakeTelegram();bot=TelegramBot(service,client);bot.message_key='long'
    bot.say('😀'*5000,[('Approve',{'submit':'run'})])
    with Session(service.store.engine) as session:
        rows=list(session.scalars(select(OutboxRow).order_by(OutboxRow.key)))
        assert len(rows)>1 and all(len(r.payload['text'].encode('utf-16-le'))//2<=4096 for r in rows)
        assert all('reply_markup' not in r.payload for r in rows[:-1])
    from app.connectors.search import ToolError
    async def fail(*args,**kwargs): raise ToolError('uncertain')
    client.call=fail
    async def check():
        while await bot.deliver_one(): pass
    asyncio.run(check())
    with Session(service.store.engine) as session:
        statuses=list(session.scalars(select(OutboxRow.status)))
        assert statuses[0]=='uncertain' and all(s=='blocked' for s in statuses[1:])


def test_rate_limit_schedules_retry_without_losing_message(make_run_manager):
    setup=make_run_manager(settings=Settings(telegram_owner_id=123));service=AgentService(setup.manager)
    client=FakeTelegram();bot=TelegramBot(service,client);bot.message_key='limit';bot.say('Hello')
    async def limited(*args,**kwargs): raise RateLimited(10)
    client.call=limited
    asyncio.run(bot.deliver_one())
    with Session(service.store.engine) as session:
        row=session.scalar(select(OutboxRow));assert row.status=='pending' and row.retry_at>0
