import asyncio

import pytest
from kairo_harness.domain import ModelRequest, ModelResponse, ToolCallRequest, ToolResult, ToolSpec
from kairo_harness.events import EventType, InMemoryEventSink
from kairo_harness.execution import ExecutionRunner
from kairo_harness.providers.mock import MockProvider
from kairo_harness.state import ExecutionStatus, TerminalReason
from kairo_harness.tools import ToolExecutor
from support import ScriptedToolExecutor, make_config, make_tool, response, tool_call


class SlowProvider(MockProvider):
    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        await asyncio.sleep(10)
        return response("never")


class SecondRequestBlocksProvider(MockProvider):
    async def complete(self, request: ModelRequest) -> ModelResponse:
        if self.requests:
            await asyncio.Event().wait()
        return await super().complete(request)


class SlowToolExecutor(ToolExecutor):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled: list[str] = []
        self.closed = False

    async def execute(self, call: ToolCallRequest, spec: ToolSpec) -> ToolResult:
        self.started.set()
        await asyncio.sleep(10)
        return ToolResult(tool_call_id=call.id, status="ok", output="never")

    async def cancel(self, call: ToolCallRequest) -> None:
        self.cancelled.append(call.id)

    async def aclose(self) -> None:
        self.closed = True


def event_types(sink: InMemoryEventSink) -> list[str]:
    return [event.type for event in sink.events]


def test_shutdown_during_tool_call_stops_new_work_and_cleans_resources() -> None:
    config = make_config(tools=[make_tool()])
    provider = MockProvider([response(tool_calls=[tool_call(value="hello")]), response("never")])
    executor = SlowToolExecutor()
    sink = InMemoryEventSink()
    runner = ExecutionRunner(config, provider, executor, sink)

    async def scenario() -> None:
        task = asyncio.create_task(runner.run())
        await asyncio.wait_for(executor.started.wait(), timeout=1)
        await runner.shutdown()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert runner.state.status == ExecutionStatus.CANCELLED
    assert runner.state.terminal_reason == TerminalReason.CANCELLED
    assert len(provider.requests) == 1
    assert "call-1" in executor.cancelled
    assert executor.closed is True
    types = event_types(sink)
    assert types.index(EventType.EXECUTION_SHUTDOWN) < types.index(EventType.EXECUTION_CANCELLED)
    cancelled = next(event for event in sink.events if event.type == EventType.EXECUTION_CANCELLED)
    assert cancelled.payload["reason"] == "shutdown"
    assert cancelled.payload["safeToResume"] is False
    assert cancelled.payload["interruptedOperation"] == "tool:call-1"


def test_shutdown_before_run_prevents_new_work() -> None:
    provider = MockProvider([response("done")])
    sink = InMemoryEventSink()
    runner = ExecutionRunner(make_config(), provider, ScriptedToolExecutor(), sink)

    async def scenario() -> None:
        await runner.shutdown()
        with pytest.raises(asyncio.CancelledError):
            await runner.run()

    asyncio.run(scenario())

    assert provider.requests == []
    assert runner.state.status == ExecutionStatus.CANCELLED
    assert EventType.EXECUTION_CHECKPOINTED not in event_types(sink)
    assert EventType.EXECUTION_CANCELLED in event_types(sink)


def test_cancellation_during_model_request_reports_interrupted_operation() -> None:
    sink = InMemoryEventSink()
    runner = ExecutionRunner(make_config(), SlowProvider(), ScriptedToolExecutor(), sink)

    async def scenario() -> None:
        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    cancelled = next(event for event in sink.events if event.type == EventType.EXECUTION_CANCELLED)
    assert cancelled.payload["reason"] == "cancelled"
    assert cancelled.payload["safeToResume"] is False
    assert str(cancelled.payload["interruptedOperation"]).startswith("model:")


def test_timeout_is_distinct_from_cancellation_and_expected_failure() -> None:
    config = make_config()
    config.model.timeout_seconds = 0.01
    sink = InMemoryEventSink()
    runner = ExecutionRunner(config, SlowProvider(), ScriptedToolExecutor(), sink)

    result = asyncio.run(runner.run())

    assert result.state.terminal_reason == TerminalReason.TIMEOUT
    assert EventType.EXECUTION_TIMED_OUT in event_types(sink)
    assert EventType.EXECUTION_CANCELLED not in event_types(sink)
    failed = next(event for event in sink.events if event.type == EventType.EXECUTION_FAILED)
    assert failed.payload["reason"] == "timeout"
    assert failed.payload["errorKind"] == "timeout"


def test_unexpected_failure_is_distinct_from_expected_failure() -> None:
    class BrokenRunner(ExecutionRunner):
        async def _react(self) -> str:
            raise RuntimeError("boom")

    sink = InMemoryEventSink()
    runner = BrokenRunner(
        make_config(),
        MockProvider([]),
        ScriptedToolExecutor(),
        sink,
    )

    result = asyncio.run(runner.run())

    assert result.state.terminal_reason == TerminalReason.INTERNAL_ERROR
    assert EventType.EXECUTION_TIMED_OUT not in event_types(sink)
    failed = next(event for event in sink.events if event.type == EventType.EXECUTION_FAILED)
    assert failed.payload["reason"] == "internal_error"
    assert failed.payload["errorKind"] == "unexpected"


def test_completed_tool_checkpoint_is_preserved_when_shutdown_follows() -> None:
    config = make_config(tools=[make_tool()])
    provider = SecondRequestBlocksProvider(
        [response(tool_calls=[tool_call(value="hello")]), response("never")]
    )
    executor = ScriptedToolExecutor()
    runner = ExecutionRunner(config, provider, executor, InMemoryEventSink())

    async def scenario() -> None:
        task = asyncio.create_task(runner.run())
        for _ in range(100):
            if any(
                item.metadata.boundary.value == "after_tool_result"
                for item in runner.checkpoints.checkpoints
            ):
                break
            await asyncio.sleep(0)
        else:
            raise AssertionError("tool checkpoint was not recorded")
        await runner.shutdown()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    completed = [
        item
        for item in runner.checkpoints.checkpoints
        if item.metadata.boundary.value == "after_tool_result"
    ]
    assert len(completed) == 1
    assert [call.tool_call_id for call in completed[0].state.completed_tool_calls] == ["call-1"]
    assert runner.checkpoints.latest is not None
    assert runner.checkpoints.latest.metadata.boundary.value == "before_model_request"
