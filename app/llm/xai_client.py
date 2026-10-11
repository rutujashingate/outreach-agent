"""Use Grok on xAI through the same structured interface as other providers.

Each call makes one request. The existing workflow wrapper owns retries and
budgets, so there are no extra requests hidden inside this adapter.
"""

import os
from typing import Self

import httpx
from pydantic import BaseModel, ValidationError

from app.llm.client import ModelProviderError, ModelRefusalError, ModelResponseError

DEFAULT_XAI_MODEL = "grok-4.3"
REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh"}


def _request_failure(response: httpx.Response) -> ModelProviderError:
    """Turn an HTTP failure into fixed text safe for saved logs and Telegram."""
    status = response.status_code
    reason = {
        400: "request_rejected", 401: "invalid_key", 402: "credits_required",
        403: "xai_access_denied", 404: "model_unavailable",
        413: "request_rejected", 422: "request_rejected", 429: "rate_limited",
    }.get(status, "service_unavailable" if 500 <= status <= 599 else "request_failed")
    # Provider error bodies can contain private input. Never copy them to logs.
    return ModelProviderError(provider="xAI", reason=reason, status_code=status)


class XAIModelClient:
    """Translate instructions, input text, and a record type into an xAI request."""

    def __init__(self, *, model: str, api_key: str | None = None,
                 reasoning_effort: str | None = "none", max_output_tokens: int = 4000,
                 http_client: httpx.AsyncClient | None = None, timeout: float = 60):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a nonblank xAI model name.")
        key = os.getenv("XAI_API_KEY", "") if api_key is None else api_key
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Set XAI_API_KEY before using XAIModelClient.")
        if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORTS:
            raise ValueError("XAI_REASONING_EFFORT must be none, low, medium, high, or xhigh.")
        if type(max_output_tokens) is not int or max_output_tokens < 1:
            raise ValueError("max_output_tokens must be a positive integer.")
        self.model_name = model.strip()
        self.last_usage: dict[str, int] = {}
        self._key = key.strip()
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)

    @classmethod
    def from_env(cls, **kwargs) -> Self:
        """Read only xAI settings; another provider's key is never a fallback."""
        return cls(model=os.getenv("XAI_MODEL") or DEFAULT_XAI_MODEL,
                   reasoning_effort=os.getenv("XAI_REASONING_EFFORT") or "none", **kwargs)

    async def generate_structured(self, *, instructions: str, input_text: str,
                                  response_model: type[BaseModel]) -> BaseModel:
        self.last_usage = {}
        body = {
            "model": self.model_name,
            "instructions": instructions,
            "input": input_text,
            "text": {"format": {
                "type": "json_schema", "name": response_model.__name__,
                "schema": response_model.model_json_schema(), "strict": True,
            }},
            "reasoning": {"effort": self._reasoning_effort},
            # xAI bounds visible output here, not reasoning tokens. Our default
            # effort is explicitly "none"; increasing it can add token costs.
            "max_output_tokens": self._max_output_tokens,
            "store": False,
            "stream": False,
        }
        if self._reasoning_effort is None:
            body.pop('reasoning')  # 4.20 reasoning uses the model's own setting.
        payload = await self.request(body)
        return self.parse_structured(payload, response_model)

    async def request(self, body):
        """Perform exactly one HTTP request and retain only safe usage fields."""
        self.last_usage = {}
        try:
            response = await self._http.post(
                "https://api.x.ai/v1/responses",
                headers={"Authorization": f"Bearer {self._key}"}, json=body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise _request_failure(error.response) from error
        except httpx.HTTPError as error:
            raise ModelProviderError(provider="xAI", reason="connection_failed") from error

        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError
            output = payload["output"]
            if not isinstance(output, list):
                raise TypeError
        except (ValueError, TypeError, KeyError) as error:
            raise ModelResponseError("xAI returned an invalid response structure.") from error

        usage = payload.get("usage")
        if isinstance(usage, dict):
            for name in ("input_tokens", "output_tokens", "total_tokens", "num_sources_used",
                         "num_server_side_tools_used", "cost_in_usd_ticks"):
                value = usage.get(name)
                if type(value) is int and value >= 0:
                    self.last_usage[name] = value
            for section, name in [('output_tokens_details', 'reasoning_tokens'),
                                  ('input_tokens_details', 'cached_tokens')]:
                details = usage.get(section)
                value = details.get(name) if isinstance(details, dict) else None
                if type(value) is int and value >= 0:
                    self.last_usage[name] = value
            # Tool names are an allowlist too; arbitrary provider strings must
            # not become log fields (they could contain private input).
            counts = usage.get('server_side_tool_usage', payload.get('server_side_tool_usage', {}))
            if isinstance(counts, dict):
                counts = {k: v for k, v in counts.items() if k in {
                    'SERVER_SIDE_TOOL_WEB_SEARCH', 'web_search', 'browse_page', 'open_page'
                } and type(v) is int and v >= 0}
                if counts:
                    self.last_usage['server_side_tool_usage'] = counts
        if payload.get("status") != "completed" or payload.get("error"):
            raise ModelResponseError("xAI model response did not complete.")
        return payload

    @staticmethod
    def parse_structured(payload, response_model):
        """Reject unexpected tool outputs when a structured record is expected."""
        texts = []
        for item in payload['output']:
            if not isinstance(item, dict):
                raise ModelResponseError("xAI returned an invalid output item.")
            if item.get("type") == "reasoning":
                continue  # Reasoning is not part of the requested record.
            if (item.get("type") != "message" or item.get("role") != "assistant"
                    or item.get("status") != "completed"
                    or not isinstance(item.get("content"), list)):
                raise ModelResponseError("xAI returned unexpected or incomplete output.")
            for part in item["content"]:
                if isinstance(part, dict) and part.get("type") == "refusal":
                    raise ModelRefusalError("xAI declined to produce structured output.")
                if (not isinstance(part, dict) or part.get("type") != "output_text"
                        or not isinstance(part.get("text"), str)):
                    raise ModelResponseError("xAI returned unexpected message content.")
                texts.append(part["text"])
        content = "".join(texts)
        if not content.strip():
            raise ModelResponseError("xAI response contained no structured output.")
        try:
            # Validate locally as well: provider guarantees do not replace our
            # field constraints or approval and contact-policy checks.
            return response_model.model_validate_json(content)
        except ValidationError as error:
            raise ModelResponseError(f"Model output did not match {response_model.__name__}.") from error

    async def aclose(self):
        """Close a connection created here, leaving injected connections alone."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exception_type, exception, traceback):
        await self.aclose()
