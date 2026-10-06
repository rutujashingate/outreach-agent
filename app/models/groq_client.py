"""Ask Groq for the same validated records used by the existing workflow.

This adapter uses HTTPX, which is already installed. It makes one HTTP request
per call; the workflow's existing wrapper owns attempt limits and retries.
"""

import os
from typing import Self

import httpx
from pydantic import BaseModel, ValidationError

from app.models.client import ModelClientError, ModelRefusalError, ModelResponseError

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


class GroqModelClient:
    """Translate our shared model interface into Groq Chat Completions."""

    def __init__(self, *, model: str, api_key: str | None = None,
                 http_client: httpx.AsyncClient | None = None,
                 max_output_tokens: int | None = None, timeout: float = 60):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a nonblank Groq model name.")
        key = os.getenv("GROQ_API_KEY", "") if api_key is None else api_key
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Set GROQ_API_KEY before using GroqModelClient.")
        if max_output_tokens is not None and (type(max_output_tokens) is not int or max_output_tokens < 1):
            raise ValueError("max_output_tokens must be a positive integer.")
        self.model_name = model.strip()
        self.last_usage: dict[str, int] = {}
        self._key = key.strip()
        self._max_output_tokens = max_output_tokens
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)

    @classmethod
    def from_env(cls, **kwargs) -> Self:
        """Read the locally exported key and optional model selection."""
        return cls(model=os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL, **kwargs)

    async def generate_structured(self, *, instructions: str, input_text: str,
                                  response_model: type[BaseModel]) -> BaseModel:
        self.last_usage = {}
        body = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    # Existing records have optional fields. Best-effort mode
                    # preserves their schemas; local validation is mandatory.
                    "strict": False,
                    "schema": response_model.model_json_schema(),
                },
            },
        }
        if self._max_output_tokens is not None:
            body["max_completion_tokens"] = self._max_output_tokens
        try:
            response = await self._http.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"}, json=body,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            # Credentials and provider response bodies stay out of user errors.
            raise ModelClientError("Groq model request failed.") from error
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError
            choice = payload["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict):
                raise TypeError
        except (ValueError, TypeError, KeyError, IndexError) as error:
            raise ModelResponseError("Groq returned an invalid response structure.") from error

        usage = payload.get("usage")
        if isinstance(usage, dict):
            for provider_name, local_name in (
                ("prompt_tokens", "input_tokens"),
                ("completion_tokens", "output_tokens"),
                ("total_tokens", "total_tokens"),
            ):
                value = usage.get(provider_name)
                if type(value) is int and value >= 0:
                    self.last_usage[local_name] = value
        if message.get("refusal") or choice.get("finish_reason") == "content_filter":
            raise ModelRefusalError("Groq declined to produce structured output.")
        if choice.get("finish_reason") != "stop":
            raise ModelResponseError("Groq model response did not complete.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelResponseError("Groq response contained no structured output.")
        try:
            return response_model.model_validate_json(content)
        except ValidationError as error:
            raise ModelResponseError(f"Model output did not match {response_model.__name__}.") from error

    async def aclose(self):
        """Close a connection created here; injected connections remain owned by their caller."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exception_type, exception, traceback):
        await self.aclose()
