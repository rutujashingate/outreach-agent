"""Verify that evaluation reports expose missing results and deliberate regressions."""

import asyncio
import json
from pathlib import Path

from app.domain.workflow import WorkflowState
from evals.run import evaluate
from evals.scoring import score_run


def test_local_evaluation_covers_four_goal_types_without_external_services():
    report = asyncio.run(evaluate())
    assert report["mode"] == "simulation"
    assert {item["case"] for item in report["results"]} == {"jobs", "academic", "sales", "networking"}
    assert all(all(score == 1.0 for score in item["scores"].values()) for item in report["results"])
    assert all(item["model_calls"] == 6 for item in report["results"])


def test_missing_pipeline_results_are_not_scored_as_success():
    case = json.loads((Path(__file__).parents[1] / "evals/cases.json").read_text())[0]
    state = WorkflowState(run_id="test", goal=case["goal"])
    scores = score_run(state, case)
    assert scores["goal_interpretation"] == 0
    assert scores["research_relevance"] == 0
    assert scores["strategy_hook"] == 0
    assert scores["writer_constraints"] == 0
    assert scores["reviewer_decisions"] == 0


def test_evaluation_detects_unsupported_claim_and_wrong_sources(make_run_manager, workflow_data):
    setup = make_run_manager()
    result = asyncio.run(setup.manager.start(workflow_data.request))
    state = result.state.model_copy(deep=True)
    reference = {"goal_type": "sales", "target_names": ["Example AI"], "qualified_names": ["Example AI"],
                 "sources": ["https://example.com/careers"], "forbidden_claims": ["we met last week"]}
    state.prospects[0].sources = ["https://unsupported.example.com"]
    state.drafts["p1"].body = "We met last week."
    scores = score_run(state, reference)
    assert scores["research_sources"] == 0
    assert scores["writer_constraints"] == 0


def test_evaluation_detects_revision_limit_regression(make_run_manager, workflow_data):
    setup = make_run_manager()
    state = asyncio.run(setup.manager.start(workflow_data.request)).state
    state.revision_counts["p1"] = 2
    reference = {"goal_type": "sales", "target_names": ["Example AI"], "qualified_names": ["Example AI"], "sources": ["https://example.com/careers"]}
    assert score_run(state, reference, max_revisions=1)["workflow_rules"] == 0


def test_evaluation_checks_action_and_account_bound_approval(make_run_manager, workflow_data):
    from app.domain.workflow import ApprovalSubmission
    setup = make_run_manager()
    async def exercise():
        response = await setup.manager.start(workflow_data.request.model_copy(update={'gmail_action':'draft'}))
        item = response.state.approval_requests[0]
        return await setup.manager.resume(response.state.run_id, ApprovalSubmission(decisions=[{
            'prospect_id':'p1','version':item.version,'fingerprint':item.fingerprint,'action':'approve'}]))
    state = asyncio.run(exercise()).state
    reference = {'goal_type':'sales','target_names':['Example AI'],'qualified_names':['Example AI'],'sources':['https://example.com/careers']}
    assert state.outcomes['p1'].status == 'drafted'
    assert score_run(state, reference)['workflow_rules'] == 1
    state.gmail_action = 'send'
    assert score_run(state, reference)['workflow_rules'] < 1
    state.gmail_action, state.gmail_account_id = 'draft', 'another-account'
    assert score_run(state, reference)['workflow_rules'] < 1
