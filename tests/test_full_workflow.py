"""Exercise the real graph from goal to approval and simulated external actions."""

import asyncio
from copy import deepcopy

from langgraph.runtime import Runtime
import pytest

from app.llm.client import FakeModelClient
from app.domain.workflow import ApprovalSubmission
from app.agent.context import WorkflowContext
from app.agent.nodes.external import external_node
from app.services.runs import RunConflict
from app.services.limits import Limits
from app.settings import Settings
from app.connectors.gmail.client import FakeGmailClient
from app.connectors.search import ToolError


def decide(response, action="approve", **changes):
    request = response.state.approval_requests[0]
    return ApprovalSubmission(decisions=[{"prospect_id": request.prospect.id, "version": request.version,
        "fingerprint": request.fingerprint, "action": action, **changes}])


def test_complete_run_pauses_after_review_without_gmail(make_run_manager, workflow_data):
    setup = make_run_manager()
    result = asyncio.run(setup.manager.start(workflow_data.request))
    assert result.awaiting_approval
    assert result.state.current_step == "awaiting_approval"
    assert result.state.structured_goal.raw_goal == workflow_data.request.goal
    assert result.state.qualified_prospects[0].id == "p1"
    assert result.state.draft_versions == {"p1": 1}
    assert len(result.state.approval_requests) == 1
    assert [call.response_model.__name__ for call in setup.client.calls] == [
        "OutreachGoal", "ResearchResult", "Qualification", "OutreachStrategy", "EmailDraft", "ReviewResult",
    ]
    assert setup.gmail.calls == []
    events = setup.manager.execution_events(result.state.run_id)
    assert any(event["event"] == "interrupt" for event in events)
    assert any(event["event"] == "route" for event in events)


@pytest.mark.parametrize("no_research", [True, False])
def test_no_qualifying_prospects_end_before_writing(make_run_manager, workflow_data, no_research):
    responses = deepcopy(workflow_data.responses)
    if no_research:
        responses[1] = {"prospects": []}
    else:
        responses[2]["score"] = 69
    setup = make_run_manager(responses=responses)
    result = asyncio.run(setup.manager.start(workflow_data.request))
    assert not result.awaiting_approval
    assert result.state.current_step == "no_matches"
    assert result.state.drafts == {}
    assert len(setup.client.calls) == (2 if no_research else 3)


@pytest.mark.parametrize("score,selected", [(69, False), (70, True), (100, True)])
def test_threshold_owns_selection_even_if_model_boolean_disagrees(make_run_manager, workflow_data, score, selected):
    responses = deepcopy(workflow_data.responses)
    responses[2].update(score=score, qualified=not selected)
    setup = make_run_manager(responses=responses)
    result = asyncio.run(setup.manager.start(workflow_data.request))
    assert result.state.qualification_results[0].qualified is selected
    assert bool(result.state.qualified_prospects) is selected


@pytest.mark.parametrize("blocked", ["missing_address", "opt_out", "active_conversation"])
def test_blocked_contacts_never_reach_writer(make_run_manager, workflow_data, blocked):
    setup = make_run_manager()
    request = workflow_data.request.model_copy(deep=True)
    if blocked == "missing_address":
        request.recipients.clear()
    else:
        setup.repository.update_contact("contact@example.com", **{
            "opted_out" if blocked == "opt_out" else "active_conversation": True,
        })
    result = asyncio.run(setup.manager.start(request))
    assert result.state.outcomes["p1"].status == "blocked"
    assert result.state.drafts == {}
    assert len(setup.client.calls) == 3
    assert setup.gmail.calls == []


@pytest.mark.parametrize("action,outcome", [("approve", "approved"), ("reject", "rejected")])
def test_decision_resumes_same_run_without_repeating_models(make_run_manager, workflow_data, action, outcome):
    setup = make_run_manager()
    async def run():
        paused = await setup.manager.start(workflow_data.request)
        completed = await setup.manager.resume(paused.state.run_id, decide(paused, action))
        return paused, completed
    paused, completed = asyncio.run(run())
    assert completed.state.run_id == paused.state.run_id
    assert not completed.awaiting_approval
    assert completed.state.outcomes["p1"].status == outcome
    assert len(setup.client.calls) == 6
    assert setup.gmail.calls == []
    assert setup.repository.history("contact@example.com")[0]["kind"] == outcome


def test_requested_draft_is_saved_without_inventing_human_approval(make_run_manager, workflow_data):
    setup = make_run_manager()
    request = workflow_data.request.model_copy(update={"gmail_action": "draft"})
    async def run():
        return await setup.manager.start(request)
    completed = asyncio.run(run())
    assert completed.state.outcomes["p1"].status == "drafted"
    assert completed.state.outcomes["p1"].external_id
    assert not completed.awaiting_approval and completed.state.human_decisions == {}
    assert [action for action, _ in setup.gmail.calls] == ["draft"]


def test_old_sending_flag_cannot_enable_sending(monkeypatch):
    monkeypatch.setenv('OUTREACH_ENABLE_SENDING', 'true')
    assert Settings.from_env().sending_enabled is False
    with pytest.raises(ValueError):
        Settings(sending_enabled=True)


def test_saved_legacy_send_run_cannot_resume(make_run_manager, workflow_data):
    from app.domain.workflow import WorkflowState
    setup = make_run_manager()
    state = WorkflowState(run_id='legacy-send', **workflow_data.request.model_dump())
    state.gmail_action = 'send'
    setup.repository.save_run(state, 'failed')
    with pytest.raises(RunConflict, match='draft-only'):
        asyncio.run(setup.manager.retry(state.run_id))
    assert setup.client.calls == [] and setup.gmail.calls == []
    assert setup.repository.acquire_run(state.run_id, 60)
    setup.repository.release_run(state.run_id)


def test_human_edit_is_reviewed_and_needs_a_fresh_approval(make_run_manager, workflow_data):
    responses = workflow_data.responses + [deepcopy(workflow_data.responses[-1])]
    setup = make_run_manager(responses=responses)
    async def run():
        paused = await setup.manager.start(workflow_data.request)
        edited = paused.state.drafts["p1"].model_copy(update={"body": "Would you be open to a brief technical conversation?"})
        revised = await setup.manager.resume(paused.state.run_id, decide(paused, "edit", edited_draft=edited))
        assert revised.awaiting_approval
        assert revised.state.draft_versions["p1"] == 2
        assert revised.state.revision_counts["p1"] == 1
        assert revised.state.drafts["p1"] == edited
        assert revised.state.approval_requests[0].fingerprint != paused.state.approval_requests[0].fingerprint
        with pytest.raises(ValueError, match="current draft"):
            await setup.manager.resume(paused.state.run_id, decide(paused))
        return await setup.manager.resume(paused.state.run_id, decide(revised))
    completed = asyncio.run(run())
    assert completed.state.outcomes["p1"].status == "approved"
    assert len(setup.client.calls) == 7
    assert setup.gmail.calls == []


@pytest.mark.parametrize('destination', ['none', 'draft'])
def test_repeated_review_rejection_stops_at_one_revision(make_run_manager, workflow_data, destination):
    responses = deepcopy(workflow_data.responses)
    responses[-1].update(approved=False, issues=["Unsupported statement."])
    responses.extend([deepcopy(responses[-2]), deepcopy(responses[-1])])
    setup = make_run_manager(responses=responses)
    result = asyncio.run(setup.manager.start(workflow_data.request.model_copy(update={'gmail_action': destination})))
    assert not result.awaiting_approval
    assert result.state.outcomes["p1"].status == "manual_review"
    assert result.state.revision_counts == {"p1": 1}
    assert setup.gmail.calls == []
    assert sum(call.response_model.__name__ == "EmailDraft" for call in setup.client.calls) == 2


def test_rejection_can_be_revised_and_then_approved(make_run_manager, workflow_data):
    responses = deepcopy(workflow_data.responses)
    responses[-1].update(approved=False, issues=["Make the request clearer."])
    responses.extend([deepcopy(responses[-2]), {**responses[-1], "approved": True, "issues": []}])
    setup = make_run_manager(responses=responses)
    result = asyncio.run(setup.manager.start(workflow_data.request))
    assert result.awaiting_approval
    assert result.state.revision_counts == {"p1": 1}
    assert result.state.draft_versions == {"p1": 2}


def test_model_output_for_wrong_prospect_cannot_advance(make_run_manager, workflow_data):
    responses = deepcopy(workflow_data.responses)
    responses[2]["prospect_id"] = "someone_else"
    setup = make_run_manager(responses=responses)
    result = asyncio.run(setup.manager.start(workflow_data.request))
    assert result.state.qualified_prospects == []
    assert result.state.outcomes["p1"].status == "failed"
    assert result.state.drafts == {}


def test_send_is_disabled_before_any_model_or_tool_call(make_run_manager, workflow_data):
    setup = make_run_manager()
    with pytest.raises(RunConflict, match="only creates drafts"):
        asyncio.run(setup.manager.start(workflow_data.request.model_copy(update={"gmail_action": "send"})))
    assert setup.client.calls == setup.gmail.calls == []


def test_opt_out_before_gmail_write_prevents_draft(make_run_manager, workflow_data):
    setup = make_run_manager()
    async def run():
        paused = await setup.manager.start(workflow_data.request)
        setup.repository.update_contact("contact@example.com", opted_out=True)
        state = paused.state.model_copy(update={'gmail_action':'draft'})
        context = WorkflowContext(FakeModelClient([]), setup.repository, setup.manager.settings.limits, gmail=setup.gmail)
        return await external_node(state, Runtime(context=context))
    result = asyncio.run(run())
    assert result['outcomes']["p1"].status == "blocked"
    assert setup.gmail.calls == []


def test_replaying_draft_node_returns_recorded_result_without_another_write(make_run_manager, workflow_data):
    settings = Settings(checkpoint_backend="memory")
    setup = make_run_manager(settings=settings)
    async def run():
        completed = await setup.manager.start(workflow_data.request.model_copy(update={"gmail_action": "draft"}))
        replay = completed.state.model_copy(update={"outcomes": {}}, deep=True)
        context = WorkflowContext(FakeModelClient([]), setup.repository, settings.limits,
                                  gmail=setup.gmail)
        result = await external_node(replay, Runtime(context=context))
        assert result["outcomes"]["p1"] == completed.state.outcomes["p1"]
        return completed
    completed = asyncio.run(run())
    assert completed.state.outcomes["p1"].status == "drafted"
    assert [action for action, _ in setup.gmail.calls] == ["draft"]
    assert not setup.repository.contact("contact@example.com")["last_contact_at"]


def test_uncertain_draft_is_not_retried(make_run_manager, workflow_data):
    class UncertainGmail(FakeGmailClient):
        async def create_draft(self, *args):
            await super().create_draft(*args)
            raise ToolError("Response was lost after acceptance.")
    gmail = UncertainGmail()
    settings = Settings(checkpoint_backend="memory")
    setup = make_run_manager(settings=settings, gmail=gmail)
    async def run():
        completed = await setup.manager.start(workflow_data.request.model_copy(update={"gmail_action": "draft"}))
        assert completed.state.outcomes["p1"].status == "uncertain"
        replay = completed.state.model_copy(update={"outcomes": {}}, deep=True)
        context = WorkflowContext(FakeModelClient([]), setup.repository, settings.limits,
                                  gmail=gmail)
        result = await external_node(replay, Runtime(context=context))
        assert result["outcomes"]["p1"].status == "blocked"
    asyncio.run(run())
    assert [action for action, _ in gmail.calls] == ["draft"]
    assert setup.repository.has_pending_action("contact@example.com")


def test_run_lease_prevents_simultaneous_approval_processing(make_run_manager, workflow_data):
    setup = make_run_manager()
    async def run():
        paused = await setup.manager.start(workflow_data.request)
        assert setup.repository.acquire_run(paused.state.run_id)
        try:
            with pytest.raises(RunConflict, match="already being processed"):
                await setup.manager.resume(paused.state.run_id, decide(paused))
        finally:
            setup.repository.release_run(paused.state.run_id)
        return await setup.manager.resume(paused.state.run_id, decide(paused))
    result = asyncio.run(run())
    assert result.state.outcomes["p1"].status == "approved"


def test_duplicate_recipient_in_one_run_gets_only_one_draft(make_run_manager, workflow_data):
    responses = deepcopy(workflow_data.responses)
    first = responses[1]["prospects"][0]
    second = {**first, "id": "p2", "company_name": "Another AI"}
    responses[1]["prospects"].append(second)
    responses.insert(3, {**responses[2], "prospect_id": "p2", "score": 80})
    setup = make_run_manager(responses=responses)
    request = workflow_data.request.model_copy(update={"research_material": str([first, second]),
        "recipients": {"p1": workflow_data.request.recipients["p1"], "p2": workflow_data.request.recipients["p1"]}})
    result = asyncio.run(setup.manager.start(request))
    assert result.awaiting_approval
    assert result.state.outcomes["p2"].status == "blocked"
    assert set(result.state.drafts) == {"p1"}


def test_gmail_opt_out_is_loaded_before_writing(make_run_manager, workflow_data):
    import base64
    from app.domain.workflow import utc_now
    gmail = FakeGmailClient({"t1": {"messages": [{"id": "m1", "internalDate": str(int(utc_now().timestamp() * 1000)),
        "payload": {"mimeType": "text/plain", "headers": [{"name": "From", "value": "contact@example.com"},
        {"name": "To", "value": "user@example.com"}], "body": {"data": base64.urlsafe_b64encode(b"Please unsubscribe me.").decode()}}}]}})
    setup = make_run_manager(gmail=gmail, settings=Settings(checkpoint_backend="memory", read_gmail=True))
    result = asyncio.run(setup.manager.start(workflow_data.request))
    assert result.state.outcomes["p1"].status == "blocked"
    assert result.state.memories["p1"][0].kind == "opt_out"
    assert len(setup.client.calls) == 3
    assert [action for action, _ in gmail.calls] == ["search", "read"]


def test_person_only_prospect_does_not_require_an_invented_organization():
    from app.agent.components.researcher import Researcher
    person = {"id": "p1", "entity_type": "person", "company_name": "Ada Example", "sources": ["https://example.com/ada"]}
    client = FakeModelClient([{"prospects": [person]}])
    result = asyncio.run(Researcher(client=client).research(goal="Find open-source maintainers for networking",
        research_material="Ada Example maintains open-source tools. Source: https://example.com/ada"))
    assert result[0].entity_type == "person"
    assert result[0].company_name == "Ada Example"
