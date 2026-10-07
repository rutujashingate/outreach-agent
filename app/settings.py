"""Read explicit configuration; local .env files are never loaded implicitly."""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.services.limits import Limits


class Settings(BaseModel):
    # Keep existing installations compatible; choose groq explicitly in .env.
    model_provider: Literal["openai", "groq"] = "openai"
    data_dir: Path = Path(".data")
    database_url: str | None = None
    checkpoint_backend: Literal["memory", "sqlite", "postgres"] = "sqlite"
    checkpoint_postgres_url: str | None = None
    api_key: str = ""
    sending_enabled: bool = False
    read_gmail: bool = False
    limits: Limits = Field(default_factory=Limits)

    @classmethod
    def from_env(cls):
        return cls(
            model_provider=os.getenv("OUTREACH_MODEL_PROVIDER", "openai"),
            data_dir=Path(os.getenv("OUTREACH_DATA_DIR", ".data")),
            database_url=os.getenv("OUTREACH_DATABASE_URL") or None,
            checkpoint_backend=os.getenv("OUTREACH_CHECKPOINT_BACKEND", "sqlite"),
            checkpoint_postgres_url=os.getenv("OUTREACH_CHECKPOINT_POSTGRES_URL") or None,
            api_key=os.getenv("OUTREACH_API_KEY", ""),
            sending_enabled=os.getenv("OUTREACH_ENABLE_SENDING", "false").casefold() == "true",
            read_gmail=os.getenv("OUTREACH_READ_GMAIL", "false").casefold() == "true",
            limits=Limits.model_validate(json.loads(os.getenv("OUTREACH_LIMITS_JSON", "{}"))),
        )
