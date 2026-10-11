"""The small set of actions a conversational reply may request.

These are model suggestions. Python validates them and owns tool execution;
there is deliberately no approve, send-email, shell, or arbitrary API action.
"""
from typing import Literal

from pydantic import Field

from app.domain.workflow import Record, WorkflowRequest


class ConversationAction(Record):
    action: Literal['reply', 'search', 'search_saved', 'research', 'read_page', 'read_file', 'run_status', 'read_gmail_draft', 'edit_draft', 'outreach']
    text: str = Field(default='', max_length=6000)
    query: str = Field(default='', max_length=1000)
    url: str = Field(default='', max_length=2048)
    document_id: str = Field(default='', max_length=32)
    run_id: str = Field(default='', max_length=64)
    draft_id: str = Field(default='', max_length=200)
    sources: list[str] = Field(default_factory=list, max_length=20)
    request: WorkflowRequest | None = None
    # Clear owner instructions start work directly. Only an explicit request
    # to wait/show a plan first requires the optional start button.
    require_confirmation: bool = Field(default=False, strict=True)
    # Set by the provider adapter, then saved with the tool result for replay.
    call_id: str = Field(default='', max_length=200)


class ConversationInstruction(ConversationAction):
    """Initial instruction-following pass; suggestions do not execute tools."""
