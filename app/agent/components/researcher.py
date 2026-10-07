"""Turn supplied evidence into goal-relevant Prospect records."""

import json

from app.llm.client import ModelClient, ModelClientError, ModelResponseError, generate_structured
from app.domain.schemas import OutreachRequest, Prospect, ResearchResult
from app.agent.prompts.researcher import RESEARCH_INSTRUCTIONS
from app.domain.workflow import OutreachGoal, SearchResult
from app.connectors.search import SearchTool


class Researcher:
    """Use the existing model boundary; the caller owns the injected client."""

    def __init__(self, *, client: ModelClient | None = None, search_tool: SearchTool | None = None) -> None:
        self._client = client
        self._search_tool = search_tool
        self.search_enabled = search_tool is not None
        self.search_results: list[SearchResult] = []
        self.evidence_material = ""

    async def research(self, *, goal: str, research_material: str = "",
                       structured_goal: OutreachGoal | None = None) -> list[Prospect]:
        """Return validated prospects supported by the supplied research notes."""
        # Reuse the request rules for programmatic callers as well as HTTP users.
        request = OutreachRequest(goal=goal, research_material=research_material)
        self.search_results = []
        if self._search_tool is not None:
            query = request.goal if structured_goal is None else " ".join([
                structured_goal.target_description, *structured_goal.research_signals[:2],
            ])
            self.search_results = await self._search_tool.search(query)
            if self.search_results:
                # The URL and snippet stay together as supplied evidence.
                search_notes = json.dumps([item.model_dump() for item in self.search_results], ensure_ascii=False)
                request.research_material += "\n" + search_notes
        self.evidence_material = request.research_material
        if not request.research_material.strip():
            # No search is available yet. An empty evidence set yields no facts.
            return []
        if self._client is None:
            raise ModelClientError("Research with supplied material requires a model client.")

        result = await generate_structured(
            instructions=RESEARCH_INSTRUCTIONS,
            input_text=json.dumps({**request.model_dump(), **(
                {"structured_goal": structured_goal.model_dump()} if structured_goal else {}
            )}, ensure_ascii=False),
            response_model=ResearchResult,
            client=self._client,
        )
        # Format validation cannot prove facts. These checks reject missing or
        # invented references and names, and IDs that would confuse later joins.
        seen_ids: set[str] = set()
        material = request.research_material
        for prospect in result.prospects:
            if prospect.id in seen_ids:
                raise ModelResponseError("Research returned duplicate prospect IDs.")
            seen_ids.add(prospect.id)
            for name in (prospect.company_name, prospect.decision_maker_name):
                if name is not None and name.casefold() not in material.casefold():
                    raise ModelResponseError("Research returned a name absent from the supplied material.")
            if not prospect.sources or any(source not in material for source in prospect.sources):
                raise ModelResponseError("Research returned missing or unsupported source references.")
        return result.prospects
