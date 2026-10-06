"""Adapt graph state to the researcher and return only research updates."""

from dataclasses import dataclass

from langgraph.runtime import Runtime

from app.agents.researcher import Researcher
from app.models.schemas import Prospect
from app.orchestration.state import OutreachState


@dataclass(frozen=True)
class ResearchContext:
    """Per-request inputs kept outside the graph's result record."""

    researcher: Researcher | None = None
    research_material: str = ""


async def research(state: OutreachState, runtime: Runtime[ResearchContext]) -> dict[str, object]:
    """Pass the goal and evidence to the component, then update the graph."""
    context = runtime.context or ResearchContext()
    researcher = context.researcher or Researcher()
    prospects: list[Prospect] = await researcher.research(
        goal=state.goal, research_material=context.research_material,
    )
    updates: dict[str, object] = {"current_step": "research_complete"}
    if context.research_material.strip() or getattr(researcher, "search_enabled", False):
        # Replace researched prospects when new evidence was supplied. Without
        # new evidence, preserve any results already held by the caller's state.
        updates["prospects"] = prospects
    return updates
