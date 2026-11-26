from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
from anthropic import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APITimeoutError,
    AsyncAnthropic,
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

ANTHROPIC_OPTIONS = frozenset({"top_p", "top_k"})


class AnthropicConfig(ProviderAdapterConfig):
    api_key_env: str = Field(default="ANTHROPIC_API_KEY", min_length=1, max_length=100)
    base_url: AnyHttpUrl | None = None
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)
    default_max_tokens: int = Field(default=1024, gt=0, le=200_000)

    def api_key(self, environ: Mapping[str, str] | None = None) -> str:
        env = os.environ if environ is None else environ
        api_key = env.get(self.api_key_env)
        if not api_key:
            raise ConfigError(
                "Anthropic API key is not configured",
                code="provider.missing_credentials",
                details={"provider": "anthropic", "envVar": self.api_key_env},
            )
        return api_key

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AnthropicConfig | None:
        env = os.environ if environ is None else environ
        api_key_env = env.get("KAIRO_ANTHROPIC_API_KEY_ENV", "ANTHROPIC_API_KEY")
        if not env.get(api_key_env):
            return None
        base_url = env.get("KAIRO_ANTHROPIC_BASE_URL")
        return cls(
            api_key_env=api_key_env,
            base_url=base_url or None,
            timeout_seconds=float(env.get("KAIRO_ANTHROPIC_TIMEOUT_SECONDS", "30")),
            default_max_tokens=int(env.get("KAIRO_ANTHROPIC_MAX_TOKENS", "1024")),
        )


class AnthropicProvider(ModelProvider):
    def __init__(self, config: AnthropicConfig, client: AsyncAnthropic | None = None) -> None:
        self.config = config
        self._owns_client = client is None
        if client is None:
            client = AsyncAnthropic(
                api_key=config.api_key(),
                base_url=str(config.base_url) if config.base_url else None,
                timeout=config.timeout_seconds,
                max_retries=config.max_retries,
            )
        self._client = client

    @property
    def name(self) -> str:
        return "anthropic"

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
                    "Anthropic returned an invalid model entry",
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
            message = await self._client.messages.create(**payload)
        except Exception as error:
            raise self._translate_error(error, "complete") from error
        return self._response_from_message(message)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamChunk]:
        self.require_capabilities(
            request.model,
            streaming=True,
            tool_calls=bool(request.tools),
        )
        payload = self._payload(request, stream=True)
        try:
            events = await self._client.messages.create(**payload)
            tool_starts: dict[int, ToolCallDelta] = {}
            input_tokens = 0
            output_tokens = 0
            previous_usage = Usage()
            finish_reason: FinishReason | None = None
            async for event in events:
                event_type = getattr(event, "type", None)
                if event_type == "message_start":
                    usage = self._usage(getattr(getattr(event, "message", None), "usage", None))
                    input_tokens = usage.input_tokens or 0
                    output_tokens = usage.output_tokens or 0
                    raw_usage = self._cumulative_usage(input_tokens, output_tokens)
                    delta_usage = usage_delta(raw_usage, previous_usage)
                    previous_usage = raw_usage
                    yield ModelStreamChunk(usage=delta_usage)
                    continue
                if event_type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if getattr(block, "type", None) == "tool_use":
                        index = getattr(event, "index", 0)
                        arguments = getattr(block, "input", None)
                        tool_starts[index] = ToolCallDelta(
                            index=index,
                            id=getattr(block, "id", None),
                            name=getattr(block, "name", None),
                            arguments=arguments
                            if isinstance(arguments, dict) and arguments
                            else None,
                        )
                        yield ModelStreamChunk(tool_calls=[tool_starts[index]])
                    continue
                if event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        yield ModelStreamChunk(content_delta=getattr(delta, "text", "") or "")
                    elif delta_type == "input_json_delta":
                        index = getattr(event, "index", 0)
                        if index not in tool_starts:
                            raise ProviderError(
                                "Anthropic streamed tool arguments without a tool block",
                                code="provider.invalid_stream_chunk",
                                retryable=False,
                            )
                        yield ModelStreamChunk(
                            tool_calls=[
                                ToolCallDelta(
                                    index=index,
                                    arguments_delta=getattr(delta, "partial_json", "") or "",
                                )
                            ]
                        )
                    continue
                if event_type == "message_delta":
                    delta = getattr(event, "delta", None)
                    raw_reason = getattr(delta, "stop_reason", None)
                    if raw_reason is not None:
                        finish_reason = self._finish_reason(raw_reason, operation="stream")
                    usage = self._usage(getattr(event, "usage", None))
                    if usage.input_tokens is not None:
                        input_tokens = usage.input_tokens
                    if usage.output_tokens is not None:
                        output_tokens = usage.output_tokens
                    raw_usage = self._cumulative_usage(input_tokens, output_tokens)
                    delta_usage = usage_delta(raw_usage, previous_usage)
                    previous_usage = raw_usage
                    yield ModelStreamChunk(
                        usage=delta_usage,
                        done=True,
                        finish_reason=finish_reason or FinishReason.STOP,
                    )
                    continue
                if event_type == "message_stop":
                    yield ModelStreamChunk(
                        done=True,
                        finish_reason=finish_reason or FinishReason.STOP,
                    )
        except ProviderError:
            raise
        except Exception as error:
            raise self._translate_error(error, "stream") from error

    def _payload(self, request: ModelRequest, *, stream: bool) -> dict[str, Any]:
        system, messages = self._messages(request.messages)
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens or self.config.default_max_tokens,
            "messages": messages,
            "stream": stream,
        }
        if system:
            payload["system"] = system
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tools:
            payload["tools"] = [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                }
                for spec in request.tools
            ]
        payload.update(self._options(request.options))
        return payload

    @classmethod
    def _messages(cls, messages: list[ModelMessage]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        payload: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        for message in messages:
            if message.role == ModelRole.SYSTEM:
                system_parts.append(message.content)
                continue
            if message.role == ModelRole.TOOL:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id or "",
                        "content": message.content,
                    }
                )
                continue
            if tool_results:
                payload.append({"role": "user", "content": tool_results})
                tool_results = []
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            payload.append({"role": str(message.role), "content": blocks or message.content})
        if tool_results:
            payload.append({"role": "user", "content": tool_results})
        return "\n".join(system_parts), payload

    @staticmethod
    def _options(options: dict[str, Any]) -> dict[str, Any]:
        for key, value in options.items():
            if key not in ANTHROPIC_OPTIONS:
                raise ConfigError(
                    "Unsupported Anthropic model option",
                    code="provider.invalid_option",
                    details={"provider": "anthropic", "option": key},
                )
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConfigError(
                    "Anthropic option must be an integer",
                    code="provider.invalid_option",
                    details={"provider": "anthropic", "option": key},
                )
        return dict(options)

    def _response_from_message(self, message: Any) -> ModelResponse:
        content = ""
        tool_calls: list[ToolCallRequest] = []
        for block in getattr(message, "content", []) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                content += getattr(block, "text", "") or ""
            elif block_type == "tool_use":
                tool_calls.extend(self._tool_call(block))
        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            usage=self._usage(getattr(message, "usage", None)),
            finish_reason=self._finish_reason(
                getattr(message, "stop_reason", None),
                operation="complete",
                has_tool_calls=bool(tool_calls),
            ),
        )

    @staticmethod
    def _tool_call(block: Any) -> list[ToolCallRequest]:
        arguments = getattr(block, "input", None)
        if not isinstance(arguments, dict):
            raise ProviderError(
                "Anthropic returned tool input that was not an object",
                code="provider.invalid_tool_arguments",
                retryable=False,
            )
        try:
            return [
                ToolCallRequest(
                    id=getattr(block, "id", None),
                    name=getattr(block, "name", None),
                    arguments=arguments,
                )
            ]
        except ValidationError as error:
            raise ProviderError(
                "Anthropic returned an invalid tool call",
                code="provider.invalid_tool_call",
                retryable=False,
                details={"issueCount": len(error.errors())},
            ) from error

    @staticmethod
    def _usage(value: Any) -> Usage:
        if value is None:
            return Usage()
        input_tokens = AnthropicProvider._counter(value, "input_tokens")
        output_tokens = AnthropicProvider._counter(value, "output_tokens")
        total = None
        if input_tokens is not None and output_tokens is not None:
            total = input_tokens + output_tokens
        return Usage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total)

    @staticmethod
    def _cumulative_usage(input_tokens: int, output_tokens: int) -> Usage:
        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
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
            "end_turn": FinishReason.STOP,
            "stop_sequence": FinishReason.STOP,
            "tool_use": FinishReason.TOOL_CALL,
            "max_tokens": FinishReason.LENGTH,
            "pause_turn": FinishReason.INCOMPLETE,
        }
        reason = mapping.get(str(value)) if isinstance(value, str) else None
        if reason is None:
            raise ProviderError(
                "Anthropic returned an unsupported finish reason",
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
                "Anthropic authentication failed",
                code="provider.auth",
                retryable=False,
                details=details,
            )
        if isinstance(error, RateLimitError):
            return ProviderError(
                "Anthropic rate limit reached",
                code="provider.rate_limited",
                retryable=True,
                details=details,
            )
        if isinstance(error, APITimeoutError):
            return ProviderError(
                "Anthropic request timed out",
                code="provider.timeout",
                retryable=True,
                details=details,
            )
        if isinstance(error, APIConnectionError):
            return ProviderError(
                "Could not connect to Anthropic",
                code="provider.connection",
                retryable=True,
                details=details,
            )
        if isinstance(error, APIResponseValidationError):
            return ProviderError(
                "Anthropic returned an invalid response",
                code="provider.invalid_response",
                retryable=False,
                details=details,
            )
        status = getattr(error, "status_code", None)
        if isinstance(status, int):
            details["statusCode"] = status
        if isinstance(error, APIError):
            return ProviderError(
                "Anthropic returned an API error",
                code=f"provider.http_{status}" if isinstance(status, int) else "provider.api_error",
                retryable=status == 429 or isinstance(status, int) and status >= 500,
                details=details,
            )
        if isinstance(error, httpx.TimeoutException):
            return ProviderError(
                "Anthropic request timed out",
                code="provider.timeout",
                retryable=True,
                details=details,
            )
        if isinstance(error, httpx.ConnectError):
            return ProviderError(
                "Could not connect to Anthropic",
                code="provider.connection",
                retryable=True,
                details=details,
            )
        if isinstance(error, httpx.HTTPError):
            return ProviderError(
                "Anthropic HTTP request failed",
                code="provider.http_error",
                retryable=False,
                details=details,
            )
        return ProviderError(
            "Anthropic provider raised an unexpected error",
            code="provider.unexpected",
            retryable=False,
            details={"operation": operation, "errorType": type(error).__name__},
        )
