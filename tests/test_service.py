"""Check saved jobs, approval sharing, cancellation and restart behavior."""
import asyncio
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.services.application import AgentService
from app.services.runs import RunConflict
from app.domain.workflow import ApprovalDecision
from app.storage.control import ControlStore, JobRow, RunMeta
from app.storage.models import RunRow


def decision(response, action='approve'):
    item = response.state.approval_requests[0]
    return ApprovalDecision(prospect_id=item.prospect.id, version=item.version, fingerprint=item.fingerprint, action=action)


def test_jobs_acknowledge_before_model_and_replays_do_not_repeat(make_run_manager, workflow_data):
    setup = make_run_manager(); service = AgentService(setup.manager)
    job = service.start(workflow_data.request, 'telegram:1', 'telegram')
    assert setup.client.calls == []
    assert service.start(workflow_data.request, 'telegram:1') == job
    asyncio.run(service.execute_one())
    response = service.state(job['run_id']); assert response.awaiting_approval
    service.stage_decision(job['run_id'], decision(response))
    first = service.submit_choices(job['run_id'], 'web:submit')
    with pytest.raises(RunConflict): service.submit_choices(job['run_id'], 'telegram:other')
    asyncio.run(service.execute_one())
    assert service.state(job['run_id']).state.outcomes['p1'].status == 'approved'
    assert len(setup.client.calls) == 6
    assert service.store.find_job('web:submit')['id'] == first['id']
    assert service.submit_choices(job['run_id'], 'web:submit')['id'] == first['id']
    with pytest.raises(RunConflict): service.stage_decision(job['run_id'], decision(response))


def test_pause_queue_and_cancel_prevents_any_model_call(make_run_manager, workflow_data):
    setup = make_run_manager(); service = AgentService(setup.manager)
    job = service.start(workflow_data.request, 'start')
    service.store.put('queue', {'paused': True})
    assert not asyncio.run(service.execute_one())
    service.cancel(job['run_id'])
    service.store.put('queue', {'paused': False})
    assert not asyncio.run(service.execute_one())
    assert service.state(job['run_id']).state.current_step == 'cancelled'
    assert setup.client.calls == []


def test_cancellation_during_call_stops_before_next_node(make_run_manager, workflow_data):
    setup = make_run_manager(); service = AgentService(setup.manager)
    original = setup.client.generate_structured
    job = service.start(workflow_data.request, 'start')
    async def interrupted(**kwargs):
        value = await original(**kwargs)
        service.cancel(job['run_id'])
        return value
    setup.client.generate_structured = interrupted
    asyncio.run(service.execute_one())
    assert service.state(job['run_id']).state.current_step == 'cancelled'
    assert len(setup.client.calls) == 1
    assert setup.gmail.calls == []


def test_recovery_marks_abandoned_jobs_and_retains_queued_work(make_run_manager, workflow_data):
    setup = make_run_manager(); service = AgentService(setup.manager)
    first = service.start(workflow_data.request, 'first')
    service.store.claim()
    row = service.state(first['run_id']).state
    setup.repository.save_run(row, 'running')
    second = service.start(workflow_data.request, 'second')
    ControlStore(setup.repository.engine).recover()
    assert service.store.find_job('first')['status'] == 'interrupted'
    assert service.store.find_job('second')['status'] == 'queued'
    assert setup.repository.run(first['run_id'])['status'] == 'failed'
    with Session(setup.repository.engine) as session:
        assert session.get(RunRow, first["run_id"]).lease_until == 0


def test_restart_reuses_pending_approval_without_new_model_calls(tmp_path, workflow_data):
    from app.storage.database import create_database
    from app.storage.repository import Repository
    from app.storage.checkpoints import open_checkpointer
    from app.services.runs import RunManager
    from app.llm.client import FakeModelClient
    from app.settings import Settings
    from contextlib import asynccontextmanager
    settings = Settings(data_dir=tmp_path)
    repository = Repository(create_database(f'sqlite:///{tmp_path / "relationships.sqlite3"}'))
    first, second = FakeModelClient(workflow_data.responses), FakeModelClient([])
    def factory(client):
        @asynccontextmanager
        async def make(): yield client
        return make
    async def run():
        async with open_checkpointer(settings) as cp:
            service = AgentService(RunManager(repository, cp, settings=settings, client_factory=factory(first)))
            job = service.start(workflow_data.request, 'start')
            await service.execute_one()
            service.stage_decision(job['run_id'], decision(service.state(job['run_id'])))
        async with open_checkpointer(settings) as cp:
            service = AgentService(RunManager(repository, cp, settings=settings, client_factory=factory(second)))
            service.store.recover()
            service.submit_choices(job['run_id'], 'submit')
            await service.execute_one()
            assert service.state(job['run_id']).state.outcomes['p1'].status == 'approved'
    try: asyncio.run(run())
    finally: repository.engine.dispose()
    assert len(first.calls) == 6 and second.calls == []


def test_statistics_count_confirmed_actions_not_approvals(make_run_manager, workflow_data):
    setup = make_run_manager(); service = AgentService(setup.manager)
    request = workflow_data.request.model_copy(update={'gmail_action':'draft'})
    job = service.start(request, 'start')
    before = service.overview()['stats']
    assert before['drafts'] == 0 and before['pending_approvals'] == 0
    asyncio.run(service.execute_one())
    after = service.overview()['stats']
    assert after['drafts'] == 1 and after['sent'] == 0 and after['model_calls'] == 6
    assert service.overview()['job_counts'] == {'completed': 1}
    assert len(service.details(job['run_id'])['events']) <= 50


def test_current_node_is_visible_while_model_call_is_running(make_run_manager, workflow_data):
    setup = make_run_manager(); service = AgentService(setup.manager)
    job = service.start(workflow_data.request, 'start')
    original = setup.client.generate_structured
    steps = []
    async def inspect(**kwargs):
        steps.append(service.details(job['run_id'])['current_step'])
        return await original(**kwargs)
    setup.client.generate_structured = inspect
    asyncio.run(service.execute_one())
    assert steps == ['interpret_goal', 'research', 'qualification', 'strategy', 'writing', 'review']


def test_reply_checks_process_five_new_messages_and_resume_the_same_thread(make_run_manager):
    import base64
    from app.storage.models import ActionRow
    setup = make_run_manager(); service = AgentService(setup.manager)
    email = 'contact@example.com'
    setup.gmail.threads['thread'] = {'messages': [{'id': str(i), 'payload': {'mimeType':'text/plain',
        'headers':[{'name':'From','value':email}],
        'body':{'data':base64.urlsafe_b64encode(b'Please unsubscribe me.').decode()}}} for i in range(7)]}
    with Session(setup.repository.engine) as session, session.begin():
        session.add(ActionRow(key='tracked',email=email,kind='send',status='done',payload={'outcome':{'thread_id':'thread'}}))
    assert asyncio.run(service.check_replies()) == 5
    assert asyncio.run(service.check_replies()) == 2
    assert asyncio.run(service.check_replies()) == 0
    assert service.overview()['stats']['replies'] == 7
    assert setup.client.calls == []


def test_reply_scans_are_bounded_and_rotate_through_history(make_run_manager):
    from app.storage.models import ActionRow
    setup = make_run_manager(); service = AgentService(setup.manager)
    with Session(setup.repository.engine) as session, session.begin():
        for i in range(25):
            key = f'{i:03}'
            setup.gmail.threads[key] = {'messages': []}
            session.add(ActionRow(key=key,email='contact@example.com',kind='draft',status='done',payload={'outcome':{'thread_id':key}}))
    assert asyncio.run(service.check_replies()) == 0
    assert len(setup.gmail.calls) == 20
    assert asyncio.run(service.check_replies()) == 0
    assert len(setup.gmail.calls) == 25


def test_every_prospect_needs_a_choice_before_the_batch_resumes(make_run_manager, workflow_data):
    from copy import deepcopy
    import json
    responses = deepcopy(workflow_data.responses)
    second = deepcopy(responses[1]['prospects'][0])
    second.update(id='p2', company_name='Second Example AI')
    responses[1]['prospects'].append(second)
    script = responses[:2]
    for record in responses[2:]:
        script.extend([record, {**record, 'prospect_id':'p2'}])
    request = workflow_data.request.model_copy(update={
        'research_material':json.dumps(responses[1]),
        'recipients':{**workflow_data.request.recipients, 'p2':workflow_data.request.recipients['p1'].model_copy(update={'email':'second@example.com'})}})
    setup = make_run_manager(responses=script); service = AgentService(setup.manager)
    job = service.start(request, 'start'); asyncio.run(service.execute_one())
    items = service.state(job['run_id']).state.approval_requests
    assert len(items) == 2
    def choose(item, action):
        return ApprovalDecision(prospect_id=item.prospect.id, version=item.version, fingerprint=item.fingerprint, action=action)
    service.stage_decision(job['run_id'], choose(items[0], 'approve'))
    with pytest.raises(ValueError, match='each pending prospect'):
        service.submit_choices(job['run_id'], 'incomplete')
    assert service.store.find_job('incomplete') is None
    service.stage_decision(job['run_id'], choose(items[1], 'reject'))
    service.submit_choices(job['run_id'], 'complete'); asyncio.run(service.execute_one())
    outcomes = service.state(job['run_id']).state.outcomes
    assert outcomes['p1'].status == 'approved' and outcomes['p2'].status == 'rejected'
