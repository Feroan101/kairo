from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
from openai import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)
from pydantic import AnyHttpUrl, Field, ValidationError

from kairo_harness.domain import (
    FinishReason,
    ModelCapabilities,
    ModelDescriptor,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelStreamChunk,
    ToolCallDelta,
    ToolCallRequest,
    Usage,
    usage_delta,
)
from kairo_harness.errors import ConfigError, ProviderError
from kairo_harness.providers.base import ModelProvider, ProviderAdapterConfig

OPENAI_OPTIONS = frozenset(
    {
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "seed",
        "user",
        "parallel_tool_calls",
    }
)
NUMERIC_OPENAI_OPTIONS = frozenset({"top_p", "frequency_penalty", "presence_penalty", "seed"})


class OpenAIConfig(ProviderAdapterConfig):
    api_key_env: str = Field(default="OPENAI_API_KEY", min_length=1, max_length=100)
    base_url: AnyHttpUrl | None = None
    organization: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)

    def api_key(self, environ: Mapping[str, str] | None = None) -> str:
        env = os.environ if environ is None else environ
        api_key = env.get(self.api_key_env)
        if not api_key:
            raise ConfigError(
                "OpenAI API key is not configured",
                code="provider.missing_credentials",
                details={"provider": "openai", "envVar": self.api_key_env},
            )
        return api_key

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> OpenAIConfig | None:
        env = os.environ if environ is None else environ
        api_key_env = env.get("KAIRO_OPENAI_API_KEY_ENV", "OPENAI_API_KEY")
        if not env.get(api_key_env):
            return None
        base_url = env.get("KAIRO_OPENAI_BASE_URL")
        organization = env.get("OPENAI_ORGANIZATION")
        return cls(
            api_key_env=api_key_env,
            base_url=base_url or None,
            organization=organization or None,
            timeout_seconds=float(env.get("KAIRO_OPENAI_TIMEOUT_SECONDS", "30")),
        )


class OpenAIProvider(ModelProvider):
    def __init__(self, config: OpenAIConfig, client: AsyncOpenAI | None = None) -> None:
        self.config = config
        self._owns_client = client is None
        if client is None:
            client = AsyncOpenAI(
                api_key=config.api_key(),
                base_url=str(config.base_url) if config.base_url else None,
                organization=config.organization,
                timeout=config.timeout_seconds,
                max_retries=config.max_retries,
            )
        self._client = client

    @property
    def name(self) -> str:
        return "openai"

    @property
    def capabilities(self) -> ModelCapabilities:
        return self.config.capabilities

    def capabilities_for(self, model: str) -> ModelCapabilities:
        return self.config.model_capabilities.get(model, self.config.capabilities)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.close()

    async def list_models(self) -> list[ModelDescriptor]:
        try:
            page = await self._client.models.list()
        except Exception as error:
            raise self._translate_error(error, "list_models") from error

        descriptors: list[ModelDescriptor] = []
        for model in getattr(page, "data", []) or []:
            model_id = getattr(model, "id", None)
            if not isinstance(model_id, str) or not model_id:
                raise ProviderError(
                    "OpenAI returned an invalid model entry",
                    code="provider.invalid_response",
                    retryable=False,
                    details={"operation": "list_models"},
                )
            descriptors.append(
                ModelDescriptor(
                    id=model_id,
                    name=model_id,
                    capabilities=self.capabilities_for(model_id),
                )
            )
        return descriptors

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.require_capabilities(request.model, tool_calls=bool(request.tools))
        payload = self._payload(request, stream=False)
        try:
            completion = await self._client.chat.completions.create(**payload)
        except Exception as error:
            raise self._translate_error(error, "complete") from error
        return self._response_from_completion(completion)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamChunk]:
        self.require_capabilities(
            request.model,
            streaming=True,
            tool_calls=bool(request.tools),
        )
        payload = self._payload(request, stream=True)
        try:
            stream = await self._client.chat.completions.create(**payload)
            previous_usage = Usage()
            async for chunk in stream:
                normalized, cumulative = self._chunk(chunk, previous_usage)
                previous_usage = cumulative
                yield normalized
        except ProviderError:
            raise
        except Exception as error:
            raise self._translate_error(error, "stream") from error

    def _payload(self, request: ModelRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [self._message(message) for message in request.messages],
            "stream": stream,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.input_schema,
                    },
                }
                for spec in request.tools
            ]
        payload.update(self._options(request.options))
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    @staticmethod
    def _message(message: ModelMessage) -> dict[str, Any]:
        if message.role == ModelRole.TOOL:
            if not message.tool_call_id:
                raise ConfigError(
                    "Tool messages require a tool call id",
                    code="provider.invalid_request",
                    details={"provider": "openai"},
                )
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": message.content,
            }

        tool_calls = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, sort_keys=True, separators=(",", ":")),
                },
            }
            for call in message.tool_calls
        ]
        content: str | None = message.content
        if tool_calls and not content:
            content = None
        payload: dict[str, Any] = {"role": str(message.role), "content": content}
        if tool_calls:
            payload["tool_calls"] = tool_calls
        return payload

    @staticmethod
    def _options(options: dict[str, Any]) -> dict[str, Any]:
        for key, value in options.items():
            if key not in OPENAI_OPTIONS:
                raise ConfigError(
                    "Unsupported OpenAI model option",
                    code="provider.invalid_option",
                    details={"provider": "openai", "option": key},
                )
            if key == "parallel_tool_calls" and not isinstance(value, bool):
                raise ConfigError(
                    "OpenAI option must be a boolean",
                    code="provider.invalid_option",
                    details={"provider": "openai", "option": key},
                )
            if key == "user" and not isinstance(value, str):
                raise ConfigError(
                    "OpenAI option must be a string",
                    code="provider.invalid_option",
                    details={"provider": "openai", "option": key},
                )
            if key in NUMERIC_OPENAI_OPTIONS and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise ConfigError(
                    "OpenAI option must be numeric",
                    code="provider.invalid_option",
                    details={"provider": "openai", "option": key},
                )
        return dict(options)

    def _response_from_completion(self, completion: Any) -> ModelResponse:
        choices = getattr(completion, "choices", None) or []
        if not choices:
            raise ProviderError(
                "OpenAI returned no completion choices",
                code="provider.invalid_response",
                retryable=False,
                details={"operation": "complete"},
            )
        choice = choices[0]
        message = getattr(choice, "message", None)
        if message is None:
            raise ProviderError(
                "OpenAI returned a completion without a message",
                code="provider.invalid_response",
                retryable=False,
                details={"operation": "complete"},
            )
        tool_calls = self._tool_calls(getattr(message, "tool_calls", None))
        return ModelResponse(
            content=getattr(message, "content", None) or "",
            tool_calls=tool_calls,
            usage=self._usage(getattr(completion, "usage", None)),
            finish_reason=self._finish_reason(
                getattr(choice, "finish_reason", None),
                operation="complete",
                has_tool_calls=bool(tool_calls),
            ),
        )

    def _chunk(self, chunk: Any, previous_usage: Usage) -> tuple[ModelStreamChunk, Usage]:
        content_delta = ""
        tool_deltas: list[ToolCallDelta] = []
        finish_reason: FinishReason | None = None
        for choice in getattr(chunk, "choices", None) or []:
            delta = getattr(choice, "delta", None)
            if delta is not None:
                content_delta += getattr(delta, "content", None) or ""
                for index, call in enumerate(getattr(delta, "tool_calls", None) or []):
                    function = getattr(call, "function", None)
                    tool_deltas.append(
                        ToolCallDelta(
                            index=getattr(call, "index", index),
                            id=getattr(call, "id", None),
                            name=getattr(function, "name", None),
                            arguments_delta=getattr(function, "arguments", None) or "",
                        )
                    )
            if finish_reason is None:
                raw_reason = getattr(choice, "finish_reason", None)
                if raw_reason is not None:
                    finish_reason = self._finish_reason(raw_reason, operation="stream")

        raw_usage = self._usage(getattr(chunk, "usage", None))
        usage = usage_delta(raw_usage, previous_usage)
        cumulative = previous_usage.model_copy(
            update={
                field: value for field, value in raw_usage.model_dump().items() if value is not None
            }
        )
        return (
            ModelStreamChunk(
                content_delta=content_delta,
                tool_calls=tool_deltas,
                usage=usage,
                done=finish_reason is not None,
                finish_reason=finish_reason,
            ),
            cumulative,
        )

    @staticmethod
    def _tool_calls(calls: Any) -> list[ToolCallRequest]:
        normalized: list[ToolCallRequest] = []
        for call in calls or []:
            function = getattr(call, "function", None)
            arguments = getattr(function, "arguments", None)
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError as error:
                    raise ProviderError(
                        "OpenAI returned malformed tool arguments",
                        code="provider.invalid_tool_arguments",
                        retryable=False,
                    ) from error
            if not isinstance(arguments, dict):
                raise ProviderError(
                    "OpenAI returned tool arguments that were not an object",
                    code="provider.invalid_tool_arguments",
                    retryable=False,
                )
            try:
                normalized.append(
                    ToolCallRequest(
                        id=getattr(call, "id", None),
                        name=getattr(function, "name", None),
                        arguments=arguments,
                    )
                )
            except ValidationError as error:
                raise ProviderError(
                    "OpenAI returned an invalid tool call",
                    code="provider.invalid_tool_call",
                    retryable=False,
                    details={"issueCount": len(error.errors())},
                ) from error
        return normalized

    @staticmethod
    def _usage(value: Any) -> Usage:
        if value is None:
            return Usage()
        return Usage(
            input_tokens=OpenAIProvider._counter(value, "prompt_tokens"),
            output_tokens=OpenAIProvider._counter(value, "completion_tokens"),
            total_tokens=OpenAIProvider._counter(value, "total_tokens"),
        )

    @staticmethod
    def _counter(value: Any, field: str) -> int | None:
        counter = getattr(value, field, None)
        if isinstance(counter, bool) or not isinstance(counter, int) or counter < 0:
            return None
        return counter

    @staticmethod
    def _finish_reason(
        value: Any,
        *,
        operation: str,
        has_tool_calls: bool = False,
    ) -> FinishReason:
        if value is None:
            return FinishReason.TOOL_CALL if has_tool_calls else FinishReason.STOP
        mapping = {
            "stop": FinishReason.STOP,
            "tool_calls": FinishReason.TOOL_CALL,
            "function_call": FinishReason.TOOL_CALL,
            "length": FinishReason.LENGTH,
            "content_filter": FinishReason.INCOMPLETE,
        }
        reason = mapping.get(str(value)) if isinstance(value, str) else None
        if reason is None:
            raise ProviderError(
                "OpenAI returned an unsupported finish reason",
                code="provider.invalid_finish_reason",
                retryable=False,
                details={"operation": operation},
            )
        return reason

    @staticmethod
    def _translate_error(error: Exception, operation: str) -> ProviderError:
        details: dict[str, str | int | float | bool] = {"operation": operation}
        if isinstance(error, AuthenticationError):
            return ProviderError(
                "OpenAI authentication failed",
                code="provider.auth",
                retryable=False,
                details=details,
            )
        if isinstance(error, RateLimitError):
            return ProviderError(
                "OpenAI rate limit reached",
                code="provider.rate_limited",
                retryable=True,
                details=details,
            )
        if isinstance(error, APITimeoutError):
            return ProviderError(
                "OpenAI request timed out",
                code="provider.timeout",
                retryable=True,
                details=details,
            )
        if isinstance(error, APIConnectionError):
            return ProviderError(
                "Could not connect to OpenAI",
                code="provider.connection",
                retryable=True,
                details=details,
            )
        if isinstance(error, APIResponseValidationError):
            return ProviderError(
                "OpenAI returned an invalid response",
                code="provider.invalid_response",
                retryable=False,
                details=details,
            )
        status = getattr(error, "status_code", None)
        if isinstance(status, int):
            details["statusCode"] = status
        if isinstance(error, APIError):
            return ProviderError(
                "OpenAI returned an API error",
                code=f"provider.http_{status}" if isinstance(status, int) else "provider.api_error",
                retryable=status == 429 or isinstance(status, int) and status >= 500,
                details=details,
            )
        if isinstance(error, httpx.TimeoutException):
            return ProviderError(
                "OpenAI request timed out",
                code="provider.timeout",
                retryable=True,
                details=details,
            )
        if isinstance(error, httpx.ConnectError):
            return ProviderError(
                "Could not connect to OpenAI",
                code="provider.connection",
                retryable=True,
                details=details,
            )
        if isinstance(error, httpx.HTTPError):
            return ProviderError(
                "OpenAI HTTP request failed",
                code="provider.http_error",
                retryable=False,
                details=details,
            )
        return ProviderError(
            "OpenAI provider raised an unexpected error",
            code="provider.unexpected",
            retryable=False,
            details={"operation": operation, "errorType": type(error).__name__},
        )
