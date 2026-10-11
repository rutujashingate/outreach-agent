"""Read environment settings. The service entry point loads the local .env file."""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.limits import Limits


class Settings(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    # Existing installs keep the Groq fallback; .env.example explicitly selects xAI.
    model_provider: Literal["openai", "groq", "xai"] = "groq"
    xai_task_routing: bool = True
    data_dir: Path = Path(".data")
    supabase_database_url: str | None = Field(default=None, repr=False, exclude=True)
    database_url: str | None = Field(default=None, repr=False, exclude=True)
    checkpoint_backend: Literal["memory", "sqlite", "postgres"] = "sqlite"
    checkpoint_postgres_url: str | None = Field(default=None, repr=False, exclude=True)
    api_key: str = Field(default="", repr=False)
    # Retained for reading old configuration; execution never sends email.
    sending_enabled: Literal[False] = False
    read_gmail: bool = False
    telegram_token: str = Field(default="", repr=False)
    telegram_owner_id: int = 0
    owner_password: str = Field(default="", repr=False)
    secret_key: str = Field(default="", repr=False)
    google_client_id: str = ""
    google_client_secret: str = Field(default="", repr=False)
    app_url: str = "http://127.0.0.1:8000"
    browser_enabled: bool = True
    ocr_languages: str = Field(default='eng', pattern=r'^[A-Za-z_]+(?:\+[A-Za-z_]+)*$')
    demo: bool = False
    limits: Limits = Field(default_factory=Limits)

    @model_validator(mode='after')
    def use_one_supabase_database(self):
        if self.supabase_database_url:
            from app.storage.postgres import connection_urls
            database, checkpoint = connection_urls(self.supabase_database_url)
            if self.database_url not in {None, database} or self.checkpoint_postgres_url not in {None, checkpoint}:
                raise ValueError('With Supabase, leave OUTREACH_DATABASE_URL and OUTREACH_CHECKPOINT_POSTGRES_URL empty; one URL stores both kinds of state.')
            self.database_url, self.checkpoint_postgres_url = database, checkpoint
            self.checkpoint_backend = 'postgres'
        return self

    @classmethod
    def from_env(cls):
        return cls(
            model_provider=os.getenv("OUTREACH_MODEL_PROVIDER", "groq"),
            xai_task_routing=os.getenv('XAI_TASK_ROUTING', 'true').lower() == 'true',
            data_dir=Path(os.getenv("OUTREACH_DATA_DIR", ".data")),
            supabase_database_url=os.getenv("OUTREACH_SUPABASE_DATABASE_URL") or None,
            database_url=os.getenv("OUTREACH_DATABASE_URL") or None,
            checkpoint_backend=os.getenv("OUTREACH_CHECKPOINT_BACKEND", "sqlite"),
            checkpoint_postgres_url=os.getenv("OUTREACH_CHECKPOINT_POSTGRES_URL") or None,
            api_key=os.getenv("OUTREACH_API_KEY", ""),
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
            ocr_languages=os.getenv('OUTREACH_OCR_LANGUAGES', 'eng'),
            limits=Limits.model_validate(json.loads(os.getenv("OUTREACH_LIMITS_JSON", "{}"))),
        )
