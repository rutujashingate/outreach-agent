"""Test terminal interactions using real local graphs and fake model responses."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError

from app import cli
from app.models.client import FakeModelClient
from app.models.schemas import EmailDraft, Prospect, Qualification, OutreachStrategy, ReviewResult
from app.models.workflow import WorkflowState
from app.orchestration.runtime import open_runtime
from app.settings import Settings


def answers(*lines):
    """Supply the lines a person would type, without needing an actual terminal."""
    waiting = iter(lines)
    return lambda prompt: next(waiting)


def test_terminal_questions_create_a_validated_request_and_preserve_notes():
    request = cli.collect_request(read=answers(
        '  Find AI startups  ', 'Example User', '', 'My product background', '.', 'no',
        'Example AI', '', 'Source: https://example.com', '.', 'Example AI', 'contact@example.com', '', 'none',
    ))
    assert request.goal == 'Find AI startups'
    assert request.sender.name == 'Example User' and request.sender.email is None
    assert request.sender.context == 'My product background'
    assert request.research_material == 'Example AI\n\nSource: https://example.com'
    assert request.recipients['Example AI'].email == 'contact@example.com'
    assert not request.use_search and request.gmail_action == 'none'


def test_invalid_menu_request_never_calls_the_workflow(make_run_manager, capsys):
    setup = make_run_manager()
    asyncio.run(cli.interact(setup.manager, read=answers(
        '1', '   ', '', '', '.', 'no', '.', '', 'none', '0',
    )))
    assert setup.client.calls == [] and setup.repository.list_runs() == []
    assert 'Invalid goal:' in capsys.readouterr().out


def test_cli_choices_retry_unknown_answers_and_default_to_later(capsys):
    assert cli.choose('Decision', ('approve', 'later'), default='later',
                      read=answers('unknown', '')) == 'later'
    assert 'Choose one of:' in capsys.readouterr().out


def test_multiline_edit_keeps_existing_text_when_no_replacement_is_entered():
    assert cli.read_text('Body', default='First line\n\nLast line', read=answers('.')) == 'First line\n\nLast line'


@pytest.mark.parametrize('action,status', [('approve', 'approved'), ('reject', 'rejected')])
def test_cli_decisions_resume_the_same_run_without_research_repeating(make_run_manager, workflow_data, action, status, capsys):
    setup = make_run_manager()
    async def exercise():
        response = await setup.manager.start(workflow_data.request)
        run_id = response.state.run_id
        result = await cli.review_run(setup.manager, run_id, read=answers(action))
        assert result.state.run_id == run_id and result.state.outcomes['p1'].status == status
        assert len(setup.client.calls) == 6 and not result.awaiting_approval
        assert setup.gmail.calls == []
    asyncio.run(exercise())
    output = capsys.readouterr().out
    assert 'To: contact@example.com' in output and 'Subject:' in output
    assert 'Qualification score: 86' in output and 'Research and sources:' in output


def test_cli_edit_returns_changed_content_for_fresh_approval(make_run_manager, workflow_data):
    setup = make_run_manager(responses=workflow_data.responses + [workflow_data.responses[-1]])
    async def exercise():
        response = await setup.manager.start(workflow_data.request)
        previous = response.state.approval_requests[0]
        result = await cli.review_run(setup.manager, response.state.run_id,
                                     read=answers('edit', 'Updated subject', 'Updated message.', '.'))
        assert result.awaiting_approval and len(setup.client.calls) == 7
        current = result.state.approval_requests[0]
        assert current.version == 2 and current.fingerprint != previous.fingerprint
        assert current.draft.subject == 'Updated subject' and current.draft.body == 'Updated message.'
        assert result.state.human_decisions == {} and setup.gmail.calls == []
    asyncio.run(exercise())


def test_later_leaves_every_decision_unsubmitted(make_run_manager, records, workflow_data):
    # Two prospects prove that approving the first locally cannot submit a
    # partial batch when the person chooses "later" for the second.
    prospect = records[Prospect]
    second = prospect.model_copy(update={'id': 'p2', 'company_name': 'Second AI'})
    responses = [workflow_data.responses[0], {'prospects': [prospect.model_dump(), second.model_dump()]}]
    for record_type in (Qualification, OutreachStrategy, EmailDraft, ReviewResult):
        responses.extend([records[record_type].model_dump(), records[record_type].model_copy(update={'prospect_id': 'p2'}).model_dump()])
    request = workflow_data.request.model_copy(update={
        'research_material': prospect.model_dump_json() + '\n' + second.model_dump_json(),
        'recipients': {'p1': workflow_data.request.recipients['p1'],
                       'p2': workflow_data.request.recipients['p1'].model_copy(update={'email': 'second@example.com'})},
    })
    setup = make_run_manager(responses=responses)
    async def exercise():
        response = await setup.manager.start(request)
        assert len(response.state.approval_requests) == 2
        assert await cli.review_run(setup.manager, response.state.run_id, read=answers('approve', 'later')) is None
        saved = setup.manager.get(response.state.run_id)
        assert saved.awaiting_approval and saved.state.human_decisions == {} and setup.gmail.calls == []
    asyncio.run(exercise())


def test_demo_menu_runs_drafts_reads_events_and_lists_runs(capsys):
    async def exercise():
        async with cli.cli_manager(demo=True) as manager:
            await cli.interact(manager, demo=True, read=answers('1', '4', '', 'approve', '6', '', '2', '0'))
            assert [name for name, _ in manager.gmail.calls] == ['draft']
    asyncio.run(exercise())
    output = capsys.readouterr().out
    assert 'DEMO: fictional data' in output and 'awaiting_approval' in output
    assert 'p1: drafted' in output and 'node_start' in output and 'Goodbye.' in output


def test_cli_view_and_unknown_run_errors_are_understandable(make_run_manager, workflow_data, capsys):
    setup = make_run_manager()
    async def exercise():
        response = await setup.manager.start(workflow_data.request)
        await cli.interact(setup.manager, read=answers('3', 'f'*32, '3', response.state.run_id, '0'))
    asyncio.run(exercise())
    output = capsys.readouterr().out
    assert 'Unknown run identifier' in output and 'Subject:' in output


def test_config_check_hides_keys_and_connection_passwords(monkeypatch, capsys):
    monkeypatch.setenv('OUTREACH_MODEL_PROVIDER', 'groq')
    monkeypatch.setenv('GROQ_API_KEY', 'test-only-private-key')
    monkeypatch.setenv('OUTREACH_DATABASE_URL', 'postgresql+psycopg://user:private-password@localhost/example')
    assert cli.main(['--check-config']) == 0
    output = capsys.readouterr().out
    assert 'GROQ_API_KEY: configured' in output and 'keys have not been authenticated' in output
    assert 'private-key' not in output and 'private-password' not in output


def test_config_check_requires_only_the_selected_model_settings(monkeypatch, capsys):
    monkeypatch.setenv('OUTREACH_MODEL_PROVIDER', 'groq')
    assert cli.main(['--check-config']) == 1
    assert 'GROQ_API_KEY: MISSING' in capsys.readouterr().out
    monkeypatch.setenv('GROQ_API_KEY', 'test-only')
    assert cli.main(['--check-config']) == 0
    output = capsys.readouterr().out
    assert 'SQLite at' in output and 'OPENAI_API_KEY' not in output


def test_eof_exits_the_cli_cleanly(monkeypatch, capsys):
    def closed(prompt):
        raise EOFError
    monkeypatch.setattr('builtins.input', closed)
    assert cli.main(['--demo']) == 0
    assert 'Input closed' in capsys.readouterr().out


def test_unexpected_startup_errors_do_not_print_sensitive_details(monkeypatch, capsys):
    @asynccontextmanager
    async def broken_runtime(**kwargs):
        raise RuntimeError('private-connection-details')
        yield
    monkeypatch.setattr(cli, 'cli_manager', broken_runtime)
    assert cli.main([]) == 1
    assert 'private-connection-details' not in capsys.readouterr().out


def test_shared_runtime_preserves_paused_runs_across_cli_sessions(tmp_path, workflow_data):
    settings = Settings(data_dir=tmp_path, checkpoint_backend='sqlite')
    @asynccontextmanager
    async def first_client():
        yield FakeModelClient(workflow_data.responses)
    unused_client = FakeModelClient([])
    @asynccontextmanager
    async def no_new_model_calls():
        yield unused_client
    async def exercise():
        async with open_runtime(settings) as manager:
            manager.client_factory = first_client
            response = await manager.start(workflow_data.request)
            run_id = response.state.run_id
            assert response.awaiting_approval
        assert (tmp_path / 'relationships.sqlite3').is_file() and (tmp_path / 'checkpoints.sqlite3').is_file()
        async with open_runtime(settings) as manager:
            manager.client_factory = no_new_model_calls
            assert manager.repository.list_runs()[0]['run_id'] == run_id
            result = await cli.review_run(manager, run_id, read=answers('approve'))
            assert result.state.outcomes['p1'].status == 'approved'
            assert unused_client.calls == []
    asyncio.run(exercise())


def test_run_list_excludes_reply_budget_records_and_limits_results(make_run_manager):
    setup = make_run_manager()
    setup.repository.save_run(WorkflowState(run_id='a'*32, goal='First goal'), 'paused')
    setup.repository.save_run(WorkflowState(run_id='b'*32, goal='Second goal'), 'completed')
    setup.repository.save_run(WorkflowState(run_id='c'*64, goal='Reply budget record'), 'completed')
    assert [run['goal'] for run in setup.repository.list_runs()] == ['First goal', 'Second goal']
    assert len(setup.repository.list_runs(limit=1)) == 1
    with pytest.raises(ValueError):
        setup.repository.list_runs(limit=101)


def test_cancelled_workflow_can_be_inspected_and_retried(make_run_manager, workflow_data):
    entered = asyncio.Event()
    class WaitingClient:
        async def generate_structured(self, **kwargs):
            entered.set()
            await asyncio.Future()
    setup = make_run_manager(client=WaitingClient())
    @asynccontextmanager
    async def retry_client():
        yield FakeModelClient(workflow_data.responses)
    async def exercise():
        task = asyncio.create_task(setup.manager.start(workflow_data.request))
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        saved = setup.repository.list_runs()[0]
        assert saved['status'] == 'failed' and setup.manager.get(saved['run_id']).state.current_step == 'failed'
        setup.manager.client_factory = retry_client
        response = await setup.manager.retry(saved['run_id'])
        assert response.awaiting_approval and response.state.run_id == saved['run_id']
        assert setup.repository.run(saved['run_id'])['model_calls'] == 7
    asyncio.run(exercise())
