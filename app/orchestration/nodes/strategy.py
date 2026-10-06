"""Build a message approach only for prospects allowed by contact rules."""

from langgraph.runtime import Runtime

from app.models.workflow import WorkflowState
from app.orchestration.context import WorkflowContext
from app.orchestration.nodes.common import allowed_prospects, failure, for_each
from app.strategy.builder import build_strategy


async def strategy_node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    context, strategies, outcomes = runtime.context, dict(state.strategies), dict(state.outcomes)
    failures = dict(state.failures)
    async def prepare(prospect):
        return await build_strategy(state.structured_goal, prospect, state.memories.get(prospect.id, []),
                                    state.sender, context.client)
    prospects = [prospect for prospect in allowed_prospects(state) if prospect.id not in strategies]
    for prospect, result in await for_each(prospects, prepare, context, run_id=state.run_id, stage="strategy"):
        if isinstance(result, Exception):
            outcomes[prospect.id] = failure(state, prospect.id, "strategy")
            failures[prospect.id] = "Strategy failed."
        else:
            strategies[prospect.id] = result
    return {"strategies": strategies, "outcomes": outcomes, "failures": failures}
