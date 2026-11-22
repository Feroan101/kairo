from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from kairo_harness.domain import Usage
from kairo_harness.errors import ErrorInfo


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECOVERY = "recovery"


class TerminalReason(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    LIMIT_EXCEEDED = "limit_exceeded"
    TIMEOUT = "timeout"
    MODEL_ERROR = "model_error"
    INVALID_MODEL_RESPONSE = "invalid_model_response"
    TOOL_ERROR = "tool_error"
    CONFIGURATION_ERROR = "configuration_error"
    INTERNAL_ERROR = "internal_error"


class ExecutionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: UUID
    status: ExecutionStatus = ExecutionStatus.QUEUED
    iteration: int = Field(default=0, ge=0)
    model_requests: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    usage: Usage = Field(default_factory=Usage)
    terminal_reason: TerminalReason | None = None
    error: ErrorInfo | None = None


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: UUID
    status: ExecutionStatus
    output: str | None = None
    error: ErrorInfo | None = None
    state: ExecutionState
