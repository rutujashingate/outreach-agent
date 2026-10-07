"""Score observable results against supplied references, without model guessing.

These checks measure structured interpretation, relevance against reference
targets, source retention, selected IDs, concise writing, and workflow rules.
Human assessment is still needed for subtle factual and tone judgments.
"""

from app.domain.workflow import WorkflowState
from app.agent.policy import message_fingerprint


def overlap(expected: set, actual: set) -> float:
    return len(expected & actual) / len(expected | actual) if expected | actual else 1.0


def score_run(state: WorkflowState, reference: dict, *, max_revisions: int = 1) -> dict[str, float]:
    target_names = set(reference["target_names"])
    actual_names = {prospect.company_name for prospect in state.prospects}
    sources = set(reference["sources"])
    source_checks = [bool(prospect.sources) and set(prospect.sources) <= sources for prospect in state.prospects]
    qualified_names = {prospect.company_name for prospect in state.qualified_prospects}
    draft_checks = [len(draft.body.split()) <= reference.get("max_words", 180)
                    and all(phrase.casefold() not in draft.body.casefold() for phrase in reference.get("forbidden_claims", []))
                    for draft in state.drafts.values()]
    strategy_checks = [reference.get("hook", "").casefold() in strategy.personalization_hook.casefold()
                       for strategy in state.strategies.values()]
    memory_checks = [fact.evidence_quote == fact.value for facts in state.memories.values() for fact in facts
                     if fact.kind != "opt_out"]
    safety = [all(count <= max_revisions for count in state.revision_counts.values())]
    for prospect_id, outcome in state.outcomes.items():
        if outcome.status in {"sent", "drafted"}:
            decision = state.human_decisions.get(prospect_id)
            safety.append(decision is not None and decision.action == "approve" and
                decision.fingerprint == message_fingerprint(state.sender, state.recipients[prospect_id], state.drafts[prospect_id],
                    action=state.gmail_action, account_id=state.gmail_account_id)
                and state.contact_decisions[prospect_id].allowed)
    ratio = lambda checks: sum(checks) / len(checks) if checks else 1.0
    expected_prepared = len(reference["qualified_names"])
    stage_score = lambda checks, count: ratio(checks) if count >= expected_prepared else 0.0
    return {
        "goal_interpretation": float(state.structured_goal is not None and
            state.structured_goal.goal_type == reference["goal_type"] and state.structured_goal.raw_goal == state.goal),
        "research_relevance": overlap(target_names, actual_names),
        "research_sources": ratio(source_checks),
        "qualification": overlap(set(reference["qualified_names"]), qualified_names),
        "memory_provenance": ratio(memory_checks),
        "memory_relevance": overlap(set(reference.get("expected_memory_ids", [])),
                                    {fact.id for facts in state.memories.values() for fact in facts}),
        "strategy_hook": stage_score(strategy_checks, len(state.strategies)),
        "writer_constraints": stage_score(draft_checks, len(state.drafts)),
        "reviewer_decisions": stage_score([review.approved == reference.get("review_approved", True)
                                            for review in state.reviews.values()], len(state.reviews)),
        "workflow_rules": ratio(safety),
    }
