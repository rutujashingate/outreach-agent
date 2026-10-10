"""Keep operating limits in one place instead of hiding them in prompts."""

from pydantic import BaseModel, Field


class LimitExceeded(RuntimeError):
    """The run reached a configured operating limit."""


class Limits(BaseModel):
    max_discovered: int = Field(default=10, ge=1, le=100)
    max_qualified: int = Field(default=5, ge=1, le=100)
    max_search_calls: int = Field(default=2, ge=0, le=20)
    max_search_results: int = Field(default=10, ge=1, le=20)
    max_browser_pages: int = Field(default=5, ge=0, le=20)
    browser_timeout: float = Field(default=20, gt=0, le=60)
    max_page_chars: int = Field(default=15000, ge=1000, le=30000)
    max_revisions: int = Field(default=1, ge=0, le=5)
    max_graph_steps: int = Field(default=100, ge=10, le=1000)
    max_model_calls: int = Field(default=40, ge=1, le=1000)
    # Ordinary messages get a smaller budget than a complete outreach run.
    max_chat_model_calls: int = Field(default=6, ge=1, le=12)
    max_chat_tool_calls: int = Field(default=5, ge=0, le=10)
    max_output_tokens: int = Field(default=4000, ge=64, le=32000)
    model_timeout: float = Field(default=60, gt=0, le=600)
    search_timeout: float = Field(default=15, gt=0, le=120)
    tool_timeout: float = Field(default=20, gt=0, le=120)
    concurrency: int = Field(default=1, ge=1, le=10)
    recent_contact_days: int = Field(default=14, ge=0, le=365)
    memory_limit: int = Field(default=12, ge=1, le=100)
    memory_max_age_days: int = Field(default=365, ge=1)
    max_requests_per_minute: int = Field(default=30, ge=1)
    # Reserve this configured estimate before each call. Actual billing depends
    # on the chosen provider/model; this is an estimated budget, not a price quote.
    estimated_cost_per_call: float = Field(default=0.05, ge=0, allow_inf_nan=False)
    max_estimated_cost_per_run: float = Field(default=2, gt=0, allow_inf_nan=False)
