from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError

from kairo_harness.domain import (
    FinishReason,
    ModelCapabilities,
    ModelDescriptor,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamChunk,
    OptionValue,
    ToolCallDelta,
    ToolCallRequest,
    Usage,
    usage_delta,
)
from kairo_harness.errors import ProviderError
from kairo_harness.providers.base import ModelProvider, ProviderAdapterConfig


class OllamaConfig(ProviderAdapterConfig):
    base_url: AnyHttpUrl
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    headers: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> OllamaConfig | None:
        env = os.environ if environ is None else environ
        base_url = env.get("KAIRO_OLLAMA_BASE_URL")
        if not base_url:
            return None
        timeout = env.get("KAIRO_OLLAMA_TIMEOUT_SECONDS")
        return cls(
            base_url=base_url,
            timeout_seconds=float(timeout) if timeout else 30.0,
        )


class OllamaFunctionCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    arguments: Any = None


class OllamaToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    function: OllamaFunctionCall


class OllamaMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str = "assistant"
    content: str = ""
    tool_calls: list[OllamaToolCall] = Field(default_factory=list)


class OllamaChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: OllamaMessage
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    done_reason: str | None = None


class OllamaModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str


class OllamaTagsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    models: list[OllamaModel] = Field(default_factory=list)


class OllamaProvider(ModelProvider):
    def __init__(self, config: OllamaConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._base_url = str(config.base_url).rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=config.timeout_seconds,
            headers=config.headers,
        )

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def capabilities(self) -> ModelCapabilities:
        return self.config.capabilities

    def capabilities_for(self, model: str) -> ModelCapabilities:
        return self.config.model_capabilities.get(model, self.config.capabilities)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def list_models(self) -> list[ModelDescriptor]:
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
        except Exception as error:
            raise self._translate_error(error, "list_models") from error

        payload = self._json_object(response, "list_models")
        try:
            parsed = OllamaTagsResponse.model_validate(payload)
        except ValidationError as error:
            raise ProviderError(
                "Ollama returned an invalid model list",
                code="provider.invalid_response",
                retryable=False,
                details={"operation": "list_models", "issueCount": len(error.errors())},
            ) from error

        return [
            ModelDescriptor(
                id=model.name,
                name=model.name,
                capabilities=self.capabilities_for(model.name),
            )
            for model in parsed.models
        ]

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.require_capabilities(request.model, tool_calls=bool(request.tools))
        payload = self._chat_payload(request, stream=False)
        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
        except Exception as error:
            raise self._translate_error(error, "complete") from error

        body = self._json_object(response, "complete")
        try:
            parsed = OllamaChatResponse.model_validate(body)
        except ValidationError as error:
            raise ProviderError(
                "Ollama returned an invalid chat response",
                code="provider.invalid_response",
                retryable=False,
                details={"operation": "complete", "issueCount": len(error.errors())},
            ) from error

        tool_calls = self._tool_calls(parsed.message.tool_calls)
        return ModelResponse(
            content=parsed.message.content,
            tool_calls=tool_calls,
            usage=self._usage(body),
            finish_reason=self._finish_reason(tool_calls, parsed.done_reason),
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamChunk]:
        self.require_capabilities(
            request.model,
            streaming=True,
            tool_calls=bool(request.tools),
        )
        payload = self._chat_payload(request, stream=True)
        previous_usage = Usage()
        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = self._stream_chunk(line)
                    usage = usage_delta(chunk.usage, previous_usage)
                    previous_usage = previous_usage.model_copy(
                        update={
                            field: value
                            for field, value in chunk.usage.model_dump().items()
                            if value is not None
                        }
                    )
                    yield chunk.model_copy(update={"usage": usage})
        except ProviderError:
            raise
        except Exception as error:
            raise self._translate_error(error, "stream") from error

    def _chat_payload(self, request: ModelRequest, *, stream: bool) -> dict[str, Any]:
        options: dict[str, OptionValue] = dict(request.options)
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [self._message(message) for message in request.messages],
            "stream": stream,
        }
        if options:
            payload["options"] = options
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
        return payload

    @staticmethod
    def _message(message: ModelMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": str(message.role), "content": message.content}
        if message.tool_name:
            payload["tool_name"] = message.tool_name
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, sort_keys=True),
                    },
                }
                for call in message.tool_calls
            ]
        return payload

    @staticmethod
    def _json_object(response: httpx.Response, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderError(
                "Ollama returned a non-JSON response",
                code="provider.invalid_json",
                retryable=False,
                details={"operation": operation},
            ) from error
        if not isinstance(payload, dict):
            raise ProviderError(
                "Ollama returned a JSON value that was not an object",
                code="provider.invalid_response",
                retryable=False,
                details={"operation": operation},
            )
        return payload

    @staticmethod
    def _tool_calls(calls: list[OllamaToolCall]) -> list[ToolCallRequest]:
        normalized: list[ToolCallRequest] = []
        for call in calls:
            arguments = call.function.arguments
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError as error:
                    raise ProviderError(
                        "Ollama returned malformed tool arguments",
                        code="provider.invalid_tool_arguments",
                        retryable=False,
                    ) from error
            if not isinstance(arguments, dict):
                raise ProviderError(
                    "Ollama returned tool arguments that were not an object",
                    code="provider.invalid_tool_arguments",
                    retryable=False,
                )
            try:
                normalized.append(
                    ToolCallRequest(
                        id=call.id or str(uuid.uuid4()),
                        name=call.function.name,
                        arguments=arguments,
                    )
                )
            except ValidationError as error:
                raise ProviderError(
                    "Ollama returned an invalid tool call",
                    code="provider.invalid_tool_call",
                    retryable=False,
                    details={"issueCount": len(error.errors())},
                ) from error
        return normalized

    @staticmethod
    def _tool_call_deltas(calls: list[OllamaToolCall]) -> list[ToolCallDelta]:
        deltas: list[ToolCallDelta] = []
        for index, call in enumerate(calls):
            arguments = call.function.arguments
            arguments_delta = ""
            if isinstance(arguments, str):
                arguments_delta = arguments
            elif arguments is not None:
                arguments_delta = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
            deltas.append(
                ToolCallDelta(
                    index=index,
                    id=call.id or None,
                    name=call.function.name,
                    arguments_delta=arguments_delta,
                )
            )
        return deltas

    @staticmethod
    def _usage(payload: dict[str, Any]) -> Usage:
        input_tokens = payload.get("prompt_eval_count")
        output_tokens = payload.get("eval_count")
        if not isinstance(input_tokens, int) or isinstance(input_tokens, bool):
            input_tokens = None
        if not isinstance(output_tokens, int) or isinstance(output_tokens, bool):
            output_tokens = None
        total = None
        if input_tokens is not None and output_tokens is not None:
            total = input_tokens + output_tokens
        return Usage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total)

    @staticmethod
    def _finish_reason(tool_calls: list[ToolCallRequest], done_reason: str | None) -> FinishReason:
        if tool_calls:
            return FinishReason.TOOL_CALL
        if done_reason == "length":
            return FinishReason.LENGTH
        return FinishReason.STOP

    @staticmethod
    def _stream_finish_reason(
        done: bool, done_reason: str | None, has_tool_calls: bool
    ) -> FinishReason | None:
        if done_reason == "length":
            return FinishReason.LENGTH
        if done and has_tool_calls:
            return FinishReason.TOOL_CALL
        if done:
            return FinishReason.STOP
        return None

    def _stream_chunk(self, line: str) -> ModelStreamChunk:
        try:
            payload = json.loads(line)
        except ValueError as error:
            raise ProviderError(
                "Ollama returned a malformed streaming chunk",
                code="provider.invalid_stream_chunk",
                retryable=False,
            ) from error
        if not isinstance(payload, dict):
            raise ProviderError(
                "Ollama streaming chunk was not an object",
                code="provider.invalid_stream_chunk",
                retryable=False,
            )

        raw_message = payload.get("message", {})
        if not isinstance(raw_message, dict):
            raw_message = {}
        try:
            message = OllamaMessage.model_validate(raw_message)
        except ValidationError as error:
            raise ProviderError(
                "Ollama returned an invalid streaming message",
                code="provider.invalid_stream_chunk",
                retryable=False,
                details={"issueCount": len(error.errors())},
            ) from error

        done = bool(payload.get("done", False))
        raw_done_reason = payload.get("done_reason")
        done_reason = raw_done_reason if isinstance(raw_done_reason, str) else None
        tool_calls = self._tool_call_deltas(message.tool_calls)
        return ModelStreamChunk(
            content_delta=message.content,
            tool_calls=tool_calls,
            usage=self._usage(payload),
            done=done,
            finish_reason=self._stream_finish_reason(done, done_reason, bool(tool_calls)),
        )

    @staticmethod
    def _translate_error(error: Exception, operation: str) -> ProviderError:
        details: dict[str, str | int | float | bool] = {"operation": operation}
        if isinstance(error, httpx.TimeoutException):
            return ProviderError(
                "Ollama request timed out",
                code="provider.timeout",
                retryable=True,
                details=details,
            )
        if isinstance(error, httpx.ConnectError):
            return ProviderError(
                "Could not connect to Ollama",
                code="provider.connection",
                retryable=True,
                details=details,
            )
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            details["statusCode"] = status
            return ProviderError(
                "Ollama returned an HTTP error",
                code=f"provider.http_{status}",
                retryable=status == 429 or status >= 500,
                details=details,
            )
        if isinstance(error, httpx.HTTPError):
            return ProviderError(
                "Ollama HTTP request failed",
                code="provider.http_error",
                retryable=False,
                details=details,
            )
        return ProviderError(
            "Ollama provider raised an unexpected error",
            code="provider.unexpected",
            retryable=False,
            details={"operation": operation, "errorType": type(error).__name__},
        )
