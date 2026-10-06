"""One structured relevance assessment, followed by a selection rule in code."""

import json

from app.models.client import ModelClient, ModelResponseError, generate_structured
from app.models.schemas import Prospect, Qualification
from app.models.workflow import OutreachGoal
from app.prompts.qualification import QUALIFICATION_INSTRUCTIONS

QUALIFICATION_THRESHOLD = 70


async def qualify(goal: OutreachGoal, prospect: Prospect, client: ModelClient) -> Qualification:
    if not prospect.sources:
        return Qualification(prospect_id=prospect.id, score=0, qualified=False,
                             reasons=["No source-backed evidence is available."])
    result = await generate_structured(
        instructions=QUALIFICATION_INSTRUCTIONS,
        input_text=json.dumps({"goal": goal.model_dump(), "prospect": prospect.model_dump()}),
        response_model=Qualification, client=client,
    )
    if result.prospect_id != prospect.id:
        raise ModelResponseError("Qualification referred to the wrong prospect.")
    # The model supplies a score; this explicit threshold owns final selection.
    return result.model_copy(update={"qualified": result.score >= QUALIFICATION_THRESHOLD})
