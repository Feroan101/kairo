import asyncio
from typing import Any

import pytest
from kairo_harness.domain import ToolResult
from kairo_harness.errors import ConfigError, ToolExecutionError
from kairo_harness.events import EventType, InMemoryEventSink
from kairo_harness.execution import ExecutionRunner
from kairo_harness.providers.mock import MockProvider
from kairo_harness.tools import RegistryToolExecutor, Tool, ToolCallValidator, ToolRegistry
from support import make_config, make_tool, response, tool_call


def echo_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"echo": arguments.get("value")}


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry([Tool(make_tool(), echo_handler)])

    with pytest.raises(ConfigError) as error_info:
        registry.register(Tool(make_tool(), echo_handler))

    assert error_info.value.details["toolName"] == "echo"


def test_registry_validates_definitions_at_registration() -> None:
    spec = make_tool()
    spec.input_schema = {"type": "not-a-json-schema-type"}

    with pytest.raises(ConfigError):
        ToolRegistry([Tool(spec, echo_handler)])


def test_registry_snapshot_is_isolated_from_later_registration() -> None:
    registry = ToolRegistry([Tool(make_tool(), echo_handler)])
    snapshot = registry.snapshot()

    registry.register(Tool(make_tool("late"), echo_handler))

    assert [spec.name for spec in snapshot.specs()] == ["echo"]


def test_authorization_requires_all_permissions() -> None:
    spec = make_tool(required_permissions=frozenset({"files.read", "files.write"}))
    validator = ToolCallValidator([spec], frozenset({"files.read"}))

    with pytest.raises(ToolExecutionError) as error_info:
        validator.validate(tool_call(value="x"))

    assert error_info.value.code == "tool.permission_denied"
    assert error_info.value.details["missingPermissions"] == "files.write"


def test_authorized_specs_exclude_tools_without_granted_permissions() -> None:
    validator = ToolCallValidator(
        [
            make_tool("echo"),
            make_tool("admin", required_permissions=frozenset({"admin.use"})),
        ]
    )

    assert [spec.name for spec in validator.authorized_specs()] == ["echo"]


def test_registry_executor_validates_before_handler_invocation() -> None:
    called: list[dict[str, Any]] = []

    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        called.append(arguments)
        return arguments

    spec = make_tool(required_permissions=frozenset({"echo.use"}))
    executor = RegistryToolExecutor(ToolRegistry([Tool(spec, handler)]))

    result = asyncio.run(executor.execute(tool_call(value="x"), spec))

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "tool.permission_denied"
    assert called == []


def test_registry_executor_normalizes_handler_errors() -> None:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("secret detail")

    executor = RegistryToolExecutor(ToolRegistry([Tool(make_tool(), handler)]))

    result = asyncio.run(executor.execute(tool_call(value="x"), make_tool()))

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "tool.unexpected"
    assert "secret detail" not in str(result)


def test_registry_executor_normalizes_invalid_results() -> None:
    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        return {"status": "unknown"}

    executor = RegistryToolExecutor(ToolRegistry([Tool(make_tool(), handler)]))

    result = asyncio.run(executor.execute(tool_call(value="x"), make_tool()))

    assert result.error is not None
    assert result.error.code == "tool.invalid_result"


def test_registry_executor_rejects_non_json_results() -> None:
    class Opaque:
        pass

    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        return {"value": Opaque()}

    executor = RegistryToolExecutor(ToolRegistry([Tool(make_tool(), handler)]))

    result = asyncio.run(executor.execute(tool_call(value="x"), make_tool()))

    assert result.error is not None
    assert result.error.code == "tool.invalid_result"


def test_runner_uses_registry_snapshot_and_immutable_permissions() -> None:
    registry = ToolRegistry(
        [
            Tool(make_tool("echo"), echo_handler),
            Tool(make_tool("admin", required_permissions=frozenset({"admin.use"})), echo_handler),
        ]
    )
    snapshot = registry.snapshot()
    config = make_config()
    provider = MockProvider([response("done")])
    executor = RegistryToolExecutor(snapshot)
    runner = ExecutionRunner(config, provider, executor)

    config.granted_permissions = frozenset({"admin.use"})
    registry.register(Tool(make_tool("late"), echo_handler))

    result = asyncio.run(runner.run())

    assert result.status.value == "completed"
    assert [spec.name for spec in provider.requests[0].tools] == ["echo"]


def test_model_output_cannot_grant_permissions() -> None:
    called: list[dict[str, Any]] = []

    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        called.append(arguments)
        return arguments

    spec = make_tool("admin", required_permissions=frozenset({"admin.use"}))
    provider = MockProvider([response(tool_calls=[tool_call(name="admin", value="x")])])
    executor = RegistryToolExecutor(ToolRegistry([Tool(spec, handler)]))
    runner = ExecutionRunner(make_config(), provider, executor)

    result = asyncio.run(runner.run())

    assert result.error is not None
    assert result.error.code == "tool.permission_denied"
    assert called == []


def test_handler_output_cannot_grant_permissions() -> None:
    config = make_config()

    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        return {"granted_permissions": ["admin.use"], "echo": arguments.get("value")}

    registry = ToolRegistry(
        [
            Tool(make_tool("echo"), handler),
            Tool(make_tool("admin", required_permissions=frozenset({"admin.use"})), echo_handler),
        ]
    )
    provider = MockProvider([response(tool_calls=[tool_call(value="x")]), response("done")])
    executor = RegistryToolExecutor(registry)
    runner = ExecutionRunner(config, provider, executor)

    result = asyncio.run(runner.run())

    assert result.status.value == "completed"
    assert config.granted_permissions == frozenset()
    assert all(
        "admin" not in [spec.name for spec in request.tools] for request in provider.requests
    )


def test_tool_failure_is_observed_and_execution_continues() -> None:
    def handler(arguments: dict[str, Any]) -> ToolResult:
        raise ToolExecutionError("Rejected", code="tool.rejected", retryable=False)

    spec = make_tool()
    sink = InMemoryEventSink()
    provider = MockProvider([response(tool_calls=[tool_call(value="x")]), response("handled")])
    executor = RegistryToolExecutor(ToolRegistry([Tool(spec, handler)]))
    runner = ExecutionRunner(make_config(), provider, executor, sink)

    result = asyncio.run(runner.run())

    assert result.status.value == "completed"
    assert any(event.type == EventType.TOOL_FAILED for event in sink.events)


def test_handler_timeout_is_normalized_and_continues_execution() -> None:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(1)
        return arguments

    spec = make_tool()
    spec.timeout_seconds = 0.01
    sink = InMemoryEventSink()
    provider = MockProvider([response(tool_calls=[tool_call(value="x")]), response("handled")])
    executor = RegistryToolExecutor(ToolRegistry([Tool(spec, handler)]))
    runner = ExecutionRunner(make_config(), provider, executor, sink)

    result = asyncio.run(runner.run())

    assert result.status.value == "completed"
    failed = [event for event in sink.events if event.type == EventType.TOOL_FAILED]
    assert failed[0].payload["error"]["code"] == "tool.timeout"


def test_config_validation_rejects_invalid_permission_names() -> None:
    with pytest.raises(ValueError, match="permission"):
        make_config(granted_permissions=frozenset({"Admin.Use"}))


def test_config_defaults_to_no_permissions() -> None:
    config = make_config()

    assert config.granted_permissions == frozenset()
    assert config.model.provider == "mock"
