from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
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
    INCOMPLETE = "incomplete"


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


class ToolCallDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    id: str | None = Field(default=None, min_length=1, max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=64)
    arguments: dict[str, Any] | None = None
    arguments_delta: str = ""


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
    tool_calls: list[ToolCallDelta | ToolCallRequest] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    done: bool = False
    finish_reason: FinishReason | None = None


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


@dataclass
class _ToolCallAccumulator:
    id: str = ""
    name: str = ""
    arguments_text: str = ""
    arguments_object: dict[str, Any] | None = None


def _merge_text(existing: str, fragment: str | None) -> str:
    if not fragment:
        return existing
    if not existing:
        return fragment
    if fragment == existing or existing.startswith(fragment):
        return existing
    if fragment.startswith(existing):
        return fragment
    return existing + fragment


def _merge_dict(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge_dict(current, value)
        else:
            merged[key] = value
    return merged


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _merge_arguments(accumulator: _ToolCallAccumulator, value: dict[str, Any] | str) -> None:
    if isinstance(value, dict):
        if not accumulator.arguments_text:
            accumulator.arguments_object = _merge_dict({}, value)
            accumulator.arguments_text = _canonical_json(accumulator.arguments_object)
            return
        try:
            existing = json.loads(accumulator.arguments_text)
        except ValueError as error:
            raise InvalidModelResponseError(
                "Streamed tool arguments were invalid",
                code="model.invalid_stream_tool_arguments",
            ) from error
        if not isinstance(existing, dict):
            raise InvalidModelResponseError(
                "Streamed tool arguments were invalid",
                code="model.invalid_stream_tool_arguments",
            )
        if existing == value:
            accumulator.arguments_object = existing
            return
        accumulator.arguments_object = _merge_dict(existing, value)
        accumulator.arguments_text = _canonical_json(accumulator.arguments_object)
        return

    if not value:
        return
    if not accumulator.arguments_text:
        accumulator.arguments_text = value
        accumulator.arguments_object = None
        return
    try:
        existing = json.loads(accumulator.arguments_text)
        incoming = json.loads(value)
    except ValueError:
        accumulator.arguments_text += value
        accumulator.arguments_object = None
        return
    if isinstance(existing, dict) and isinstance(incoming, dict):
        if existing == incoming:
            accumulator.arguments_object = existing
            return
        accumulator.arguments_object = _merge_dict(existing, incoming)
        accumulator.arguments_text = _canonical_json(accumulator.arguments_object)
        return
    accumulator.arguments_text += value
    accumulator.arguments_object = None


def _finish_arguments(accumulator: _ToolCallAccumulator) -> dict[str, Any]:
    if accumulator.arguments_object is not None:
        return accumulator.arguments_object
    if not accumulator.arguments_text:
        return {}
    try:
        parsed = json.loads(accumulator.arguments_text)
    except ValueError as error:
        raise InvalidModelResponseError(
            "Streamed tool arguments were invalid",
            code="model.invalid_stream_tool_arguments",
        ) from error
    if not isinstance(parsed, dict):
        raise InvalidModelResponseError(
            "Streamed tool arguments were invalid",
            code="model.invalid_stream_tool_arguments",
        )
    return parsed


def _accumulate_tool_calls(chunks: Sequence[ModelStreamChunk]) -> list[ToolCallRequest]:
    accumulators: dict[int, _ToolCallAccumulator] = {}
    order: list[int] = []
    next_request_key = -1

    for chunk in chunks:
        for item in chunk.tool_calls:
            if isinstance(item, ToolCallRequest):
                key = next_request_key
                next_request_key -= 1
                id_fragment: str | None = item.id
                name_fragment: str | None = item.name
                arguments_object: dict[str, Any] | None = item.arguments
                arguments_delta = ""
            else:
                key = item.index
                id_fragment = item.id
                name_fragment = item.name
                arguments_object = item.arguments
                arguments_delta = item.arguments_delta

            if key not in accumulators:
                accumulators[key] = _ToolCallAccumulator()
                order.append(key)
            accumulator = accumulators[key]
            accumulator.id = _merge_text(accumulator.id, id_fragment)
            accumulator.name = _merge_text(accumulator.name, name_fragment)
            if arguments_object is not None:
                _merge_arguments(accumulator, arguments_object)
            if arguments_delta:
                _merge_arguments(accumulator, arguments_delta)

    calls: list[ToolCallRequest] = []
    seen_ids: set[str] = set()
    for key in order:
        accumulator = accumulators[key]
        arguments = _finish_arguments(accumulator)
        try:
            call = ToolCallRequest(id=accumulator.id, name=accumulator.name, arguments=arguments)
        except ValidationError as error:
            raise InvalidModelResponseError(
                "Model returned an incomplete streamed tool call",
                details={"issueCount": len(error.errors())},
            ) from error
        if call.id in seen_ids:
            raise InvalidModelResponseError(
                "Model returned duplicate streamed tool call IDs",
                code="model.invalid_stream_tool_call",
            )
        seen_ids.add(call.id)
        calls.append(call)
    return calls


def _aggregate_usage(chunks: Sequence[ModelStreamChunk]) -> Usage:
    usage = Usage()
    for chunk in chunks:
        for field_name in ("input_tokens", "output_tokens", "total_tokens"):
            incoming = getattr(chunk.usage, field_name)
            if incoming is None:
                continue
            current = getattr(usage, field_name)
            if current is None or incoming > current:
                setattr(usage, field_name, incoming)
    if usage.total_tokens is None and (
        usage.input_tokens is not None or usage.output_tokens is not None
    ):
        usage.total_tokens = (usage.input_tokens or 0) + (usage.output_tokens or 0)
    return usage


def _aggregate_finish_reason(
    chunks: Sequence[ModelStreamChunk], tool_calls: Sequence[ToolCallRequest]
) -> FinishReason:
    priority = {
        FinishReason.STOP: 1,
        FinishReason.LENGTH: 2,
        FinishReason.TOOL_CALL: 3,
        FinishReason.INCOMPLETE: 4,
    }
    reason: FinishReason | None = None
    saw_done = False
    for chunk in chunks:
        saw_done = saw_done or chunk.done
        if chunk.finish_reason is not None and (
            reason is None or priority[chunk.finish_reason] >= priority[reason]
        ):
            reason = chunk.finish_reason
    if reason == FinishReason.INCOMPLETE:
        return FinishReason.INCOMPLETE
    if reason is None and not saw_done:
        return FinishReason.INCOMPLETE
    if tool_calls:
        return FinishReason.TOOL_CALL
    if reason is not None:
        return reason
    return FinishReason.STOP


def aggregate_stream_chunks(chunks: Sequence[ModelStreamChunk]) -> ModelResponse:
    tool_calls = _accumulate_tool_calls(chunks)
    return ModelResponse(
        content="".join(chunk.content_delta for chunk in chunks),
        tool_calls=tool_calls,
        usage=_aggregate_usage(chunks),
        finish_reason=_aggregate_finish_reason(chunks, tool_calls),
    )
