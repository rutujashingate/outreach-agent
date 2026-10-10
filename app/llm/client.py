"""One shared entry point for structured model calls.

Application components call generate_structured and receive a validated record.
They receive their client as an argument, so tests can substitute preset
responses. OpenAI-specific calls stay in OpenAIModelClient.
"""

from collections import deque
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import os
from typing import Protocol, Self, TypeVar

from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
ResponsePayload = BaseModel | Mapping[str, object] | str


class ModelClientError(RuntimeError):
    """A model request could not produce a usable result."""


class ModelProviderError(ModelClientError):
    """A provider failure described by our own text, never its raw response.

    Adapters select a known reason. These messages may be saved or shown to the
    owner because neither credentials nor provider-generated text are included.
    """

    _messages = {
        "invalid_key": "The API key was rejected. Check the provider key in .env and restart the application.",
        "organization_model_blocked": "The configured model is blocked by your organization. Allow it in Settings > Organization > Limits, save, then retry.",
        "project_model_blocked": "The configured model is blocked by your project. Allow it in Settings > Projects > Limits, save, then retry.",
        "permission_denied": "Access to the configured model was denied. Check organization and project model permissions.",
        "rate_limited": "The provider's request or token limit was reached. Wait for its limit to reset, then retry. This is separate from the app's reserved budget.",
        "request_rejected": "The provider rejected the request format or parameters. Check the configured model's structured-output support and the application's request.",
        "model_unavailable": "The configured model or endpoint is unavailable. Check the model setting and restart after correcting it.",
        "service_unavailable": "The model service is temporarily unavailable. Try again later.",
        "connection_failed": "The model service could not be reached. Check the connection and try again later.",
        "request_failed": "The model request failed. Inspect the saved HTTP status and provider configuration.",
    }

    def __init__(self, *, provider: str, reason: str, status_code: int | None = None):
        self.provider = provider if provider in {"Groq", "OpenAI"} else "Model provider"
        self.reason = reason if reason in self._messages else "request_failed"
        self.status_code = status_code if type(status_code) is int and 100 <= status_code <= 599 else None
        self.retryable = self.reason in {"service_unavailable", "connection_failed"}
        super().__init__(self.public_message)

    @property
    def public_message(self) -> str:
        return f"{self.provider}: {self._messages[self.reason]}"


class ModelResponseError(ModelClientError):
    """The output is missing, incomplete, or does not match the requested format."""


class ModelRefusalError(ModelResponseError):
    """The provider declined to produce the requested output."""


class ModelClient(Protocol):
    """The small interface implemented by both real and fake clients.

    Protocol describes the required method without requiring inheritance.
    The shared entry point below validates the returned payload.
    """

    async def generate_structured(
        self,
        *,
        instructions: str,
        input_text: str,
        response_model: type[BaseModel],
    ) -> ResponsePayload: ...


async def generate_structured(
    *,
    instructions: str,
    input_text: str,
    response_model: type[ResponseModel],
    client: ModelClient,
) -> ResponseModel:
    """Ask the supplied client for output and validate it against response_model."""
    # Check arguments before asking a provider to do any work. Preserve the
    # original prompt formatting after checking that the text is not blank.
    for name, value in (("instructions", instructions), ("input_text", input_text)):
        if not isinstance(value, str):
            raise TypeError(f"{name} must be text.")
        if not value.strip():
            raise ValueError(f"{name} must not be blank.")
    if (
        not isinstance(response_model, type)
        or not issubclass(response_model, BaseModel)
        or response_model is BaseModel
    ):
        raise TypeError("response_model must be a concrete Pydantic model class.")

    try:
        payload = await client.generate_structured(
            instructions=instructions,
            input_text=input_text,
            response_model=response_model,
        )
        # Revalidate existing model instances too: a caller may have changed
        # their fields after construction. Validation also creates a fresh record.
        if isinstance(payload, BaseModel):
            payload = payload.model_dump()
        if isinstance(payload, str):
            return response_model.model_validate_json(payload)
        return response_model.model_validate(payload)
    except ValidationError as error:
        raise ModelResponseError(
            f"Model output did not match {response_model.__name__}."
        ) from error


@dataclass(frozen=True)
class ModelCall:
    """A fake client's call record, used to inspect prompts in tests."""

    instructions: str
    input_text: str
    response_model: type[BaseModel]


class FakeModelClient:
    """Return queued example payloads in order, with no credentials or network.

    Queue the responses a test expects, then inspect calls to see which prompts
    were supplied. The shared generate_structured function validates each result.
    """

    def __init__(self, responses: Iterable[ResponsePayload]) -> None:
        # Snapshot the supplied examples so later changes cannot alter the script.
        self._responses = deque(deepcopy(list(responses)))
        self.calls: list[ModelCall] = []

    async def generate_structured(
        self,
        *,
        instructions: str,
        input_text: str,
        response_model: type[BaseModel],
    ) -> ResponsePayload:
        self.calls.append(ModelCall(instructions, input_text, response_model))
        if not self._responses:
            raise ModelClientError("FakeModelClient has no queued responses left.")
        return self._responses.popleft()


class OpenAIModelClient:
    """Use OpenAI's async Responses API to request structured output.

    A model name is supplied explicitly. An injected SDK client belongs to its
    caller; an SDK client created here is closed by this class's async context.
    """

    def __init__(
        self, *, model: str, sdk_client: AsyncOpenAI | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a nonblank OpenAI model name.")
        self._model = model.strip()
        self.model_name = self._model
        self._max_output_tokens = max_output_tokens
        self.last_usage: dict[str, int] = {}
        self._owns_sdk = sdk_client is None
        if sdk_client is None:
            api_key = os.getenv("OPENAI_API_KEY", "")
            if not api_key.strip():
                raise ValueError("Set OPENAI_API_KEY before using OpenAIModelClient.")
            sdk_client = AsyncOpenAI(api_key=api_key)
        self._sdk = sdk_client

    @classmethod
    def from_env(cls) -> Self:
        """Read explicitly exported OPENAI_MODEL and OPENAI_API_KEY settings."""
        model = os.getenv("OPENAI_MODEL", "")
        if not model.strip():
            raise ValueError("Set OPENAI_MODEL before using OpenAIModelClient.")
        return cls(model=model)

    async def generate_structured(
        self,
        *,
        instructions: str,
        input_text: str,
        response_model: type[BaseModel],
    ) -> ResponsePayload:
        try:
            # The SDK builds the JSON schema from the Pydantic model and parses
            # the reply. Provider-specific parameters are confined to this file.
            response = await self._sdk.responses.parse(
                model=self._model,
                instructions=instructions,
                input=input_text,
                text_format=response_model,
                store=False,
                **({"max_output_tokens": self._max_output_tokens} if self._max_output_tokens is not None else {}),
            )
        except APIError as error:
            raise ModelClientError("OpenAI model request failed.") from error

        self.last_usage = ({name: getattr(response.usage, name) for name in (
            "input_tokens", "output_tokens", "total_tokens",
        )} if response.usage is not None else {})
        for output in response.output:
            if output.type == "message":
                for content in output.content:
                    if content.type == "refusal":
                        raise ModelRefusalError(content.refusal)
        if response.status != "completed":
            raise ModelResponseError(
                f"Model response did not complete (status: {response.status})."
            )
        if response.output_parsed is None:
            raise ModelResponseError("Model response contained no structured output.")
        return response.output_parsed

    async def aclose(self) -> None:
        """Close only the SDK client owned by this adapter."""
        if self._owns_sdk:
            await self._sdk.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exception_type: object, exception: object, traceback: object
    ) -> None:
        await self.aclose()
