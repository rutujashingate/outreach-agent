"""The model may choose only these read tools; Python still validates access.

Each schema describes one function. It contains no credentials, executable
code, email-write operation, or ability to approve a pending request.
"""
import json

from pydantic import ValidationError

from app.domain.conversation import ConversationAction
from app.llm.client import ModelResponseError


TOOL_FIELDS = {
    'search': ('query', 1000, 'Find public websites using Brave search.'),
    'read_page': ('url', 2048, 'Read an allowed public URL from the user or search results.'),
    'read_file': ('document_id', 32, 'Read extracted text from an attached file.'),
    'run_status': ('run_id', 64, 'Read outreach progress. Use an empty ID for the latest run.'),
    'research': ('query', 1000, 'Ask the research model to compare or analyze evidence already collected. Read sources first. This does not search the internet.'),
}


def tool_definitions(inputs):
    """Advertise configured tools only, and none after the reading limit."""
    if not inputs.get('tools_allowed', False):
        return []
    capabilities = inputs.get('capabilities', {})
    enabled = {'run_status'}
    if capabilities.get('search'): enabled.add('search')
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
    entries = [{'role': 'user', 'content': json.dumps(inputs, ensure_ascii=False)}]
    for observation in inputs.get('observations', []):
        call = observation.get('function_call')
        if call:
            entries.append(call)
            entries.append({'type': 'function_call_output', 'call_id': call['call_id'],
                            'output': json.dumps({k: v for k, v in observation.items() if k != 'function_call'}, ensure_ascii=False)})
    return entries
