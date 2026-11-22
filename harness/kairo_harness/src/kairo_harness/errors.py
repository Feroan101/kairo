from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class ErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False
    details: dict[str, str | int | float | bool] = Field(default_factory=dict)


class HarnessError(Exception):
    default_code: ClassVar[str] = "harness.error"
    default_retryable: ClassVar[bool] = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        retryable: bool | None = None,
        details: dict[str, str | int | float | bool] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or type(self).default_code
        self.retryable = type(self).default_retryable if retryable is None else retryable
        self.details = details or {}

    def error_info(self) -> ErrorInfo:
        return ErrorInfo(
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            details=self.details,
        )


class ConfigError(HarnessError):
    default_code = "harness.invalid_config"


class ProviderError(HarnessError):
    default_code = "provider.error"
    default_retryable = True

    def error_info(self) -> ErrorInfo:
        return ErrorInfo(
            code=self.code,
            message="Model provider request failed",
            retryable=self.retryable,
            details=self.details,
        )


class InvalidModelResponseError(HarnessError):
    default_code = "model.invalid_response"
    default_retryable = False


class ToolExecutionError(HarnessError):
    default_code = "tool.execution_error"
    default_retryable = False


class ExecutionLimitError(HarnessError):
    default_code = "execution.limit_exceeded"
    default_retryable = False


class ExecutionTimeoutError(HarnessError):
    default_code = "execution.timeout"
    default_retryable = True
