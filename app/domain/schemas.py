"""Define the expected format of requests and workflow results.

Pydantic validates data when these records are created. These classes hold
information; workflow components research, score, and write it.
Fields named prospect_id connect their records to a Prospect's id.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Annotated combines a Python type (str) with Pydantic validation rules.
# This reusable definition gives requests and state the same rules for a goal.
GoalText = Annotated[
    str,
    StringConstraints(
        strict=True,  # Accept actual text instead of converting another type.
        strip_whitespace=True,  # Remove spaces and newlines at the ends.
        min_length=1,
        max_length=2000,
    ),
]

# IDs, names, and other short text fields must contain something after trimming.
NonEmptyText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]

# Keep formatting and require a non-space character. xAI matches patterns
# against the entire string, so surrounding text must be allowed explicitly.
EmailBody = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, pattern=r"[\s\S]*\S[\s\S]*"),
]


class OutreachRequest(BaseModel):
    """A required goal and optional evidence for the phase-four researcher."""

    # Reject unknown fields, such as a misspelled goal or client-supplied state.
    model_config = ConfigDict(extra="forbid")

    goal: GoalText
    # Until search is added, callers can supply notes and source references.
    # Preserve their formatting. Omitted or blank material needs no model call.
    research_material: str = Field(
        default="", strict=True,
        description="Source-backed research notes. Omitted or blank material needs no model call.",
    )


class Prospect(BaseModel):
    """A researched organization or person with supporting source references."""

    model_config = ConfigDict(extra="forbid")

    # Other result records refer to this ID so they stay linked to the company.
    id: NonEmptyText
    company_name: NonEmptyText
    # Retain the original field name for existing callers. For person-only
    # outreach it holds the target's display name, with this explicit type.
    entity_type: Literal["organization", "person"] = "organization"
    # "| None = None" means this information may be unknown or omitted.
    website: NonEmptyText | None = None
    industry: NonEmptyText | None = None
    decision_maker_name: NonEmptyText | None = None
    decision_maker_role: NonEmptyText | None = None
    # A signal is a useful event, such as the company hiring platform engineers.
    # default_factory creates a fresh list for each prospect.
    signals: list[NonEmptyText] = Field(default_factory=list)
    # Store the references that future research uses to support its findings.
    sources: list[NonEmptyText] = Field(default_factory=list)


class ResearchResult(BaseModel):
    """Wrap a batch of existing Prospect records for structured model output."""

    model_config = ConfigDict(extra="forbid")

    # The model must explicitly return a list, including [] for no matches.
    prospects: list[Prospect]


class Qualification(BaseModel):
    """A prospect's score and an explicit qualification decision."""

    model_config = ConfigDict(extra="forbid")

    prospect_id: NonEmptyText
    # ge means "greater than or equal to"; le means "less than or equal to".
    # strict=True requires a whole-number score, including at both boundaries.
    score: int = Field(strict=True, ge=0, le=100)
    # Store an explicit True/False decision; this model does not calculate it.
    qualified: bool = Field(strict=True)
    # Explain the decision so someone can understand why a prospect was chosen.
    reasons: list[NonEmptyText] = Field(default_factory=list)


class OutreachStrategy(BaseModel):
    """The outreach approach prepared for one prospect."""

    model_config = ConfigDict(extra="forbid")

    prospect_id: NonEmptyText
    # The event or situation that makes outreach timely.
    trigger: NonEmptyText
    # A possible problem the company faces, kept separate from factual research.
    pain_hypothesis: NonEmptyText
    # How the offered product could help with that problem.
    value_proposition: NonEmptyText
    # A relevant company-specific detail to mention in the email.
    personalization_hook: NonEmptyText
    # The next action to ask for, such as a short technical conversation.
    call_to_action: NonEmptyText


class EmailDraft(BaseModel):
    """An email's content, preserving the body's original formatting."""

    model_config = ConfigDict(extra="forbid")

    prospect_id: NonEmptyText
    subject: NonEmptyText
    # This is the email text. Creating this record does not contact Gmail.
    body: EmailBody


class ReviewResult(BaseModel):
    """A draft quality review; approval here is the reviewer's decision."""

    model_config = ConfigDict(extra="forbid")

    prospect_id: NonEmptyText
    # The reviewer's quality decision. Human approval is a separate future step.
    approved: bool = Field(strict=True)
    # Reject NaN and infinity. The reviewer's score scale is still undecided.
    score: float = Field(strict=True, allow_inf_nan=False)
    # Feedback that a future writer can use to revise the draft.
    issues: list[NonEmptyText] = Field(default_factory=list)
