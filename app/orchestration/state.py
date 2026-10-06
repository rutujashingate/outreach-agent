"""Hold the goal, progress, and results for one outreach request in memory."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.schemas import (
    EmailDraft,
    GoalText,
    OutreachStrategy,
    Prospect,
    Qualification,
    ReviewResult,
)


class OutreachState(BaseModel):
    """One request's goal, progress, and future workflow results."""

    goal: GoalText
    # list[Prospect] describes a list of prospect records. Pydantic validates
    # nested input when the state is created. Each default_factory is called
    # separately, giving every request fresh lists and dictionaries.
    prospects: list[Prospect] = Field(default_factory=list)
    # Keep scores and reasons for evaluated prospects, including rejected ones.
    qualification_results: list[Qualification] = Field(default_factory=list)
    # This list will hold the prospects selected by a future qualifier.
    qualified_prospects: list[Prospect] = Field(default_factory=list)
    # These dictionaries use prospect IDs as keys, for example drafts["p1"].
    strategies: dict[str, OutreachStrategy] = Field(default_factory=dict)
    drafts: dict[str, EmailDraft] = Field(default_factory=dict)
    reviews: dict[str, ReviewResult] = Field(default_factory=dict)
    # Literal describes the two progress labels supported by this phase.
    current_step: Literal["initialized", "skeleton_ready"] = "initialized"
