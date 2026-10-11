"""Explicit owner-selected Grok roles, with no silent provider fallback.

Instruction following uses 4.3. Reasoning and native function selection use
4.20. Multi-agent research analyzes supplied evidence; it is never given
Gmail or local functions, and its built-in paid search tools are not enabled.
"""
import json
import os

from app.domain.conversation import ConversationAction
from app.llm.client import ModelResponseError
from app.llm.tools import checked_call, function_history, tool_definitions, research_request, edit_request
from app.llm.xai_client import XAIModelClient

DEFAULT_INSTRUCTION_MODEL = 'grok-4.3'
DEFAULT_REASONING_MODEL = 'grok-4.20-0309-reasoning'
DEFAULT_RESEARCH_MODEL = 'grok-4.20-multi-agent-0309'


def configured_models():
    return {
        'instruction': os.getenv('XAI_INSTRUCTION_MODEL') or os.getenv('XAI_MODEL') or DEFAULT_INSTRUCTION_MODEL,
        'reasoning': os.getenv('XAI_REASONING_MODEL') or DEFAULT_REASONING_MODEL,
        'research': os.getenv('XAI_RESEARCH_MODEL') or DEFAULT_RESEARCH_MODEL,
    }


def role_for(response_model):
    name = response_model.__name__
    if name in {'ConversationInstruction', 'OutreachGoal', 'EmailDraft'}:
        return 'instruction'
    if name in {'ResearchResult', 'ResearchAnalysis'}:
        return 'research'
    return 'reasoning'


class XAITaskRouter:
    supports_task_routing = True

    def __init__(self, *, clients=None, max_output_tokens=4000, timeout=60):
        self.clients = clients or {}
        self.models = configured_models()
        self.max_output_tokens, self.timeout = max_output_tokens, timeout
        self.last_usage, self.model_name, self.role = {}, None, None

    def route_info(self, response_model):
        role = role_for(response_model)
        return {'role': role, 'model': self.models[role]}

    def _client(self, role):
        if role not in self.clients:
            # Create only the selected role. A greeting opens no research client.
            effort = (os.getenv('XAI_REASONING_EFFORT') or 'none') if role == 'instruction' else ('low' if role == 'research' else None)
            self.clients[role] = XAIModelClient(model=self.models[role], reasoning_effort=effort,
                max_output_tokens=self.max_output_tokens, timeout=self.timeout)
        return self.clients[role]

    async def generate_structured(self, *, instructions, input_text, response_model):
        self.role = role_for(response_model)
        self.model_name, self.last_usage = self.models[self.role], {}
        client = self._client(self.role)
        try:
            if response_model is ConversationAction:
                return await self._select_tool(client, instructions, input_text)
            return await client.generate_structured(instructions=instructions, input_text=input_text,
                                                    response_model=response_model)
        finally:
            self.last_usage = client.last_usage

    async def _select_tool(self, client, instructions, input_text):
        inputs = json.loads(input_text)
        definitions = tool_definitions(inputs)
        # A clear fresh research command cannot be answered from old email
        # context. Its first native call must gather current evidence.
        editing = edit_request(inputs.get('message', ''))
        first_research = (research_request(inputs.get('message', '')) or editing) and not inputs.get('observations')
        required = 'read_gmail_draft' if editing else ('read_page' if 'http' in inputs.get('message', '') else 'search')
        if first_research and any(item['name'] == required for item in definitions):
            definitions = [item for item in definitions if item['name'] == required]
        else:
            first_research = False
        body = {
            'model': client.model_name, 'instructions': instructions +
                '\nUse a function call for reading or research. For a final reply, outreach proposal, or draft-edit proposal, return the requested JSON record. Never put a tool request in the final JSON.',
            'input': function_history(inputs),
            'text': {'format': {'type': 'json_schema', 'name': 'ConversationAction',
                               'schema': ConversationAction.model_json_schema(), 'strict': True}},
            'max_output_tokens': self.max_output_tokens, 'store': False, 'stream': False,
        }
        if definitions:
            body.update(tools=definitions, tool_choice='required' if first_research else 'auto', parallel_tool_calls=False)
        payload = await client.request(body)
        calls = [item for item in payload['output'] if isinstance(item, dict) and item.get('type') == 'function_call']
        if calls:
            if len(calls) != 1 or any(not isinstance(item, dict) or item.get('type') not in {'function_call', 'reasoning'} for item in payload['output']):
                raise ModelResponseError('Expected exactly one tool request, without a competing final answer.')
            action = checked_call(calls[0], {item['name'] for item in definitions})
            if any(item.get('function_call', {}).get('call_id') == action.call_id for item in inputs.get('observations', [])):
                raise ModelResponseError('The provider reused an earlier tool call identifier.')
            return action
        if first_research:
            raise ModelResponseError('The requested research or draft edit requires a reading tool first.')
        action = client.parse_structured(payload, ConversationAction)
        if action.action not in {'reply', 'outreach', 'edit_draft'} or action.call_id:
            raise ModelResponseError('Tool requests must use the function-calling interface.')
        return action

    async def aclose(self):
        for client in self.clients.values():
            await client.aclose()
