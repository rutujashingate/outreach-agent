"""Connect goal interpretation to graph state."""

from langgraph.runtime import Runtime

from app.agent.components.goal_interpreter import interpret_goal
from app.domain.workflow import WorkflowState
from app.agent.context import WorkflowContext


async def goal_node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    goal = await interpret_goal(state.goal, runtime.context.client)
    return {"structured_goal": goal, "current_step": "interpreted"}
