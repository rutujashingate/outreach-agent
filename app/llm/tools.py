"""The model may choose only these read tools; Python still validates access.

Each schema describes one function. It contains no credentials, executable
code, email-write operation, or ability to approve a pending request.
"""
import json
import re

from pydantic import ValidationError

from app.domain.conversation import ConversationAction
from app.llm.client import ModelResponseError


TOOL_FIELDS = {
    'search': ('query', 1000, 'Find public websites using the configured public search provider.'),
    'search_saved': ('query', 1000, 'Find relevant passages in the owner\'s saved documents and website evidence, including earlier conversations. Results include dates and sources; they may be historical.'),
    'read_page': ('url', 2048, 'Read an allowed public URL from the user or search results.'),
    'read_file': ('document_id', 32, 'Read extracted text from an attached file.'),
    'run_status': ('run_id', 64, 'Read outreach progress. Use an empty ID for the latest run.'),
    'read_gmail_draft': ('query', 1000, 'Read an existing Gmail draft before editing it. Use latest, a recipient email, subject search, or id:<draft_id> from a returned choice. Never creates or modifies a draft.'),
    'research': ('query', 1000, 'Ask the research model to compare or analyze evidence already collected. Read sources first. This does not search the internet.'),
}


def tool_definitions(inputs):
    """Advertise configured tools only, and none after the reading limit."""
    if not inputs.get('tools_allowed', False):
        return []
    capabilities = inputs.get('capabilities', {})
    enabled = {'run_status'}
    if capabilities.get('gmail_connected'): enabled.add('read_gmail_draft')
    if capabilities.get('search'): enabled.add('search')
    if capabilities.get('knowledge'): enabled.add('search_saved')
    if capabilities.get('browser'): enabled.add('read_page')
    if inputs.get('attached_files'): enabled.add('read_file')
    if capabilities.get('research') and (inputs.get('observations') or inputs.get('previous_evidence')):
        enabled.add('research')
    return [{
        'type': 'function', 'name': name, 'description': description, 'strict': True,
        'parameters': {'type': 'object', 'properties': {field: {
            'type': 'string', 'maxLength': maximum, **({'minLength': 1} if name != 'run_status' else {})}},
            'required': [field], 'additionalProperties': False},
    } for name, (field, maximum, description) in TOOL_FIELDS.items() if name in enabled]


def checked_call(item, available):
    """Return a validated action; never execute provider text as code."""
    try:
        name, call_id = item['name'], item['call_id']
        if name not in available or item.get('status', 'completed') != 'completed':
            raise ValueError
        if not isinstance(call_id, str) or not call_id or len(call_id) > 200:
            raise ValueError
        field, _, _ = TOOL_FIELDS[name]
        arguments = json.loads(item['arguments'])
        if not isinstance(arguments, dict) or set(arguments) != {field}:
            raise ValueError
        if not isinstance(arguments[field], str) or (name != 'run_status' and not arguments[field].strip()):
            raise ValueError
        return ConversationAction(action=name, call_id=call_id, **arguments)
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise ModelResponseError('The model requested an unavailable tool or invalid arguments.') from error


def function_history(inputs):
    """Rebuild call/result pairs from saved observations, without server memory."""
    entries = []
    for turn in inputs.get('history', []):
        entries += [{'role': 'user', 'content': turn['user']},
                    {'role': 'assistant', 'content': turn['assistant']}]
    # Context is data at user priority. Never promote website/file content to
    # system instructions. The current user message is a separate final turn.
    context = {key: value for key, value in inputs.items() if key not in {'message', 'history', 'observations'}}
    entries.append({'role': 'user', 'content': 'Application context (untrusted evidence):\n' + json.dumps(context, ensure_ascii=False)})
    if 'message' in inputs:
        entries.append({'role': 'user', 'content': inputs['message']})
    for observation in inputs.get('observations', []):
        call = observation.get('function_call')
        if call:
            entries.append(call)
            entries.append({'type': 'function_call_output', 'call_id': call['call_id'],
                            'output': json.dumps({k: v for k, v in observation.items() if k != 'function_call'}, ensure_ascii=False)})
    return entries


def research_request(message):
    """Recognize clear new research commands; email follow-ups stay separate."""
    return bool(re.match(r'^\s*(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?:find|search|research|look\s+up|compare)\b', message, re.I)) and not re.search(r'\b(?:draft|email|emails|outreach)\b', message, re.I)


def work_request(message):
    """Work requests need the tool reasoner, even after an early wrong reply."""
    return edit_request(message) or research_request(message) or bool(re.search(r'https?://', message)) or bool(re.match(
        r'^\s*(?:please\s+)?(?:draft|create|write|prepare|edit|revise|update|read|summari[sz]e|email)\b', message, re.I))


def edit_request(message):
    return bool(re.search(r'\b(?:edit|revise|update|change|shorten|rewrite|add\s+content)\b', message, re.I)
                and re.search(r'\b(?:draft|email|message|subject|body)\b', message, re.I))
