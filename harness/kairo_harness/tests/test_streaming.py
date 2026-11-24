import asyncio
from collections import deque
from collections.abc import Sequence

import pytest
from kairo_harness.contracts import EventEnvelope
from kairo_harness.domain import (
    FinishReason,
    ModelRequest,
    ModelStreamChunk,
    ToolCallDelta,
    ToolCallRequest,
    ToolResult,
    Usage,
    aggregate_stream_chunks,
)
from kairo_harness.errors import ProviderError
from kairo_harness.events import EventType, InMemoryEventSink
from kairo_harness.execution import ExecutionRunner
from kairo_harness.providers.mock import MockProvider
from kairo_harness.state import ExecutionStatus, TerminalReason
from support import ScriptedToolExecutor, make_config, make_tool, response


def chunk(
    content: str = "",
    tool_calls: Sequence[ToolCallDelta | ToolCallRequest] = (),
    *,
    usage: Usage | None = None,
    done: bool = False,
    finish_reason: FinishReason | None = None,
) -> ModelStreamChunk:
    return ModelStreamChunk(
        content_delta=content,
        tool_calls=list(tool_calls),
        usage=usage or Usage(),
        done=done,
        finish_reason=finish_reason,
    )


class ChunkProvider(MockProvider):
    def __init__(
        self,
        responses: Sequence[object] = (),
        chunks: Sequence[Sequence[ModelStreamChunk]] = (),
    ) -> None:
        super().__init__(responses)
        self._chunks: deque[Sequence[ModelStreamChunk]] = deque(chunks)
        self.stream_calls = 0
        self.closed = False

    async def stream(self, request: ModelRequest):
        self.requests.append(request.model_copy(deep=True))
        self.stream_calls += 1
        if not self._chunks:
            raise ProviderError("No streamed chunks queued", code="mock.no_queued_stream")
        try:
            for item in self._chunks.popleft():
                yield item
        finally:
            self.closed = True


class SlowStreamProvider(MockProvider):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False
        self.started = asyncio.Event()

    def stream(self, request: ModelRequest):
        self.requests.append(request.model_copy(deep=True))

        async def chunks():
            try:
                self.started.set()
                yield chunk("waiting")
                await asyncio.sleep(10)
            finally:
                self.closed = True

        return chunks()


class FailingStreamEventSink(InMemoryEventSink):
    async def emit(self, event: EventEnvelope) -> None:
        if event.type == EventType.MODEL_STREAM_CHUNK:
            raise RuntimeError("sink unavailable")
        await super().emit(event)


def test_streaming_is_opt_in_and_non_streaming_events_are_unchanged() -> None:
    config = make_config()
    provider = ChunkProvider(
        responses=[response("done")],
        chunks=[[chunk("done", done=True, finish_reason=FinishReason.STOP)]],
    )
    sink = InMemoryEventSink()
    runner = ExecutionRunner(config, provider, ScriptedToolExecutor(), sink)

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.COMPLETED
    assert result.output == "done"
    assert provider.stream_calls == 0
    assert all(event.type != EventType.MODEL_STREAM_CHUNK for event in sink.events)


def test_streamed_response_is_aggregated_without_exposing_content() -> None:
    config = make_config(stream_responses=True)
    provider = ChunkProvider(
        chunks=[
            [
                chunk(
                    "SUPER",
                    usage=Usage(input_tokens=3, output_tokens=1, total_tokens=4),
                ),
                chunk(
                    "SECRET",
                    usage=Usage(input_tokens=0, output_tokens=4, total_tokens=4),
                    done=True,
                    finish_reason=FinishReason.STOP,
                ),
            ]
        ]
    )
    sink = InMemoryEventSink()
    runner = ExecutionRunner(config, provider, ScriptedToolExecutor(), sink)

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.COMPLETED
    assert result.output == "SUPERSECRET"
    assert result.state.usage.total_tokens == 8
    stream_events = [event for event in sink.events if event.type == EventType.MODEL_STREAM_CHUNK]
    assert len(stream_events) == 2
    assert "SUPERSECRET" not in str(stream_events)
    assert set(stream_events[0].payload) == {
        "requestId",
        "executionId",
        "iteration",
        "sequence",
        "contentDeltaLength",
        "toolCallDeltaCount",
        "done",
        "finishReason",
        "usageReported",
    }
    responded = [event for event in sink.events if event.type == EventType.MODEL_RESPONDED][0]
    assert responded.payload["streamed"] is True
    assert responded.payload["chunkCount"] == 2
    assert responded.payload["finishReason"] == "stop"


def test_streamed_tool_call_fragments_use_the_normal_tool_pipeline() -> None:
    tool = make_tool()
    executor = ScriptedToolExecutor(
        [ToolResult(tool_call_id="call-1", status="ok", output={"echo": "hidden-argument-value"})]
    )
    config = make_config(stream_responses=True, tools=[tool])
    provider = ChunkProvider(
        chunks=[
            [
                chunk(
                    tool_calls=[
                        ToolCallDelta(
                            index=0,
                            id="call-1",
                            name="ech",
                            arguments_delta='{"value":',
                        )
                    ]
                ),
                chunk(
                    tool_calls=[
                        ToolCallDelta(index=0, name="o", arguments_delta='"hidden-argument-')
                    ]
                ),
                chunk(
                    tool_calls=[ToolCallDelta(index=0, arguments_delta='value"}')],
                    done=True,
                    finish_reason=FinishReason.TOOL_CALL,
                ),
            ],
            [chunk("done", done=True, finish_reason=FinishReason.STOP)],
        ]
    )
    sink = InMemoryEventSink()
    runner = ExecutionRunner(config, provider, executor, sink)

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.COMPLETED
    assert result.output == "done"
    assert [call.id for call in executor.calls] == ["call-1"]
    assert executor.calls[0].name == "echo"
    assert executor.calls[0].arguments == {"value": "hidden-argument-value"}
    stream_events = [event for event in sink.events if event.type == EventType.MODEL_STREAM_CHUNK]
    assert "hidden-argument-value" not in str(stream_events)
    assert all("echo" not in str(event.payload) for event in stream_events)


def test_streamed_tool_call_permissions_are_enforced_before_execution() -> None:
    executor = ScriptedToolExecutor()
    config = make_config(stream_responses=True, tools=[make_tool(allowed=False)])
    provider = ChunkProvider(
        chunks=[
            [
                chunk(
                    tool_calls=[
                        ToolCallDelta(
                            index=0,
                            id="call-1",
                            name="echo",
                            arguments_delta='{"value":"x"}',
                        )
                    ],
                    done=True,
                    finish_reason=FinishReason.TOOL_CALL,
                )
            ]
        ]
    )
    runner = ExecutionRunner(config, provider, executor, InMemoryEventSink())

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.code == "tool.forbidden"
    assert executor.calls == []


def test_aggregate_stream_usage_sums_per_chunk_deltas() -> None:
    response = aggregate_stream_chunks(
        [
            chunk(usage=Usage(input_tokens=3, output_tokens=1, total_tokens=4)),
            chunk(usage=Usage(input_tokens=0, output_tokens=0, total_tokens=0)),
            chunk(
                usage=Usage(input_tokens=0, output_tokens=4, total_tokens=4),
                done=True,
                finish_reason=FinishReason.STOP,
            ),
        ]
    )

    assert response.usage.input_tokens == 3
    assert response.usage.output_tokens == 5
    assert response.usage.total_tokens == 8


def test_aggregate_stream_usage_derives_missing_total_from_deltas() -> None:
    response = aggregate_stream_chunks(
        [
            chunk(usage=Usage(input_tokens=3, output_tokens=1)),
            chunk(
                usage=Usage(input_tokens=0, output_tokens=4),
                done=True,
                finish_reason=FinishReason.STOP,
            ),
        ]
    )

    assert response.usage.input_tokens == 3
    assert response.usage.output_tokens == 5
    assert response.usage.total_tokens == 8


def test_aggregate_stream_usage_derives_total_from_sparse_deltas() -> None:
    response = aggregate_stream_chunks(
        [
            chunk(usage=Usage(input_tokens=5)),
            chunk(usage=Usage(output_tokens=6), done=True, finish_reason=FinishReason.STOP),
        ]
    )

    assert response.usage.input_tokens == 5
    assert response.usage.output_tokens == 6
    assert response.usage.total_tokens == 11


def test_tool_call_stream_without_done_is_incomplete() -> None:
    executor = ScriptedToolExecutor()
    config = make_config(stream_responses=True, tools=[make_tool()])
    provider = ChunkProvider(
        chunks=[
            [
                chunk(
                    tool_calls=[
                        ToolCallDelta(
                            index=0,
                            id="call-1",
                            name="echo",
                            arguments={"value": "x"},
                        )
                    ],
                    done=False,
                )
            ]
        ]
    )
    runner = ExecutionRunner(config, provider, executor, InMemoryEventSink())

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.code == "model.incomplete_stream"
    assert executor.calls == []


def test_incomplete_stream_is_reported_and_does_not_execute_tools() -> None:
    executor = ScriptedToolExecutor()
    config = make_config(stream_responses=True)
    provider = ChunkProvider(chunks=[[chunk("partial", done=False)]])
    sink = InMemoryEventSink()
    runner = ExecutionRunner(config, provider, executor, sink)

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.code == "model.incomplete_stream"
    assert executor.calls == []
    stream_events = [event for event in sink.events if event.type == EventType.MODEL_STREAM_CHUNK]
    assert "partial" not in str(stream_events)


def test_stream_timeout_closes_the_async_stream() -> None:
    provider = SlowStreamProvider()
    config = make_config(stream_responses=True)
    config.model.timeout_seconds = 0.01
    runner = ExecutionRunner(config, provider, ScriptedToolExecutor(), InMemoryEventSink())

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.code == "model.timeout"
    assert provider.closed is True


def test_stream_cancellation_closes_the_async_stream() -> None:
    provider = SlowStreamProvider()
    config = make_config(stream_responses=True)
    runner = ExecutionRunner(config, provider, ScriptedToolExecutor(), InMemoryEventSink())

    async def scenario() -> None:
        task = asyncio.create_task(runner.run())
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert provider.closed is True
    assert runner.state.status == ExecutionStatus.CANCELLED


def test_event_sink_failure_is_not_reported_as_provider_failure() -> None:
    provider = ChunkProvider(chunks=[[chunk("done", done=True, finish_reason=FinishReason.STOP)]])
    runner = ExecutionRunner(
        make_config(stream_responses=True),
        provider,
        ScriptedToolExecutor(),
        FailingStreamEventSink(),
    )

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.code == "event.emit_failed"
    assert result.error.code != "provider.unexpected"
    assert result.state.terminal_reason == TerminalReason.INTERNAL_ERROR
    assert provider.closed is True
