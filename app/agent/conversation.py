"""A LangGraph conversation loop: decide, read evidence, and answer.

Unlike the outreach graph, this graph can finish with an ordinary answer.
The service saves each turn and its history; a stopped turn needs explicit
retry. Model and tool budgets are stored separately and survive that retry.
"""
from dataclasses import dataclass
import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agent.prompts.conversation import CONVERSATION_INSTRUCTIONS
from app.domain.conversation import ConversationAction
from app.llm.client import generate_structured
from app.services.cancellation import check_cancelled


class ConversationState(TypedDict):
    observations: list[dict]
    steps: int
    action: dict
    result: dict


@dataclass
class ConversationContext:
    service: Any
    run_id: str
    client: Any
    search: Any
    browser: Any
    inputs: dict
    limits: Any


async def decide(state: ConversationState, runtime: Runtime[ConversationContext]):
    context = runtime.context
    check_cancelled(context.service.manager.repository, context.run_id)
    tools_allowed = (state['steps'] < context.limits.max_chat_model_calls - 1
                     and len(state['observations']) < context.limits.max_chat_tool_calls)
    action = await generate_structured(
        client=context.client, response_model=ConversationAction,
        instructions=CONVERSATION_INSTRUCTIONS,
        input_text=json.dumps({**context.inputs, 'observations': state['observations'],
                               'tools_allowed': tools_allowed}, ensure_ascii=False),
    )
    # A model instruction alone is not a limit. Stop tool requests in code too.
    if not tools_allowed and action.action not in {'reply', 'outreach'}:
        action = ConversationAction(action='reply', text=(
            'I reached the reading limit for this message. Please narrow the question '
            'or ask me to continue with a specific source.'))
    return {'action': action.model_dump(mode='json'), 'steps': state['steps'] + 1}


async def read_tool(state: ConversationState, runtime: Runtime[ConversationContext]):
    context = runtime.context
    check_cancelled(context.service.manager.repository, context.run_id)
    observation = await context.service.read_tool(ConversationAction.model_validate(state['action']), context, state['observations'])
    return {'observations': [*state['observations'], observation]}


async def answer(state: ConversationState, runtime: Runtime[ConversationContext]):
    context = runtime.context
    check_cancelled(context.service.manager.repository, context.run_id)
    result = context.service.response(ConversationAction.model_validate(state['action']), state['observations'], context)
    return {'result': result}


def build_conversation_graph():
    builder = StateGraph(ConversationState, context_schema=ConversationContext)
    builder.add_node('decide', decide)
    builder.add_node('read_tool', read_tool)
    builder.add_node('answer', answer)
    builder.add_edge(START, 'decide')
    builder.add_conditional_edges('decide', lambda state:
        'answer' if state['action']['action'] in {'reply', 'outreach'} else 'read_tool')
    builder.add_edge('read_tool', 'decide')
    builder.add_edge('answer', END)
    return builder.compile()
