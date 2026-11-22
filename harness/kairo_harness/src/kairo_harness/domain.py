from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from kairo_harness.errors import InvalidModelResponseError

type OptionValue = str | int | float | bool

TOOL_CALL_ACTION_TYPE = "tool_call"
PERMISSION_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


def validate_permission_names(values: frozenset[str]) -> frozenset[str]:
    for value in values:
        if not PERMISSION_NAME_PATTERN.fullmatch(value):
            raise ValueError("permission names must be lowercase identifiers")
    return values


class ModelRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(StrEnum):
    STOP = "stop"
    TOOL_CALL = "tool_call"
    LENGTH = "length"


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ModelMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ModelRole
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    description: str = Field(min_length=1, max_length=1000)
    input_schema: dict[str, Any]
    allowed: bool = False
    required_permissions: frozenset[str] = Field(default_factory=frozenset)
    timeout_seconds: float = Field(default=10.0, gt=0, le=300)

    @field_validator("required_permissions")
    @classmethod
    def validate_required_permissions(cls, value: frozenset[str]) -> frozenset[str]:
        return validate_permission_names(value)

    @model_validator(mode="after")
    def validate_input_schema(self) -> ToolSpec:
        if self.input_schema.get("type") != "object":
            raise ValueError("tool input_schema must describe an object")
        return self


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str = Field(min_length=1, max_length=200)
    status: Literal["ok", "error"]
    output: Any = None
    error: ToolErrorInfo | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> ToolResult:
        if self.status == "ok" and self.error is not None:
            raise ValueError("successful tool results cannot contain an error")
        if self.status == "error" and self.error is None:
            raise ValueError("failed tool results require an error")
        return self


class FinalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["final"] = "final"
    content: str


class ToolCallDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[TOOL_CALL_ACTION_TYPE] = TOOL_CALL_ACTION_TYPE
    tool_calls: list[ToolCallRequest] = Field(min_length=1)


type ModelDecision = FinalDecision | ToolCallDecision


class ModelCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    streaming: bool = False
    tool_calls: bool = False
    structured_output: bool = False


class ModelDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str | None = None
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    messages: list[ModelMessage]
    tools: list[ToolSpec] = Field(default_factory=list)
    options: dict[str, OptionValue] = Field(default_factory=dict)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    finish_reason: FinishReason = FinishReason.STOP


class ModelStreamChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_delta: str = ""
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    done: bool = False


def parse_model_decision(response: ModelResponse) -> ModelDecision:
    if response.tool_calls:
        return ToolCallDecision(tool_calls=response.tool_calls)

    if not response.content:
        raise InvalidModelResponseError(
            "Model response contained neither content nor a tool call",
            details={"finishReason": response.finish_reason.value},
        )

    try:
        candidate: Any = json.loads(response.content)
    except ValueError:
        return FinalDecision(content=response.content)

    if not isinstance(candidate, dict) or candidate.get("type") != TOOL_CALL_ACTION_TYPE:
        return FinalDecision(content=response.content)

    try:
        return ToolCallDecision.model_validate(candidate)
    except ValidationError as error:
        raise InvalidModelResponseError(
            "Model returned a malformed tool-call action",
            details={"issueCount": len(error.errors())},
        ) from error
