"""Records for complete outreach runs, decisions, and relationship history.

The original schemas remain usable. These records add the information needed
to remember contacts and pause a complete run for a person's decision.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.domain.schemas import EmailDraft, GoalText, NonEmptyText, OutreachRequest, Prospect
from app.agent.state import OutreachState
from app.domain.browser import PageEvidence
from app.domain.documents import Attachment, DocumentEvidence, MAX_ATTACHMENTS

# Reject whitespace, multiple recipients, and email-header injection. This is
# syntax validation, not proof that an address exists or belongs to a person.
EmailText = Annotated[str, StringConstraints(
    strict=True, strip_whitespace=True, max_length=254,
    pattern=r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}$",
)]
URLText = Annotated[str, StringConstraints(strict=True, max_length=2048, pattern=r"^https?://[^\s]+$")]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Record(BaseModel):
    """Reject misspelled or unexpected fields in every new record."""

    model_config = ConfigDict(extra="forbid")


class OutreachGoal(Record):
    raw_goal: GoalText
    goal_type: NonEmptyText
    objective: NonEmptyText
    target_entity: NonEmptyText
    target_description: NonEmptyText
    desired_outcome: NonEmptyText
    constraints: list[NonEmptyText] = Field(default_factory=list)
    research_signals: list[NonEmptyText] = Field(default_factory=list)


class SearchResult(Record):
    title: NonEmptyText = Field(max_length=2000)
    url: URLText
    description: str = Field(strict=True, max_length=10000)


class Sender(Record):
    name: NonEmptyText = Field(default="User", pattern=r"^[^\r\n]+$")
    email: EmailText | None = None
    # User-supplied background is available to strategy and writing; the model
    # must not invent experience, products, achievements, or affiliations.
    context: str = Field(default="", strict=True, max_length=10000)


class Recipient(Record):
    email: EmailText
    source: NonEmptyText = "Explicitly supplied by the user"
    evidence_quote: str = Field(default="", max_length=2000)


class WorkflowRequest(OutreachRequest):
    attachments: list[Attachment] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)
    research_material: str = Field(default="", strict=True, max_length=100000)
    sender: Sender = Field(default_factory=Sender)
    recipients: dict[str, Recipient] = Field(default_factory=dict)
    use_search: bool = Field(default=False, strict=True)
    use_browser: bool = Field(default=False, strict=True)
    seed_urls: list[URLText] = Field(default_factory=list, max_length=5)
    discover_emails: bool = Field(default=False, strict=True)
    # Sending is a manual action in Gmail. Keep it out of new request schemas.
    gmail_action: Literal["none", "draft"] = "none"


class MemoryFact(Record):
    id: NonEmptyText
    contact_email: EmailText
    kind: Literal["fact", "preference", "objection", "timing", "referral", "opt_out", "relationship"]
    value: NonEmptyText
    source: NonEmptyText
    evidence_quote: NonEmptyText
    recorded_at: datetime = Field(default_factory=utc_now)
    # None means there is no known expiry. Expired facts are excluded from
    # ordinary retrieval, but an opt-out never expires implicitly.
    expires_at: datetime | None = None
    confidence: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)

    @field_validator("recorded_at", "expires_at")
    @classmethod
    def require_timezone(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Memory timestamps must include a timezone.")
        return value


class ExtractedFact(Record):
    kind: Literal["fact", "preference", "objection", "timing", "referral", "relationship"]
    value: NonEmptyText
    evidence_quote: NonEmptyText


class MemoryExtraction(Record):
    facts: list[ExtractedFact]


class ContactDecision(Record):
    allowed: bool = Field(strict=True)
    reasons: list[NonEmptyText]


class ApprovalDecision(Record):
    prospect_id: NonEmptyText
    version: int = Field(strict=True, ge=1)
    # The hash binds the decision to the actual recipient and message, not
    # merely a version number supplied by the caller.
    fingerprint: NonEmptyText
    action: Literal["approve", "reject", "edit"]
    edited_draft: EmailDraft | None = None

    @model_validator(mode="after")
    def edit_requires_matching_draft(self):
        if self.action == "edit":
            if self.edited_draft is None or self.edited_draft.prospect_id != self.prospect_id:
                raise ValueError("An edit needs a draft for the same prospect.")
            if "\r" in self.edited_draft.subject or "\n" in self.edited_draft.subject:
                raise ValueError("Edited email subjects must not contain line breaks.")
        elif self.edited_draft is not None:
            raise ValueError("Only an edit decision may include an edited draft.")
        return self


class ApprovalSubmission(Record):
    decisions: list[ApprovalDecision] = Field(min_length=1)


class ApprovalRequest(Record):
    prospect: Prospect
    recipient: Recipient
    version: int
    fingerprint: str
    research_summary: list[str]
    memories: list[MemoryFact]
    strategy: dict[str, object]
    draft: EmailDraft


class Outcome(Record):
    prospect_id: NonEmptyText
    status: Literal["approved", "drafted", "sent", "rejected", "manual_review", "blocked", "failed", "uncertain"]
    reason: str = ""
    source: NonEmptyText
    external_id: str | None = None
    thread_id: str | None = None
    # Identifies the exact account, recipient, content, and action saved to Gmail.
    message_fingerprint: str | None = None


class ReplyRequest(Record):
    contact_email: EmailText
    source: NonEmptyText
    body: NonEmptyText = Field(max_length=100000)


class ReplyClassification(Record):
    category: Literal["positive", "negative", "referral", "question", "later", "opt_out"]
    evidence_quote: NonEmptyText


class WorkflowState(OutreachState):
    """Extend the existing request state with durable execution information."""

    run_id: NonEmptyText
    attachments: list[Attachment] = Field(default_factory=list)
    documents: list[DocumentEvidence] = Field(default_factory=list)
    document_warnings: list[str] = Field(default_factory=list)
    structured_goal: OutreachGoal | None = None
    sender: Sender = Field(default_factory=Sender)
    research_material: str = ""
    use_search: bool = False
    gmail_action: Literal["none", "draft", "send"] = "none"
    use_browser: bool = False
    seed_urls: list[URLText] = Field(default_factory=list)
    discover_emails: bool = False
    gmail_account_id: str | None = None
    pages: list[PageEvidence] = Field(default_factory=list)
    recipient_candidates: dict[str, list[Recipient]] = Field(default_factory=dict)
    recipient_requests: list[str] = Field(default_factory=list)
    search_results: list[SearchResult] = Field(default_factory=list)
    recipients: dict[str, Recipient] = Field(default_factory=dict)
    memories: dict[str, list[MemoryFact]] = Field(default_factory=dict)
    contact_decisions: dict[str, ContactDecision] = Field(default_factory=dict)
    revision_counts: dict[str, int] = Field(default_factory=dict)
    draft_versions: dict[str, int] = Field(default_factory=dict)
    human_decisions: dict[str, ApprovalDecision] = Field(default_factory=dict)
    approval_requests: list[ApprovalRequest] = Field(default_factory=list)
    outcomes: dict[str, Outcome] = Field(default_factory=dict)
    failures: dict[str, str] = Field(default_factory=dict)
    current_step: Literal[
        "initialized", "skeleton_ready", "research_complete", "interpreted",
        "qualified", "no_matches", "contact_checked", "written", "reviewed",
        "awaiting_approval", "awaiting_recipients", "cancelled", "stopped", "completed", "failed",
    ] = "initialized"


class RunResponse(Record):
    state: WorkflowState
    awaiting_approval: bool
    error: str | None = None
    awaiting_recipients: bool = False


class ReplyState(Record):
    run_id: NonEmptyText
    reply: ReplyRequest
    classification: ReplyClassification | None = None
    facts: list[MemoryFact] = Field(default_factory=list)


class ContactUpdate(Record):
    source: NonEmptyText
    evidence_quote: NonEmptyText
    active_conversation: bool | None = Field(default=None, strict=True)
    reconnect_at: datetime | None = None

    @field_validator("reconnect_at")
    @classmethod
    def require_timezone(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Reconnect dates must include a timezone.")
        return value
