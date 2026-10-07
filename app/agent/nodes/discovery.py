"""Connect optional search and the existing researcher to the full graph."""

from langgraph.runtime import Runtime

from app.agent.components.researcher import Researcher
from app.domain.workflow import WorkflowState
from app.agent.context import WorkflowContext


async def discovery_node(state: WorkflowState, runtime: Runtime[WorkflowContext]) -> dict:
    context = runtime.context
    researcher = Researcher(client=context.client, search_tool=context.search if state.use_search else None)
    prospects = await researcher.research(goal=state.goal, research_material=state.research_material,
                                          structured_goal=state.structured_goal)
    recipients = dict(state.recipients)
    for prospect in prospects:
        # An exact organization-name mapping is an explicit user choice too.
        if prospect.id not in recipients and prospect.company_name in recipients:
            recipients[prospect.id] = recipients[prospect.company_name]
    return {"prospects": prospects[:context.limits.max_discovered], "recipients": recipients,
            "search_results": researcher.search_results, "research_material": researcher.evidence_material,
            "current_step": "research_complete"}
