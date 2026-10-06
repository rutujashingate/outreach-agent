"""One shared entry point for structured model calls.

Future agents call generate_structured and receive a validated Pydantic record.
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
        self, *, model: str, sdk_client: AsyncOpenAI | None = None
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a nonblank OpenAI model name.")
        self._model = model.strip()
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
            )
        except APIError as error:
            raise ModelClientError("OpenAI model request failed.") from error

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
