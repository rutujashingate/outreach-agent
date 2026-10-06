"""Build a grounded approach for job, academic, sales, or other outreach."""

import json

from app.models.client import ModelClient, ModelResponseError, generate_structured
from app.models.schemas import OutreachStrategy, Prospect
from app.models.workflow import MemoryFact, OutreachGoal, Sender
from app.prompts.strategy import STRATEGY_INSTRUCTIONS


async def build_strategy(goal: OutreachGoal, prospect: Prospect, memories: list[MemoryFact],
                         sender: Sender, client: ModelClient) -> OutreachStrategy:
    result = await generate_structured(instructions=STRATEGY_INSTRUCTIONS, input_text=json.dumps({
        "goal": goal.model_dump(), "prospect": prospect.model_dump(),
        "memories": [fact.model_dump(mode="json") for fact in memories], "sender": sender.model_dump(),
    }), response_model=OutreachStrategy, client=client)
    if result.prospect_id != prospect.id:
        raise ModelResponseError("Strategy referred to the wrong prospect.")
    return result
