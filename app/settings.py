"""Read environment settings. The service entry point loads the local .env file."""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.services.limits import Limits


class Settings(BaseModel):
    # Groq is the default; OpenAI remains an optional adapter.
    model_provider: Literal["openai", "groq"] = "groq"
    data_dir: Path = Path(".data")
    database_url: str | None = None
    checkpoint_backend: Literal["memory", "sqlite", "postgres"] = "sqlite"
    checkpoint_postgres_url: str | None = None
    api_key: str = Field(default="", repr=False)
    sending_enabled: bool = False
    read_gmail: bool = False
    telegram_token: str = Field(default="", repr=False)
    telegram_owner_id: int = 0
    owner_password: str = Field(default="", repr=False)
    secret_key: str = Field(default="", repr=False)
    google_client_id: str = ""
    google_client_secret: str = Field(default="", repr=False)
    app_url: str = "http://127.0.0.1:8000"
    browser_enabled: bool = True
    demo: bool = False
    limits: Limits = Field(default_factory=Limits)

    @classmethod
    def from_env(cls):
        return cls(
            model_provider=os.getenv("OUTREACH_MODEL_PROVIDER", "groq"),
            data_dir=Path(os.getenv("OUTREACH_DATA_DIR", ".data")),
            database_url=os.getenv("OUTREACH_DATABASE_URL") or None,
            checkpoint_backend=os.getenv("OUTREACH_CHECKPOINT_BACKEND", "sqlite"),
            checkpoint_postgres_url=os.getenv("OUTREACH_CHECKPOINT_POSTGRES_URL") or None,
            api_key=os.getenv("OUTREACH_API_KEY", ""),
            sending_enabled=os.getenv("OUTREACH_ENABLE_SENDING", "false").casefold() == "true",
            read_gmail=os.getenv("OUTREACH_READ_GMAIL", "false").casefold() == "true",
            telegram_token=os.getenv("OUTREACH_TELEGRAM_BOT_TOKEN", ""),
            telegram_owner_id=int(os.getenv("OUTREACH_TELEGRAM_OWNER_ID", "0")),
            owner_password=os.getenv("OUTREACH_OWNER_PASSWORD", ""),
            secret_key=os.getenv("OUTREACH_SECRET_KEY", ""),
            google_client_id=os.getenv("OUTREACH_GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.getenv("OUTREACH_GOOGLE_CLIENT_SECRET", ""),
            app_url=os.getenv("OUTREACH_APP_URL", "http://127.0.0.1:8000").rstrip("/"),
            browser_enabled=os.getenv("OUTREACH_BROWSER_ENABLED", "true").lower() == "true",
            demo=os.getenv("OUTREACH_DEMO", "false").lower() == "true",
            limits=Limits.model_validate(json.loads(os.getenv("OUTREACH_LIMITS_JSON", "{}"))),
        )
