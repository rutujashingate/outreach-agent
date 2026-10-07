"""Source material read by the browser, kept separate from confirmed contacts."""
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field


class PageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    title: str = ""
    text: str = ""
    links: list[str] = Field(default_factory=list)
    emails: dict[str, str] = Field(default_factory=dict)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None
