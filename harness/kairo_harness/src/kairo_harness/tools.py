from abc import ABC, abstractmethod

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from kairo_harness.domain import ToolCallRequest, ToolResult, ToolSpec
from kairo_harness.errors import ConfigError, ToolExecutionError


class ToolExecutor(ABC):
    @abstractmethod
    async def execute(self, call: ToolCallRequest, spec: ToolSpec) -> ToolResult: ...


class ToolCallValidator:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs = {spec.name: spec for spec in specs}
        self._validators: dict[str, Draft202012Validator] = {}
        for spec in specs:
            try:
                Draft202012Validator.check_schema(spec.input_schema)
                self._validators[spec.name] = Draft202012Validator(spec.input_schema)
            except SchemaError as error:
                raise ConfigError(
                    "Tool input_schema is not a valid JSON Schema",
                    details={"toolName": spec.name, "schemaError": error.validator or "invalid"},
                ) from error

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
