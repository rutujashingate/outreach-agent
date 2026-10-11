"""Write or revise one email from context already supplied by the workflow."""

import json

from app.llm.client import ModelClient, ModelResponseError, generate_structured
from app.domain.schemas import EmailDraft, OutreachStrategy, Prospect
from app.domain.workflow import MemoryFact, Sender
from app.agent.prompts.writer import WRITER_INSTRUCTIONS


async def write_draft(prospect: Prospect, strategy: OutreachStrategy, memories: list[MemoryFact],
                      sender: Sender, client: ModelClient, *, previous: EmailDraft | None = None,
                      feedback: list[str] | None = None, brief: dict | None = None) -> EmailDraft:
    result = await generate_structured(instructions=WRITER_INSTRUCTIONS, input_text=json.dumps({
        "prospect": prospect.model_dump(), "strategy": strategy.model_dump(),
        "memories": [fact.model_dump(mode="json") for fact in memories], "sender": sender.model_dump(),
        "previous_draft": previous.model_dump() if previous else None, "feedback": feedback or [],
        "direct_email_brief": brief,
    }), response_model=EmailDraft, client=client)
    if result.prospect_id != prospect.id:
        raise ModelResponseError("Writer referred to the wrong prospect.")
    if "\n" in result.subject or "\r" in result.subject:
        raise ModelResponseError("Email subjects must not contain line breaks.")
    return result
