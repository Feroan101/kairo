from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import AnyHttpUrl, Field

from kairo_harness.domain import (
    FinishReason,
    ModelCapabilities,
    ModelDescriptor,
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
from kairo_harness.providers.base import (
    ModelProvider,
    ProviderAdapterConfig,
    build_tool_call,
    nonnegative_counter,
    require_api_key,
    require_tool_arguments,
)

GEMINI_OPTIONS = frozenset({"top_p", "top_k", "presence_penalty", "frequency_penalty", "seed"})
GEMINI_INCOMPLETE_REASONS = frozenset(
    {
        "SAFETY",
        "RECITATION",
        "LANGUAGE",
        "OTHER",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "MALFORMED_FUNCTION_CALL",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_OTHER",
        "NO_IMAGE",
        "IMAGE_RECITATION",
        "UNEXPECTED_TOOL_CALL",
        "TOO_MANY_TOOL_CALLS",
        "MISSING_THOUGHT_SIGNATURE",
        "MALFORMED_RESPONSE",
        "ESCALATION",
        "MODEL_ARMOR",
    }
)


class GeminiConfig(ProviderAdapterConfig):
    api_key_env: str = Field(default="GEMINI_API_KEY", min_length=1, max_length=100)
    base_url: AnyHttpUrl | None = None
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    def api_key(self, environ: Mapping[str, str] | None = None) -> str:
        return require_api_key("Gemini", self.api_key_env, environ)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> GeminiConfig | None:
        env = os.environ if environ is None else environ
        api_key_env = env.get("KAIRO_GEMINI_API_KEY_ENV")
        if not api_key_env:
            api_key_env = "GEMINI_API_KEY" if env.get("GEMINI_API_KEY") else "GOOGLE_API_KEY"
        if not env.get(api_key_env):
            return None
        base_url = env.get("KAIRO_GEMINI_BASE_URL")
        return cls(
            api_key_env=api_key_env,
            base_url=base_url or None,
            timeout_seconds=float(env.get("KAIRO_GEMINI_TIMEOUT_SECONDS", "30")),
        )


class GeminiProvider(ModelProvider):
    def __init__(self, config: GeminiConfig, client: genai.Client | None = None) -> None:
        self.config = config
        self._owns_client = client is None
        if client is None:
            options = types.HttpOptions(
                base_url=str(config.base_url) if config.base_url else None,
                timeout=config.timeout_seconds,
            )
            client = genai.Client(api_key=config.api_key(), http_options=options)
        self._client = client

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def capabilities(self) -> ModelCapabilities:
        return self.config.capabilities

    def capabilities_for(self, model: str) -> ModelCapabilities:
        return self.config.capabilities_for(model)

    async def aclose(self) -> None:
        if self._owns_client:
            result = self._client.close()
            if hasattr(result, "__await__"):
                await result

    async def list_models(self) -> list[ModelDescriptor]:
        try:
            pager = await self._client.aio.models.list()
            descriptors: list[ModelDescriptor] = []
            async for model in pager:
                model_id = getattr(model, "name", None)
                if not isinstance(model_id, str) or not model_id:
                    raise ProviderError(
                        "Gemini returned an invalid model entry",
                        code="provider.invalid_response",
                        retryable=False,
                        details={"operation": "list_models"},
                    )
                descriptors.append(
                    ModelDescriptor(
                        id=model_id,
                        name=getattr(model, "display_name", None),
                        capabilities=self.capabilities_for(model_id),
                    )
                )
            return descriptors
        except ProviderError:
            raise
        except Exception as error:
            raise self._translate_error(error, "list_models") from error

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.require_capabilities(request.model, tool_calls=bool(request.tools))
        contents, config = self._payload(request)
        try:
            response = await self._client.aio.models.generate_content(
                model=request.model,
                contents=contents,
                config=config,
            )
        except Exception as error:
            raise self._translate_error(error, "complete") from error
        return self._response_from_gemini(response)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamChunk]:
        self.require_capabilities(
            request.model,
            streaming=True,
            tool_calls=bool(request.tools),
        )
        contents, config = self._payload(request)
        try:
            responses = self._client.aio.models.generate_content_stream(
                model=request.model,
                contents=contents,
                config=config,
            )
            previous_usage = Usage()
            async for response in responses:
                parts = self._parts(response, "stream")
                raw_usage = self._usage(response)
                delta_usage = usage_delta(raw_usage, previous_usage)
                previous_usage = previous_usage.model_copy(
                    update={
                        field: value
                        for field, value in raw_usage.model_dump().items()
                        if value is not None
                    }
                )
                tool_deltas = self._tool_deltas(parts)
                finish_reason = self._finish_reason(response, bool(tool_deltas))
                yield ModelStreamChunk(
                    content_delta="".join(part.text or "" for part in parts),
                    tool_calls=tool_deltas,
                    usage=delta_usage,
                    done=finish_reason is not None,
                    finish_reason=finish_reason,
                )
        except ProviderError:
            raise
        except Exception as error:
            raise self._translate_error(error, "stream") from error

    def _payload(
        self, request: ModelRequest
    ) -> tuple[list[types.Content], types.GenerateContentConfig]:
        system_parts: list[str] = []
        contents: list[types.Content] = []
        for message in request.messages:
            if message.role == ModelRole.SYSTEM:
                system_parts.append(message.content)
            elif message.role == ModelRole.TOOL:
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    id=message.tool_call_id,
                                    name=message.tool_name or "",
                                    response={"output": message.content},
                                )
                            )
                        ],
                    )
                )
            else:
                parts: list[types.Part] = []
                if message.content:
                    parts.append(types.Part.from_text(text=message.content))
                for call in message.tool_calls:
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                id=call.id,
                                name=call.name,
                                args=call.arguments,
                            )
                        )
                    )
                contents.append(
                    types.Content(
                        role="model" if message.role == ModelRole.ASSISTANT else "user",
                        parts=parts,
                    )
                )

        config_values: dict[str, Any] = {
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if system_parts:
            config_values["system_instruction"] = "\n".join(system_parts)
        if request.temperature is not None:
            config_values["temperature"] = request.temperature
        if request.max_tokens is not None:
            config_values["max_output_tokens"] = request.max_tokens
        if request.tools:
            config_values["tools"] = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=spec.name,
                            description=spec.description,
                            parameters=spec.input_schema,
                        )
                    ]
                )
                for spec in request.tools
            ]
        config_values.update(self._options(request.options))
        return contents, types.GenerateContentConfig(**config_values)

    @staticmethod
    def _options(options: dict[str, Any]) -> dict[str, Any]:
        for key, value in options.items():
            if key not in GEMINI_OPTIONS:
                raise ConfigError(
                    "Unsupported Gemini model option",
                    code="provider.invalid_option",
                    details={"provider": "gemini", "option": key},
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(
                    "Gemini option must be numeric",
                    code="provider.invalid_option",
                    details={"provider": "gemini", "option": key},
                )
        return dict(options)

    def _response_from_gemini(self, response: Any) -> ModelResponse:
        parts = self._parts(response, "complete")
        tool_calls = self._tool_calls(parts)
        return ModelResponse(
            content="".join(part.text or "" for part in parts),
            tool_calls=tool_calls,
            usage=self._usage(response),
            finish_reason=self._finish_reason(response, bool(tool_calls)),
        )

    @staticmethod
    def _parts(response: Any, operation: str) -> list[types.Part]:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            raise ProviderError(
                "Gemini returned no candidates",
                code="provider.invalid_response",
                retryable=False,
                details={"operation": operation},
            )
        content = getattr(candidates[0], "content", None)
        if content is None:
            raise ProviderError(
                "Gemini returned a candidate without content",
                code="provider.invalid_response",
                retryable=False,
                details={"operation": operation},
            )
        return list(getattr(content, "parts", None) or [])

    @staticmethod
    def _tool_calls(parts: list[types.Part]) -> list[ToolCallRequest]:
        calls: list[ToolCallRequest] = []
        for part in parts:
            function_call = getattr(part, "function_call", None)
            if function_call is None:
                continue
            arguments = require_tool_arguments("Gemini", getattr(function_call, "args", None) or {})
            calls.append(
                build_tool_call(
                    "Gemini",
                    call_id=getattr(function_call, "id", None) or str(uuid.uuid4()),
                    name=getattr(function_call, "name", None),
                    arguments=arguments,
                )
            )
        return calls

    @staticmethod
    def _tool_deltas(parts: list[types.Part]) -> list[ToolCallDelta]:
        deltas: list[ToolCallDelta] = []
        for index, part in enumerate(parts):
            function_call = getattr(part, "function_call", None)
            if function_call is None:
                continue
            arguments = getattr(function_call, "args", None)
            deltas.append(
                ToolCallDelta(
                    index=index,
                    id=getattr(function_call, "id", None),
                    name=getattr(function_call, "name", None),
                    arguments=arguments if isinstance(arguments, dict) and arguments else None,
                )
            )
        return deltas

    @staticmethod
    def _usage(response: Any) -> Usage:
        metadata = getattr(response, "usage_metadata", None)
        if metadata is None:
            return Usage()
        return Usage(
            input_tokens=nonnegative_counter(metadata, "prompt_token_count"),
            output_tokens=nonnegative_counter(metadata, "candidates_token_count"),
            total_tokens=nonnegative_counter(metadata, "total_token_count"),
        )

    @staticmethod
    def _finish_reason(response: Any, has_tool_calls: bool) -> FinishReason | None:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return None
        raw_reason = getattr(candidates[0], "finish_reason", None)
        if raw_reason is None:
            return None
        reason = getattr(raw_reason, "name", None) or str(raw_reason)
        if reason == "STOP":
            return FinishReason.TOOL_CALL if has_tool_calls else FinishReason.STOP
        if reason == "MAX_TOKENS":
            return FinishReason.LENGTH
        if reason == "FINISH_REASON_UNSPECIFIED":
            return FinishReason.TOOL_CALL if has_tool_calls else None
        if reason in GEMINI_INCOMPLETE_REASONS:
            return FinishReason.INCOMPLETE
        raise ProviderError(
            "Gemini returned an unsupported finish reason",
            code="provider.invalid_finish_reason",
            retryable=False,
            details={"operation": "response"},
        )

    @staticmethod
    def _translate_error(error: Exception, operation: str) -> ProviderError:
        details: dict[str, str | int | float | bool] = {"operation": operation}
        if isinstance(error, genai_errors.APIError):
            status = getattr(error, "code", None)
            if isinstance(status, int):
                details["statusCode"] = status
            if status in (401, 403):
                return ProviderError(
                    "Gemini authentication failed",
                    code="provider.auth",
                    retryable=False,
                    details=details,
                )
            if status == 429:
                return ProviderError(
                    "Gemini rate limit reached",
                    code="provider.rate_limited",
                    retryable=True,
                    details=details,
                )
            if isinstance(status, int) and status >= 500:
                return ProviderError(
                    "Gemini service error",
                    code=f"provider.http_{status}",
                    retryable=True,
                    details=details,
                )
            return ProviderError(
                "Gemini returned an API error",
                code=f"provider.http_{status}" if isinstance(status, int) else "provider.api_error",
                retryable=False,
                details=details,
            )
        if isinstance(error, TimeoutError):
            return ProviderError(
                "Gemini request timed out",
                code="provider.timeout",
                retryable=True,
                details=details,
            )
        return ProviderError(
            "Gemini provider raised an unexpected error",
            code="provider.unexpected",
            retryable=False,
            details={"operation": operation, "errorType": type(error).__name__},
        )
