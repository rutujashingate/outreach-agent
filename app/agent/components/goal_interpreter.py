"""Interpret a goal once so the downstream components share its meaning."""

import json

from app.llm.client import ModelClient, ModelResponseError, generate_structured
from app.domain.workflow import OutreachGoal
from app.agent.prompts.goal import GOAL_INSTRUCTIONS


async def interpret_goal(goal: str, client: ModelClient, document_context=None) -> OutreachGoal:
    input_text = json.dumps({'goal': goal, 'documents': document_context}, ensure_ascii=False) if document_context else goal
    result = await generate_structured(instructions=GOAL_INSTRUCTIONS, input_text=input_text,
                                       response_model=OutreachGoal, client=client)
    if result.raw_goal != goal:
        raise ModelResponseError("Goal interpretation changed the original goal.")
    return result
