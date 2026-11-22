import pytest
from kairo_harness.errors import ConfigError, ToolExecutionError
from kairo_harness.tools import ToolCallValidator
from support import make_tool, tool_call


def test_validator_rejects_unknown_tools() -> None:
    validator = ToolCallValidator([make_tool()])
    with pytest.raises(ToolExecutionError) as error_info:
        validator.validate(tool_call(name="missing", value="x"))
    assert error_info.value.code == "tool.unknown"


def test_validator_rejects_disallowed_tools() -> None:
    validator = ToolCallValidator([make_tool(allowed=False)])
    with pytest.raises(ToolExecutionError) as error_info:
        validator.validate(tool_call(value="x"))
    assert error_info.value.code == "tool.forbidden"


def test_validator_rejects_arguments_outside_schema() -> None:
    validator = ToolCallValidator([make_tool()])
    with pytest.raises(ToolExecutionError) as error_info:
        validator.validate(tool_call(value=123))
    assert error_info.value.code == "tool.invalid_arguments"
    assert error_info.value.details["toolName"] == "echo"


def test_validator_accepts_allowed_tool_with_valid_arguments() -> None:
    spec = make_tool()
    validator = ToolCallValidator([spec])
    assert validator.validate(tool_call(value="hello")) is spec


def test_validator_rejects_invalid_json_schema_at_construction() -> None:
    spec = make_tool()
    spec.input_schema = {"type": "not-a-json-schema-type"}
    with pytest.raises(ConfigError):
        ToolCallValidator([spec])
