"""Protect persisted data and record an in-flight action before cancellation."""
import asyncio
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import pytest

from app.services.instance import instance_lock
from app.services.application import AgentService
from app.storage.database import create_database
from app.storage.control import ControlStore
from app.storage.repository import Repository
from app.domain.workflow import ApprovalSubmission


def test_second_service_cannot_use_the_same_directory(tmp_path):
    with instance_lock(tmp_path):
        with pytest.raises(RuntimeError,match='Another outreach service'):
            with instance_lock(tmp_path): pass
    with instance_lock(tmp_path): pass


def test_restart_after_claim_before_execution_allows_explicit_retry(make_run_manager, workflow_data):
    setup = make_run_manager(); service = AgentService(setup.manager)
    job = service.start(workflow_data.request, 'start')
    service.store.claim()
    service.store.recover()
    assert setup.repository.run(job['run_id'])['status'] == 'failed'
    service.retry(job['run_id'], 'retry')
    asyncio.run(service.execute_one())
    assert service.state(job['run_id']).awaiting_approval


def test_migration_adopts_existing_contacts_and_is_repeatable(tmp_path):
    path=tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE contacts (email VARCHAR(254) PRIMARY KEY, opted_out BOOLEAN NOT NULL, active_conversation BOOLEAN NOT NULL, last_contact_at VARCHAR(40), reconnect_at VARCHAR(40))')
        db.execute('INSERT INTO contacts VALUES (?, 1, 0, NULL, NULL)',('blocked@example.com',))
    for _ in range(2):
        engine=create_database(f'sqlite:///{path}')
        try:
            assert Repository(engine).contact('blocked@example.com')['opted_out']
            ControlStore(engine).put('queue',{'paused':True})
        finally: engine.dispose()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='001_connected_service'


def test_cancelling_during_gmail_records_the_completed_action(make_run_manager,workflow_data):
    setup=make_run_manager();service=AgentService(setup.manager)
    job=service.start(workflow_data.request.model_copy(update={'gmail_action':'draft'}),'start')
    async def exercise():
        await service.execute_one()
        item=service.state(job['run_id']).state.approval_requests[0]
        service.decisions(job['run_id'],ApprovalSubmission(decisions=[{'prospect_id':'p1','version':item.version,'fingerprint':item.fingerprint,'action':'approve'}]),'approve')
        original=setup.gmail.create_draft
        async def create(*args):
            service.cancel(job['run_id'])
            return await original(*args)
        setup.gmail.create_draft=create
        await service.execute_one()
        assert service.state(job['run_id']).state.current_step=='cancelled'
        assert service.overview()['stats']['drafts']==1
        assert len([call for call in setup.gmail.calls if call[0]=='draft'])==1
    asyncio.run(exercise())
