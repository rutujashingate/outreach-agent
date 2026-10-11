"""Check one-database configuration and real Postgres restart behavior.

Set RUN_POSTGRES_TESTS=1 with local PostgreSQL binaries installed to run the
integration checks. They start an isolated temporary database, never Supabase.
"""
import asyncio
from contextlib import asynccontextmanager
import os
import shutil
import socket
import subprocess
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.domain.workflow import ApprovalSubmission
from app.llm.client import FakeModelClient
from app.services.application import AgentService
from app.services.runtime import open_runtime
from app.settings import Settings
from app.storage.database import create_database
from app.storage.postgres import connection_urls, database_instance_lock, protect_tables


def test_one_supabase_url_selects_both_stores_without_exposing_password(monkeypatch):
    monkeypatch.setenv('OUTREACH_SUPABASE_DATABASE_URL', 'postgresql://postgres.project:private-password@host.example:5432/postgres')
    settings = Settings.from_env()
    assert settings.checkpoint_backend == 'postgres'
    assert settings.database_url.startswith('postgresql+psycopg://')
    assert settings.checkpoint_postgres_url.startswith('postgresql://')
    assert 'sslmode=require' in settings.database_url
    assert 'private-password' not in repr(settings) + settings.model_dump_json()
    assert Settings().checkpoint_backend == 'sqlite'


@pytest.mark.parametrize('value', [
    'https://project.supabase.co', 'postgresql://user:secret@host:6543/postgres',
    'postgresql://user:secret@host:5432/postgres?sslmode=disable',
    'postgresql://user:secret@host:5432/postgres?options=private-secret',
    'postgresql://user:secret@host:bad/postgres',
    'malformed-private-secret',
])
def test_bad_or_transaction_pooler_urls_fail_without_echoing_credentials(value):
    with pytest.raises(ValueError) as error:
        Settings(supabase_database_url=value)
    assert value not in str(error.value) and 'private-secret' not in str(error.value)


def test_database_settings_cannot_silently_split_supabase_state():
    with pytest.raises(ValueError, match='one URL'):
        Settings(supabase_database_url='postgresql://user:password@host:5432/postgres', database_url='sqlite:///other.db')


def test_connection_url_preserves_encoded_password_and_verified_ssl():
    app, checkpoint = connection_urls('postgresql://user:p%40ss%2Fword@host:5432/postgres?sslmode=verify-full&sslrootcert=/tmp/ca.pem')
    assert 'p%40ss%2Fword' in app and 'p%40ss%2Fword' in checkpoint
    assert 'sslmode=verify-full' in app


@pytest.fixture(scope='module')
def postgres_cluster(tmp_path_factory):
    if os.getenv('RUN_POSTGRES_TESTS') != '1':
        pytest.skip('Set RUN_POSTGRES_TESTS=1 to start a temporary local PostgreSQL server.')
    binary = shutil.which('pg_ctl')
    if not binary:
        pytest.fail('RUN_POSTGRES_TESTS requires pg_ctl and initdb on PATH.')
    folder = tmp_path_factory.mktemp('outreach-postgres')
    # Unix socket paths have a small length limit on macOS; TCP is loopback-only.
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    def run(args):
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    run([shutil.which('initdb'), '-D', str(folder/'data'), '-U', 'outreach_test', '--auth=trust', '--no-locale', '--encoding=UTF8'])
    run([binary, '-D', str(folder/'data'), '-l', str(folder/'server.log'), '-o', f'-h 127.0.0.1 -p {port} -k /tmp', '-w', 'start'])
    try:
        yield f'postgresql://outreach_test@127.0.0.1:{port}'
    finally:
        run([binary, '-D', str(folder/'data'), '-m', 'fast', '-w', 'stop'])


@pytest.fixture
def postgres_url(postgres_cluster):
    import psycopg
    database = 'test_' + uuid4().hex
    with psycopg.connect(postgres_cluster+'/postgres', autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE {database}')
    yield postgres_cluster+'/'+database+'?sslmode=disable'
    with psycopg.connect(postgres_cluster+'/postgres', autocommit=True) as connection:
        connection.execute(f'DROP DATABASE {database} WITH (FORCE)')


def test_postgres_queue_checkpoint_and_approval_survive_reopen(postgres_url, tmp_path, workflow_data):
    settings = Settings(supabase_database_url=postgres_url, data_dir=tmp_path, browser_enabled=False)
    first_client, second_client = FakeModelClient(workflow_data.responses), FakeModelClient([])
    @asynccontextmanager
    async def factory(client):
        yield client
    async def check():
        async with open_runtime(settings) as manager:
            manager.client_factory = lambda: factory(first_client)
            service = AgentService(manager)
            job = service.start(workflow_data.request, 'first')
            assert await service.execute_one()
            paused = service.state(job['run_id'])
            assert paused.awaiting_approval
            service.store.put('test:conversation', {'progress': 'kept'})
            with manager.repository.engine.connect() as connection:
                assert connection.execute(text('SELECT count(*) FROM outreach.checkpoints')).scalar() > 0
        async with open_runtime(settings) as manager:
            manager.client_factory = lambda: factory(second_client)
            service = AgentService(manager)
            assert service.store.get('test:conversation') == {'progress': 'kept'}
            assert service.state(job['run_id']).awaiting_approval
            item = paused.state.approval_requests[0]
            service.decisions(job['run_id'], ApprovalSubmission(decisions=[{
                'prospect_id':'p1', 'version':item.version, 'fingerprint':item.fingerprint, 'action':'approve'}]), 'decision')
            assert await service.execute_one()
            assert service.state(job['run_id']).state.outcomes['p1'].status == 'approved'
            assert manager.repository.run(job['run_id'])['model_calls'] == 6
            with manager.repository.engine.connect() as connection:
                tables = connection.execute(text("SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='outreach'")).all()
                assert len(tables) >= 18 and all(row[1] for row in tables)
                assert connection.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")).scalar() == 0
        assert len(first_client.calls) == 6 and second_client.calls == []
    asyncio.run(check())
    assert not (tmp_path/'relationships.sqlite3').exists() and not (tmp_path/'checkpoints.sqlite3').exists()


def test_database_lock_blocks_second_service_and_releases_after_close(postgres_url):
    app, _ = connection_urls(postgres_url)
    first, second = create_database(app, private_schema=True), create_database(app, private_schema=True)
    try:
        with database_instance_lock(first):
            with pytest.raises(RuntimeError, match='Another outreach service'):
                with database_instance_lock(second):
                    pytest.fail('A second worker must not start.')
        with database_instance_lock(second):
            pass
    finally:
        first.dispose(); second.dispose()


def test_saved_gmail_draft_is_reused_after_postgres_restart(postgres_url, tmp_path, workflow_data):
    from langgraph.runtime import Runtime
    from app.agent.context import WorkflowContext
    from app.agent.nodes.external import external_node
    from app.connectors.gmail.client import FakeGmailClient
    settings = Settings(supabase_database_url=postgres_url, data_dir=tmp_path, browser_enabled=False)
    model, gmail = FakeModelClient(workflow_data.responses), FakeGmailClient()
    @asynccontextmanager
    async def factory():
        yield model
    async def check():
        async with open_runtime(settings) as manager:
            manager.client_factory, manager.gmail = factory, gmail
            service = AgentService(manager)
            request = workflow_data.request.model_copy(update={'gmail_action': 'draft'})
            job = service.start(request, 'requested-draft')
            await service.execute_one()
            saved = service.state(job['run_id']).state
            assert saved.outcomes['p1'].status == 'drafted'
        async with open_runtime(settings) as manager:
            service = AgentService(manager)
            state = service.state(job['run_id']).state
            assert state.outcomes == saved.outcomes
            # Replay the boundary after losing the node's in-memory outcome.
            # The durable ledger must return the first draft, not create another.
            state.outcomes = {}
            context = WorkflowContext(model, manager.repository, settings.limits, gmail=gmail)
            replay = await external_node(state, Runtime(context=context))
            assert replay['outcomes'] == saved.outcomes
            assert service.overview()['stats']['drafts'] == 1
        assert [kind for kind, _ in gmail.calls] == ['draft']
        assert len(model.calls) == 6
    asyncio.run(check())


def test_private_tables_have_no_data_api_role_access(postgres_url):
    app, _ = connection_urls(postgres_url)
    engine = create_database(app, private_schema=True)
    try:
        with engine.begin() as connection:
            for role in ['anon', 'authenticated', 'service_role']:
                if not connection.execute(text('SELECT 1 FROM pg_roles WHERE rolname=:role'), {'role':role}).scalar():
                    connection.exec_driver_sql(f'CREATE ROLE {role} NOLOGIN')
                connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA outreach TO {role}')
                connection.exec_driver_sql(f'GRANT SELECT ON ALL TABLES IN SCHEMA outreach TO {role}')
        protect_tables(engine)
        with engine.connect() as connection:
            for role in ['anon', 'authenticated', 'service_role']:
                assert not connection.execute(text("SELECT has_schema_privilege(:role, 'outreach', 'USAGE')"), {'role':role}).scalar()
                assert not connection.execute(text("SELECT has_table_privilege(:role, 'outreach.service_values', 'SELECT')"), {'role':role}).scalar()
    finally:
        engine.dispose()
