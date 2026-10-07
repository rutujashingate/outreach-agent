"""Interpret a goal once so the downstream components share its meaning."""

from app.llm.client import ModelClient, ModelResponseError, generate_structured
from app.domain.workflow import OutreachGoal
from app.agent.prompts.goal import GOAL_INSTRUCTIONS


async def interpret_goal(goal: str, client: ModelClient) -> OutreachGoal:
    result = await generate_structured(instructions=GOAL_INSTRUCTIONS, input_text=goal,
                                       response_model=OutreachGoal, client=client)
    if result.raw_goal != goal:
        raise ModelResponseError("Goal interpretation changed the original goal.")
    return result
