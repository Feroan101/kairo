from __future__ import annotations

import inspect
import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError

from kairo_harness.domain import (
    ToolCallRequest,
    ToolErrorInfo,
    ToolResult,
    ToolSpec,
    validate_permission_names,
)
from kairo_harness.errors import ConfigError, ToolExecutionError

type ToolHandlerResult = ToolResult | dict[str, Any] | list[Any] | str | int | float | bool | None
type ToolHandler = Callable[[dict[str, Any]], ToolHandlerResult | Awaitable[ToolHandlerResult]]

_SAFE_ERROR_MESSAGES = {
    "tool.timeout": "Tool execution timed out",
    "tool.unexpected": "Tool execution failed",
    "tool.invalid_result": "Tool returned an invalid result",
}


def _build_validators(
    specs: Sequence[ToolSpec],
) -> tuple[dict[str, ToolSpec], dict[str, Draft202012Validator]]:
    specs_by_name: dict[str, ToolSpec] = {}
    validators: dict[str, Draft202012Validator] = {}
    for spec in specs:
        if spec.name in specs_by_name:
            raise ConfigError(
                "Duplicate tool name",
                details={"toolName": spec.name},
            )
        try:
            Draft202012Validator.check_schema(spec.input_schema)
            validators[spec.name] = Draft202012Validator(spec.input_schema)
        except SchemaError as error:
            raise ConfigError(
                "Tool input_schema is not a valid JSON Schema",
                details={"toolName": spec.name, "schemaError": error.validator or "invalid"},
            ) from error
        specs_by_name[spec.name] = spec.model_copy(deep=True)
    return specs_by_name, validators


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    handler: ToolHandler


@dataclass(frozen=True)
class ToolRegistrySnapshot:
    tools: tuple[Tool, ...]

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(tool.spec.model_copy(deep=True) for tool in self.tools)

    def get(self, name: str) -> Tool | None:
        for tool in self.tools:
            if tool.spec.name == name:
                return tool
        return None


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not callable(tool.handler):
            raise ConfigError("Tool handler must be callable")
        spec = tool.spec.model_copy(deep=True)
        _build_validators([spec])
        if spec.name in self._tools:
            raise ConfigError(
                "Duplicate tool name",
                details={"toolName": spec.name},
            )
        self._tools[spec.name] = Tool(spec=spec, handler=tool.handler)

    def snapshot(self) -> ToolRegistrySnapshot:
        return ToolRegistrySnapshot(
            tools=tuple(
                Tool(spec=tool.spec.model_copy(deep=True), handler=tool.handler)
                for tool in self._tools.values()
            )
        )


class ToolExecutor(ABC):
    @abstractmethod
    async def execute(self, call: ToolCallRequest, spec: ToolSpec) -> ToolResult: ...

    async def cancel(self, call: ToolCallRequest) -> None:
        return None

    async def aclose(self) -> None:
        return None


class ToolCallValidator:
    def __init__(
        self,
        tools: Sequence[ToolSpec | Tool] | ToolRegistrySnapshot,
        granted_permissions: Iterable[str] = (),
    ) -> None:
        specs = (
            tools.specs()
            if isinstance(tools, ToolRegistrySnapshot)
            else tuple(tool.spec if isinstance(tool, Tool) else tool for tool in tools)
        )
        self._specs, self._validators = _build_validators(specs)
        self._granted_permissions = validate_permission_names(frozenset(granted_permissions))

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(spec.model_copy(deep=True) for spec in self._specs.values())

    def authorized_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(spec for spec in self.specs() if self._is_authorized(spec))

    def validate(self, call: ToolCallRequest) -> ToolSpec:
        spec = self._specs.get(call.name)
        if spec is None:
            raise ToolExecutionError(
                "Model requested an unknown tool",
                code="tool.unknown",
                details={"toolName": call.name},
            )
        if not spec.allowed:
            raise ToolExecutionError(
                "Model requested a tool that is not permitted",
                code="tool.forbidden",
                details={"toolName": call.name},
            )
        missing_permissions = spec.required_permissions - self._granted_permissions
        if missing_permissions:
            raise ToolExecutionError(
                "Model requested a tool without the required permissions",
                code="tool.permission_denied",
                details={
                    "toolName": call.name,
                    "missingPermissions": ", ".join(sorted(missing_permissions)),
                },
            )

        errors = sorted(
            self._validators[call.name].iter_errors(call.arguments),
            key=lambda error: str(error.validator),
        )
        if errors:
            first = errors[0]
            raise ToolExecutionError(
                "Tool arguments did not match the declared schema",
                code="tool.invalid_arguments",
                details={
                    "toolName": call.name,
                    "keyword": first.validator or "invalid",
                    "instancePath": "/" + "/".join(str(part) for part in first.absolute_path),
                },
            )
        return spec

    def _is_authorized(self, spec: ToolSpec) -> bool:
        return spec.allowed and spec.required_permissions <= self._granted_permissions


class RegistryToolExecutor(ToolExecutor):
    def __init__(
        self,
        registry: ToolRegistry | ToolRegistrySnapshot,
        granted_permissions: Iterable[str] = (),
    ) -> None:
        self.snapshot = registry.snapshot() if isinstance(registry, ToolRegistry) else registry
        self._validator = ToolCallValidator(self.snapshot, granted_permissions)

    def bind_validator(self, validator: ToolCallValidator) -> None:
        self._validator = validator

    async def execute(self, call: ToolCallRequest, spec: ToolSpec) -> ToolResult:
        try:
            self._validator.validate(call)
            registered = self.snapshot.get(call.name)
            if registered is None:
                raise ToolExecutionError(
                    "Tool is not registered",
                    code="tool.unknown",
                )
            raw_result = registered.handler(call.arguments)
            if inspect.isawaitable(raw_result):
                raw_result = await raw_result
            result = self._normalize(raw_result, call.id)
        except TimeoutError:
            result = self._error_result(
                call.id,
                "tool.timeout",
                _SAFE_ERROR_MESSAGES["tool.timeout"],
                True,
            )
        except ToolExecutionError as error:
            result = self._error_result(
                call.id,
                error.code,
                "Tool handler rejected the request",
                error.retryable,
            )
        except Exception:
            result = self._error_result(
                call.id,
                "tool.unexpected",
                _SAFE_ERROR_MESSAGES["tool.unexpected"],
                False,
            )
        return self._sanitize(result, call.id)

    @staticmethod
    def _invalid_result(call_id: str) -> ToolResult:
        return ToolResult(
            tool_call_id=call_id,
            status="error",
            error=ToolErrorInfo(
                code="tool.invalid_result",
                message=_SAFE_ERROR_MESSAGES["tool.invalid_result"],
                retryable=False,
            ),
        )

    @staticmethod
    def _normalize(raw_result: ToolHandlerResult, call_id: str) -> ToolResult:
        if isinstance(raw_result, ToolResult):
            result = raw_result.model_copy(deep=True)
        elif isinstance(raw_result, dict):
            try:
                result = ToolResult.model_validate(raw_result)
            except ValidationError:
                return RegistryToolExecutor._invalid_result(call_id)
        else:
            result = ToolResult(tool_call_id=call_id, status="ok", output=raw_result)

        try:
            json.dumps(result.output)
        except (TypeError, ValueError):
            return RegistryToolExecutor._invalid_result(call_id)
        return result

    @staticmethod
    def _error_result(
        call_id: str,
        code: str,
        message: str,
        retryable: bool,
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=call_id,
            status="error",
            error=ToolErrorInfo(code=code, message=message, retryable=retryable),
        )

    @staticmethod
    def _sanitize(result: ToolResult, call_id: str) -> ToolResult:
        if result.tool_call_id != call_id:
            return RegistryToolExecutor._error_result(
                call_id,
                "tool.invalid_result",
                _SAFE_ERROR_MESSAGES["tool.invalid_result"],
                False,
            )
        if result.status == "ok" or result.error is None:
            return result
        sanitized = result.model_copy(deep=True)
        if sanitized.error is not None:
            sanitized.error.message = _SAFE_ERROR_MESSAGES.get(
                sanitized.error.code,
                "Tool handler failed",
            )
        return sanitized
