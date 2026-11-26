import asyncio
import json
from collections.abc import Sequence
from uuid import uuid4

import pytest
from kairo_harness.config import ExecutionConfig
from kairo_harness.domain import ModelRequest, ModelResponse, ToolResult, ToolSpec
from kairo_harness.errors import ProviderError
from kairo_harness.events import EventType, InMemoryEventSink
from kairo_harness.execution import ExecutionRunner
from kairo_harness.providers.mock import MockProvider
from kairo_harness.state import ExecutionStatus, TerminalReason
from support import (
    ScriptedToolExecutor,
    make_config,
    make_tool,
    response,
    tool_call,
)


def setup(
    responses: list[object],
    *,
    config: ExecutionConfig | None = None,
    executor: ScriptedToolExecutor | None = None,
    tools: Sequence[ToolSpec] = (),
) -> tuple[ExecutionRunner, InMemoryEventSink, MockProvider, ScriptedToolExecutor]:
    runner_config = config or make_config(tools=tools)
    provider = MockProvider(responses)
    tool_executor = executor or ScriptedToolExecutor()
    sink = InMemoryEventSink()
    runner = ExecutionRunner(runner_config, provider, tool_executor, sink)
    return runner, sink, provider, tool_executor


def event_types(sink: InMemoryEventSink) -> list[str]:
    return [event.type for event in sink.events]


def test_final_response_completes_without_tool_execution() -> None:
    runner, sink, provider, executor = setup([response("Task complete")])

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.COMPLETED
    assert result.output == "Task complete"
    assert result.state.usage.total_tokens == 5
    assert executor.calls == []
    assert event_types(sink) == [
        EventType.EXECUTION_STARTED,
        EventType.EXECUTION_CHECKPOINTED,
        EventType.EXECUTION_CHECKPOINTED,
        EventType.MODEL_REQUESTED,
        EventType.MODEL_RESPONDED,
        EventType.EXECUTION_CHECKPOINTED,
        EventType.EXECUTION_COMPLETED,
    ]
    assert provider.requests[0].tools == []


def test_tool_call_is_observed_then_execution_continues() -> None:
    tool = make_tool()
    executor = ScriptedToolExecutor(
        [
            ToolResult(
                tool_call_id="call-1",
                status="ok",
                output={"value": "hello", "password": "s3cr3t"},
            )
        ]
    )
    runner, sink, provider, tool_executor = setup(
        [response(tool_calls=[tool_call(value="hello")]), response("done")],
        executor=executor,
        tools=[tool],
    )

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.COMPLETED
    assert result.output == "done"
    assert len(tool_executor.calls) == 1
    assert result.state.tool_calls == 1
    assert provider.requests[0].tools == [tool]
    assert EventType.TOOL_STARTED in event_types(sink)
    assert EventType.TOOL_COMPLETED in event_types(sink)
    assert "s3cr3t" not in str(sink.events)
    assert any(message.tool_call_id == "call-1" for message in runner.context.messages)


def test_multiple_tool_calls_in_one_decision_are_processed() -> None:
    tool = make_tool()
    responses = [
        response(
            tool_calls=[
                tool_call("call-1", value="one"),
                tool_call("call-2", value="two"),
            ]
        ),
        response("done"),
    ]
    runner, _, _, executor = setup(responses, tools=[tool])

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.COMPLETED
    assert [call.id for call in executor.calls] == ["call-1", "call-2"]
    assert result.state.tool_calls == 2


def test_strict_json_action_format_drives_a_tool_call() -> None:
    action = {
        "type": "tool_call",
        "tool_calls": [
            {"id": "json-call", "name": "echo", "arguments": {"value": "hello"}},
        ],
    }
    runner, _, _, executor = setup(
        [response(content=json.dumps(action)), response("done")],
        tools=[make_tool()],
    )

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.COMPLETED
    assert [call.id for call in executor.calls] == ["json-call"]


def test_unknown_tool_fails_closed_before_execution() -> None:
    runner, sink, _, executor = setup([response(tool_calls=[tool_call(name="missing", value="x")])])

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.code == "tool.unknown"
    assert executor.calls == []
    assert EventType.TOOL_STARTED not in event_types(sink)
    assert EventType.EXECUTION_FAILED in event_types(sink)


def test_invalid_tool_arguments_fail_closed() -> None:
    runner, _, _, executor = setup(
        [response(tool_calls=[tool_call(value=123)])],
        tools=[make_tool()],
    )

    result = asyncio.run(runner.run())

    assert result.state.terminal_reason == TerminalReason.TOOL_ERROR
    assert result.error is not None
    assert result.error.code == "tool.invalid_arguments"
    assert executor.calls == []


def test_iteration_limit_is_reported() -> None:
    config = make_config(tools=[make_tool()], max_iterations=1, max_model_requests=4)
    runner, _, _, _ = setup([response(tool_calls=[tool_call(value="x")])], config=config)

    result = asyncio.run(runner.run())

    assert result.state.terminal_reason == TerminalReason.LIMIT_EXCEEDED
    assert result.error is not None
    assert result.error.code == "execution.limit_exceeded"


def test_tool_call_limit_is_reported_before_execution() -> None:
    config = make_config(tools=[make_tool()], max_tool_calls=0)
    runner, _, _, executor = setup(
        [response(tool_calls=[tool_call(value="x")])],
        config=config,
    )

    result = asyncio.run(runner.run())

    assert result.state.terminal_reason == TerminalReason.LIMIT_EXCEEDED
    assert executor.calls == []


def test_malformed_model_response_is_an_expected_failure() -> None:
    malformed = json.dumps({"type": "tool_call", "tool_calls": [{"name": "echo"}]})
    runner, sink, _, executor = setup([response(content=malformed)])

    result = asyncio.run(runner.run())

    assert result.state.terminal_reason == TerminalReason.INVALID_MODEL_RESPONSE
    assert result.error is not None
    assert result.error.code == "model.invalid_response"
    assert executor.calls == []
    responded = [event for event in sink.events if event.type == EventType.MODEL_RESPONDED]
    assert responded[0].payload["decisionType"] == "invalid"


def test_provider_error_is_reported_without_raw_details() -> None:
    runner, _, _, _ = setup([ProviderError("provider secret", code="provider.http_500")])

    result = asyncio.run(runner.run())

    assert result.state.terminal_reason == TerminalReason.MODEL_ERROR
    assert result.error is not None
    assert result.error.code == "provider.http_500"
    assert "provider secret" not in str(result)


def test_tool_error_is_observed_and_can_be_followed_by_completion() -> None:
    executor = ScriptedToolExecutor(
        [
            ToolResult(
                tool_call_id="call-1",
                status="error",
                error={"code": "tool.rejected", "message": "Rejected", "retryable": False},
            )
        ]
    )
    runner, sink, _, _ = setup(
        [response(tool_calls=[tool_call(value="x")]), response("handled")],
        executor=executor,
        tools=[make_tool()],
    )

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.COMPLETED
    assert EventType.TOOL_FAILED in event_types(sink)


def test_cancellation_updates_state_and_emits_event() -> None:
    class SlowProvider(MockProvider):
        async def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            await asyncio.sleep(10)
            return response("never")

    config = make_config()
    sink = InMemoryEventSink()
    runner = ExecutionRunner(config, SlowProvider(), ScriptedToolExecutor(), sink)

    async def scenario() -> None:
        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert runner.state.status == ExecutionStatus.CANCELLED
    assert EventType.EXECUTION_CANCELLED in event_types(sink)


def test_model_timeout_is_reported() -> None:
    class SlowProvider(MockProvider):
        async def complete(self, request: ModelRequest) -> ModelResponse:
            await asyncio.sleep(10)
            return response("never")

    config = make_config()
    config.model.timeout_seconds = 0.01
    config.execution_id = uuid4()
    runner = ExecutionRunner(config, SlowProvider(), ScriptedToolExecutor(), InMemoryEventSink())

    result = asyncio.run(runner.run())

    assert result.state.terminal_reason == TerminalReason.TIMEOUT
    assert result.error is not None
    assert result.error.code == "model.timeout"


def test_events_do_not_expose_task_or_system_prompt() -> None:
    runner, sink, _, _ = setup([response("done")], config=make_config(task="secret task"))

    asyncio.run(runner.run())

    emitted = str(sink.events)
    assert "secret task" not in emitted
    assert "You are a Kairo agent" not in emitted


def test_unexpected_harness_error_returns_structured_failure() -> None:
    class BrokenRunner(ExecutionRunner):
        async def _react(self) -> str:
            raise RuntimeError("boom")

    runner = BrokenRunner(
        make_config(),
        MockProvider([]),
        ScriptedToolExecutor(),
        InMemoryEventSink(),
    )

    result = asyncio.run(runner.run())

    assert result.state.terminal_reason == TerminalReason.INTERNAL_ERROR
    assert result.error is not None
    assert result.error.code == "execution.unexpected"
    assert "boom" not in str(result)
