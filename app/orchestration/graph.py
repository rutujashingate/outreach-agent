"""Define the workflow's execution path using the existing OutreachState.

This compatibility path remains START -> research -> END. The checkpointed
complete workflow is defined in full_graph.py and reuses the same components.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.orchestration.nodes.research import ResearchContext, research
from app.orchestration.state import OutreachState


def build_graph() -> CompiledStateGraph[OutreachState, ResearchContext, OutreachState, OutreachState]:
    """Build and compile the research workflow without persistence."""
    # Use the same Pydantic model as the API; there is no second state format.
    builder = StateGraph(OutreachState, context_schema=ResearchContext)
    builder.add_node("research", research)
    # Edges describe which step runs next. END finishes this invocation.
    builder.add_edge(START, "research")
    builder.add_edge("research", END)
    return builder.compile()


# Prepare the execution path once. Each invocation has its own request state.
outreach_graph = build_graph()
