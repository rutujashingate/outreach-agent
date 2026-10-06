"""Keep the application-facing workflow interface stable as the graph evolves.

The API calls run_workflow without needing to know about LangGraph. The graph
owns execution order and progress updates; this function returns OutreachState.
"""

from app.agents.researcher import Researcher
from app.orchestration.graph import outreach_graph
from app.orchestration.nodes.research import ResearchContext
from app.orchestration.state import OutreachState


async def run_workflow(
    state: OutreachState, *, researcher: Researcher | None = None, research_material: str = ""
) -> OutreachState:
    """Run the compiled graph and return its validated result in the same record."""
    # ainvoke waits for the graph to finish without blocking the async endpoint.
    # LangGraph returns a dictionary, so validate it using our existing model.
    if researcher is None and research_material == "":
        output = await outreach_graph.ainvoke(state)
    else:
        output = await outreach_graph.ainvoke(
            state, context=ResearchContext(researcher=researcher, research_material=research_material)
        )
    result = OutreachState.model_validate(output)
    # Preserve the original function's behavior: update and return the supplied
    # record. Every field comes from the graph's validated result.
    for field in OutreachState.model_fields:
        setattr(state, field, getattr(result, field))
    return state
