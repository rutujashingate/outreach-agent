"""Exercise the authenticated, asynchronous dashboard API and shared controls."""
from fastapi.testclient import TestClient
import pytest
from app.main import create_app
from app.settings import Settings
from app.services.limits import Limits


def client_for(setup):
    setup.manager.settings.api_key = 'test-key'
    return TestClient(create_app(manager=setup.manager, background=False), headers={'X-API-Key':'test-key'})


def execute(client): client.portal.call(client.app.state.service.execute_one)


@pytest.mark.parametrize('slow_area', ['overview', 'session_lookup'])
def test_slow_database_read_leaves_health_requests_responsive(make_run_manager, monkeypatch, slow_area):
    """A waiting dashboard read must let another request finish in the meantime."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    setup = make_run_manager()
    entered, release = Event(), Event()
    with client_for(setup) as client:
        if slow_area == 'overview':
            target, name, path = client.app.state.service, 'overview', '/api/overview'
            original = target.overview
        else:
            client.headers.pop('X-API-Key')
            target, name, path = client.app.state.auth, 'session', '/api/connectors'
            original = lambda *args: ('test-session', {'csrf': 'test-csrf'})
        def waiting_read(*args):
            entered.set()
            assert release.wait(timeout=5)
            return original(*args)
        monkeypatch.setattr(target, name, waiting_read)
        with ThreadPoolExecutor(max_workers=2) as threads:
            pending = threads.submit(client.get, path)
            try:
                assert entered.wait(timeout=2)
                assert threads.submit(client.get, '/health').result(timeout=2).status_code == 200
            finally:
                release.set()
            assert pending.result(timeout=5).status_code == 200


def test_api_queues_runs_and_resumes_same_run(make_run_manager, workflow_data):
    setup=make_run_manager()
    with client_for(setup) as client:
        made=client.post('/api/runs',json=workflow_data.request.model_dump(),headers={'Idempotency-Key':'start'})
        assert made.status_code==202 and setup.client.calls==[]
        run_id=made.json()['run_id']; execute(client)
        saved=client.get('/api/runs/'+run_id).json()
        assert saved['awaiting_approval']
        item=saved['state']['approval_requests'][0]
        choice={'prospect_id':'p1','version':item['version'],'fingerprint':item['fingerprint'],'action':'approve'}
        assert client.post(f'/api/runs/{run_id}/choices',json=choice).status_code==200
        assert client.post(f'/api/runs/{run_id}/submit').status_code==202
        execute(client)
        assert client.get('/api/runs/'+run_id).json()['state']['outcomes']['p1']['status']=='approved'
        assert len(setup.client.calls)==6
        assert client.post(f'/api/runs/{run_id}/choices',json=choice).status_code==409


@pytest.mark.parametrize('changes',[{'goal':' '},{'unknown':True},{'use_search':'true'},
    {'recipients':{'p1':{'email':'invalid'}}},{'gmail_action':'automatic'}, {'gmail_action':'send'},
    {'seed_urls':['file:///tmp/test']}])
def test_bad_requests_never_queue_or_call_models(make_run_manager,workflow_data,changes):
    setup=make_run_manager()
    with client_for(setup) as client:
        assert client.post('/api/runs',json={**workflow_data.request.model_dump(),**changes}).status_code==422
    assert setup.client.calls==[]


def test_all_data_and_actions_require_login_and_mutations_require_csrf(make_run_manager,workflow_data):
    setup=make_run_manager(settings=Settings(checkpoint_backend='memory',owner_password='test-password'))
    with TestClient(create_app(manager=setup.manager,background=False)) as client:
        for path in ['/api/runs','/api/overview','/api/connectors']:
            assert client.get(path).status_code==401
        login=client.post('/auth/login',json={'password':'test-password'})
        assert login.status_code==200
        assert 'HttpOnly' in login.headers['set-cookie']
        csrf=login.json()['csrf']
        assert client.get('/api/overview').status_code==200
        assert client.put('/api/queue',json={'paused':True}).status_code==403
        assert client.put('/api/queue',json={'paused':True},headers={'X-CSRF-Token':csrf,'Origin':'https://evil.example'}).status_code==403
        assert client.put('/api/queue',json={'paused':True},headers={'X-CSRF-Token':csrf}).status_code==200
        assert client.post('/auth/logout',headers={'X-CSRF-Token':csrf}).status_code==200
        assert client.get('/api/overview').status_code==401


def test_missing_api_key_is_not_an_anonymous_fallback(make_run_manager):
    setup=make_run_manager(settings=Settings(checkpoint_backend='memory',owner_password='secret'))
    with TestClient(create_app(manager=setup.manager,background=False)) as client:
        assert client.get('/api/overview',headers={'X-API-Key':''}).status_code==401
        assert client.get('/runs').status_code==404
        assert client.post('/outreach',json={'goal':'old path'}).status_code==404


def test_request_limit_and_invalid_run(make_run_manager):
    setup=make_run_manager(settings=Settings(checkpoint_backend='memory',limits=Limits(max_requests_per_minute=2)))
    with client_for(setup) as client:
        assert client.get('/api/runs/unknown').status_code==404
        assert client.get('/api/runs').status_code==200
        assert client.get('/api/runs').status_code==429


def test_failed_job_retains_run_id_and_generic_error(make_run_manager,workflow_data):
    setup=make_run_manager(settings=Settings(checkpoint_backend='memory',limits=Limits(max_model_calls=1)))
    with client_for(setup) as client:
        made=client.post('/api/runs',json=workflow_data.request.model_dump()).json()
        execute(client)
        saved=client.get('/api/runs/'+made['run_id']).json()
        assert saved['status']=='failed'
        assert saved['usage']['model_calls']==1
        assert client.get('/api/overview').json()['stats']['failed']==1


def test_validation_does_not_echo_password_input(make_run_manager):
    with client_for(make_run_manager()) as client:
        response = client.post('/auth/login', json={'password': {'secret': 'do-not-echo'}})
        assert response.status_code == 422
        assert 'do-not-echo' not in response.text
