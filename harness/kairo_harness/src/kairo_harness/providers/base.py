from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kairo_harness.domain import (
    ModelCapabilities,
    ModelDescriptor,
    ModelRequest,
    ModelResponse,
    ModelStreamChunk,
    ToolCallRequest,
)
from kairo_harness.errors import ConfigError, ProviderError

type ProviderErrorDetails = dict[str, str | int | float | bool]


class ProviderAdapterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: ModelCapabilities = Field(
        default_factory=lambda: ModelCapabilities(streaming=True, tool_calls=True)
    )
    model_capabilities: dict[str, ModelCapabilities] = Field(default_factory=dict)

    def capabilities_for(self, model: str) -> ModelCapabilities:
        return self.model_capabilities.get(model, self.capabilities)


def resolve_api_key_env(environ: Mapping[str, str], name: str, default: str) -> str:
    return environ.get(name, default)


def require_api_key(
    provider_label: str,
    api_key_env_name: str,
    environ: Mapping[str, str] | None = None,
) -> str:
    env = os.environ if environ is None else environ
    api_key = env.get(api_key_env_name)
    if not api_key:
        raise ConfigError(
            f"{provider_label} API key is not configured",
            code="provider.missing_credentials",
            details={"provider": provider_label.lower(), "envVar": api_key_env_name},
        )
    return api_key


def nonnegative_counter(value: Any, field: str) -> int | None:
    counter = getattr(value, field, None)
    if isinstance(counter, bool) or not isinstance(counter, int) or counter < 0:
        return None
    return counter


def require_tool_arguments(
    provider_label: str,
    value: Any,
    *,
    subject: str = "tool arguments",
    parse_json: bool = False,
) -> dict[str, Any]:
    arguments = value
    if parse_json and isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError as error:
            raise ProviderError(
                f"{provider_label} returned malformed {subject}",
                code="provider.invalid_tool_arguments",
                retryable=False,
            ) from error
    if not isinstance(arguments, dict):
        raise ProviderError(
            f"{provider_label} returned {subject} that was not an object",
            code="provider.invalid_tool_arguments",
            retryable=False,
        )
    return arguments


def build_tool_call(
    provider_label: str,
    *,
    call_id: Any,
    name: Any,
    arguments: dict[str, Any],
) -> ToolCallRequest:
    try:
        return ToolCallRequest(id=call_id, name=name, arguments=arguments)
    except ValidationError as error:
        raise ProviderError(
            f"{provider_label} returned an invalid tool call",
            code="provider.invalid_tool_call",
            retryable=False,
            details={"issueCount": len(error.errors())},
        ) from error


def translate_sdk_error(
    error: Exception,
    *,
    operation: str,
    provider_label: str,
    authentication_error: type[Exception],
    rate_limit_error: type[Exception],
    timeout_error: type[Exception],
    connection_error: type[Exception],
    response_validation_error: type[Exception],
    api_error: type[Exception],
) -> ProviderError:
    details: ProviderErrorDetails = {"operation": operation}
    if isinstance(error, authentication_error):
        return ProviderError(
            f"{provider_label} authentication failed",
            code="provider.auth",
            retryable=False,
            details=details,
        )
    if isinstance(error, rate_limit_error):
        return ProviderError(
            f"{provider_label} rate limit reached",
            code="provider.rate_limited",
            retryable=True,
            details=details,
        )
    if isinstance(error, timeout_error):
        return ProviderError(
            f"{provider_label} request timed out",
            code="provider.timeout",
            retryable=True,
            details=details,
        )
    if isinstance(error, connection_error):
        return ProviderError(
            f"Could not connect to {provider_label}",
            code="provider.connection",
            retryable=True,
            details=details,
        )
    if isinstance(error, response_validation_error):
        return ProviderError(
            f"{provider_label} returned an invalid response",
            code="provider.invalid_response",
            retryable=False,
            details=details,
        )
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        details["statusCode"] = status
    if isinstance(error, api_error):
        return ProviderError(
            f"{provider_label} returned an API error",
            code=f"provider.http_{status}" if isinstance(status, int) else "provider.api_error",
            retryable=status == 429 or isinstance(status, int) and status >= 500,
            details=details,
        )
    if isinstance(error, httpx.TimeoutException):
        return ProviderError(
            f"{provider_label} request timed out",
            code="provider.timeout",
            retryable=True,
            details=details,
        )
    if isinstance(error, httpx.ConnectError):
        return ProviderError(
            f"Could not connect to {provider_label}",
            code="provider.connection",
            retryable=True,
            details=details,
        )
    if isinstance(error, httpx.HTTPError):
        return ProviderError(
            f"{provider_label} HTTP request failed",
            code="provider.http_error",
            retryable=False,
            details=details,
        )
    return ProviderError(
        f"{provider_label} provider raised an unexpected error",
        code="provider.unexpected",
        retryable=False,
        details={"operation": operation, "errorType": type(error).__name__},
    )


class ModelProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> ModelCapabilities: ...

    def capabilities_for(self, model: str) -> ModelCapabilities:
        return self.capabilities

    def require_capabilities(
        self,
        model: str,
        *,
        streaming: bool = False,
        tool_calls: bool = False,
    ) -> None:
        capabilities = self.capabilities_for(model)
        missing: list[str] = []
        if streaming and not capabilities.streaming:
            missing.append("streaming")
        if tool_calls and not capabilities.tool_calls:
            missing.append("tool_calls")
        if missing:
            raise ConfigError(
                "Model does not support requested capabilities",
                code="provider.capability_unsupported",
                details={
                    "provider": self.name,
                    "model": model,
                    "capabilities": ",".join(missing),
                },
            )

    @abstractmethod
    async def list_models(self) -> list[ModelDescriptor]: ...

    @abstractmethod
    async def complete(self, request: ModelRequest) -> ModelResponse: ...

    @abstractmethod
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamChunk]: ...
