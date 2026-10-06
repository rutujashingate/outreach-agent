"""Review a draft against the evidence supplied to its writer."""

import json

from app.models.client import ModelClient, ModelResponseError, generate_structured
from app.models.schemas import EmailDraft, OutreachStrategy, Prospect, ReviewResult
from app.models.workflow import MemoryFact, Sender
from app.prompts.reviewer import REVIEW_INSTRUCTIONS


async def review_draft(prospect: Prospect, strategy: OutreachStrategy, memories: list[MemoryFact],
                       sender: Sender, draft: EmailDraft, client: ModelClient) -> ReviewResult:
    result = await generate_structured(instructions=REVIEW_INSTRUCTIONS, input_text=json.dumps({
        "research": prospect.model_dump(), "strategy": strategy.model_dump(),
        "memories": [fact.model_dump(mode="json") for fact in memories], "sender": sender.model_dump(),
        "draft": draft.model_dump(),
    }), response_model=ReviewResult, client=client)
    if result.prospect_id != prospect.id:
        raise ModelResponseError("Reviewer referred to the wrong prospect.")
    if not 0 <= result.score <= 1:
        raise ModelResponseError("This reviewer uses scores from 0 to 1.")
    return result
