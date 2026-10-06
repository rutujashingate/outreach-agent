"""Assess all discovered prospects and preserve their reasons."""

from langgraph.runtime import Runtime

from app.models.workflow import WorkflowState
from app.orchestration.context import WorkflowContext
from app.orchestration.nodes.common import failure, for_each
from app.qualification.qualifier import qualify


async def qualification_node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    context = runtime.context
    results, failures, outcomes = [], dict(state.failures), dict(state.outcomes)

    async def assess(prospect):
        return await qualify(state.structured_goal, prospect, context.client)

    for prospect, result in await for_each(state.prospects, assess, context, run_id=state.run_id, stage="qualification"):
        if isinstance(result, Exception):
            failures[prospect.id] = "Qualification failed."
            outcomes[prospect.id] = failure(state, prospect.id, "qualification")
        else:
            results.append(result)
    chosen_ids = [item.prospect_id for item in sorted(results, key=lambda item: (-item.score, item.prospect_id))
                  if item.qualified][:context.limits.max_qualified]
    by_id = {prospect.id: prospect for prospect in state.prospects}
    selected = [by_id[prospect_id] for prospect_id in chosen_ids]
    return {"qualification_results": results, "qualified_prospects": selected,
            "failures": failures, "outcomes": outcomes,
            "current_step": "qualified" if selected else "no_matches"}
