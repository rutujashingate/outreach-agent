"""A LangGraph conversation loop: decide, read evidence, and answer.

Unlike the outreach graph, this graph can finish with an ordinary answer.
The service checkpoints every step. A stopped turn resumes with its original
inputs, observations, and tool call IDs. Budgets survive that continuation.
"""
from dataclasses import dataclass
import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agent.prompts.conversation import CONVERSATION_INSTRUCTIONS
from app.domain.conversation import ConversationAction, ConversationInstruction
from app.llm.client import generate_structured
from app.services.cancellation import check_cancelled
from app.agent.context import model_cache_scope


class ConversationState(TypedDict):
    observations: list[dict]
    steps: int
    action: dict
    result: dict
    instruction: dict
    inputs: dict


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
    used = context.service.manager.repository.run(context.run_id)['model_calls']
    tools_allowed = (used < context.limits.max_chat_model_calls - 1
                     and len(state['observations']) < context.limits.max_chat_tool_calls)
    inputs = {**context.inputs, 'capabilities': {**context.inputs['capabilities']}}
    # Research itself needs a model call, followed by a final answer. Reserve
    # room for those as well as the tool-selection call about to happen.
    if used > context.limits.max_chat_model_calls - 3:
        inputs['capabilities']['research'] = False
    action = await generate_structured(
        client=context.client, response_model=ConversationAction,
        instructions=CONVERSATION_INSTRUCTIONS,
        input_text=json.dumps({**inputs, 'observations': state['observations'],
                               'instruction': state.get('instruction', {}),
                               'tools_allowed': tools_allowed}, ensure_ascii=False),
    )
    # A model instruction alone is not a limit. Stop tool requests in code too.
    if not tools_allowed and action.action not in {'reply', 'outreach'}:
        action = ConversationAction(action='reply', text=(
            'I reached the reading limit for this message. Please narrow the question '
            'or ask me to continue with a specific source.'))
    return {'action': action.model_dump(mode='json'), 'steps': state['steps'] + 1}


async def understand(state: ConversationState, runtime: Runtime[ConversationContext]):
    """4.3 handles instructions first; only the reasoner can dispatch a tool."""
    context = runtime.context
    if not context.client.supports_task_routing:
        return {}  # Other providers retain the tested single-model loop.
    check_cancelled(context.service.manager.repository, context.run_id)
    action = await generate_structured(client=context.client, response_model=ConversationInstruction,
        instructions=CONVERSATION_INSTRUCTIONS + '\nThis is the instruction-following pass. Answer simple requests directly. For tasks requiring evidence, suggest the first reading step; a reasoner will select and execute the tools.',
        input_text=json.dumps({**context.inputs, 'observations': [], 'tools_allowed': True}, ensure_ascii=False))
    record = action.model_dump(mode='json')
    return {'instruction': record, 'action': record, 'steps': state['steps'] + 1}


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


def build_conversation_graph(checkpointer):
    from app.storage.events import trace

    def observed(name, function):
        async def node(state, runtime):
            context = runtime.context
            check_cancelled(context.service.manager.repository, context.run_id)
            trace(context.service.manager.repository, context.run_id, 'node_start', node='chat_' + name)
            scope = model_cache_scope.set(f"chat:{name}:{state.get('steps', 0)}")
            try:
                result = await function(state, runtime)
            finally:
                model_cache_scope.reset(scope)
            trace(context.service.manager.repository, context.run_id, 'node_end', node='chat_' + name)
            return result
        return node

    builder = StateGraph(ConversationState, context_schema=ConversationContext)
    builder.add_node('understand', observed('understand', understand))
    builder.add_node('decide', observed('decide', decide))
    builder.add_node('read_tool', observed('read_tool', read_tool))
    builder.add_node('answer', observed('answer', answer))
    builder.add_edge(START, 'understand')
    builder.add_conditional_edges('understand', lambda state:
        'answer' if state.get('instruction', {}).get('action') in {'reply', 'outreach'} else 'decide')
    builder.add_conditional_edges('decide', lambda state:
        'answer' if state['action']['action'] in {'reply', 'outreach'} else 'read_tool')
    builder.add_edge('read_tool', 'decide')
    builder.add_edge('answer', END)
    return builder.compile(checkpointer=checkpointer)
