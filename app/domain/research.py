"""Analysis of evidence already collected by the application's read tools."""
from pydantic import Field

from app.domain.workflow import Record


class ResearchAnalysis(Record):
    summary: str = Field(min_length=1, max_length=30000)
    sources: list[str] = Field(default_factory=list, max_length=30)
