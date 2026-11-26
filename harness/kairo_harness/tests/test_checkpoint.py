import asyncio
import json

from kairo_harness.checkpoint import (
    Checkpoint,
    CheckpointBoundary,
    CheckpointRecorder,
    PendingOperation,
    RecoveryAction,
)
from kairo_harness.context import ExecutionContext
from kairo_harness.domain import ModelRole, ToolResult
from kairo_harness.events import EventEmitter, EventType, InMemoryEventSink
from kairo_harness.execution import ExecutionRunner
from kairo_harness.providers.mock import MockProvider
from kairo_harness.state import ExecutionState, ExecutionStatus
from support import ScriptedToolExecutor, make_config, make_tool, response, tool_call


def test_checkpoint_boundaries_are_explicit() -> None:
    assert set(CheckpointBoundary) == {
        CheckpointBoundary.EXECUTION_STARTED,
        CheckpointBoundary.BEFORE_MODEL_REQUEST,
        CheckpointBoundary.AFTER_MODEL_RESPONSE,
        CheckpointBoundary.AFTER_TOOL_RESULT,
        CheckpointBoundary.BEFORE_COMPLETION,
    }


def test_checkpoint_state_is_serializable_and_preserves_completed_tool_references() -> None:
    config = make_config(task="secret task", tools=[make_tool()])
    executor = ScriptedToolExecutor(
        [
            ToolResult(
                tool_call_id="call-1",
                status="ok",
                output={"note": "private note"},
            )
        ]
    )
    provider = MockProvider([response(tool_calls=[tool_call(value="hello")]), response("done")])
    sink = InMemoryEventSink()
    runner = ExecutionRunner(config, provider, executor, sink)

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.COMPLETED
    boundaries = [item.metadata.boundary for item in runner.checkpoints.checkpoints]
    assert boundaries == [
        CheckpointBoundary.EXECUTION_STARTED,
        CheckpointBoundary.BEFORE_MODEL_REQUEST,
        CheckpointBoundary.AFTER_MODEL_RESPONSE,
        CheckpointBoundary.AFTER_TOOL_RESULT,
        CheckpointBoundary.BEFORE_MODEL_REQUEST,
        CheckpointBoundary.BEFORE_COMPLETION,
    ]

    completed = next(
        item
        for item in runner.checkpoints.checkpoints
        if item.metadata.boundary == CheckpointBoundary.AFTER_TOOL_RESULT
    )
    assert completed.state.execution_id == config.execution_id
    assert completed.state.agent_id == config.agent_id
    assert completed.state.state.tool_calls == 1
    assert [
        (call.tool_call_id, call.tool_name, call.status)
        for call in completed.state.completed_tool_calls
    ] == [("call-1", "echo", "ok")]
    assert completed.state.pending_operations == []
    assert [message.role for message in completed.state.conversation] == [
        ModelRole.USER,
        ModelRole.ASSISTANT,
        ModelRole.TOOL,
    ]
    assert (
        Checkpoint.model_validate_json(json.dumps(completed.model_dump(mode="json"))) == completed
    )

    checkpoint_events = [
        event for event in sink.events if event.type == EventType.EXECUTION_CHECKPOINTED
    ]
    assert checkpoint_events
    assert set(checkpoint_events[0].payload) == {
        "executionId",
        "agentId",
        "checkpointId",
        "schemaVersion",
        "boundary",
        "sequence",
        "iteration",
        "modelRequests",
        "toolCalls",
        "completedToolCallIds",
        "pendingOperationIds",
        "safeToResume",
        "recoveryAction",
    }
    assert "secret task" not in str(checkpoint_events)
    assert "private note" not in str(checkpoint_events)
    assert "You are a Kairo agent" not in str(checkpoint_events)


def test_recovery_actions_are_explicit() -> None:
    assert {action.value for action in RecoveryAction} == {"resume", "reconcile"}


def test_in_flight_replay_safe_operation_allows_resume() -> None:
    config = make_config()
    recorder = CheckpointRecorder(
        config=config,
        state=ExecutionState(execution_id=config.execution_id),
        context=ExecutionContext(),
        emitter=EventEmitter(
            execution_id=config.execution_id,
            correlation_id=config.correlation_id or config.execution_id,
            sink=InMemoryEventSink(),
        ),
    )
    operation = PendingOperation(
        operation_id="model:request-1",
        kind="model_request",
        reference_id="request-1",
        status="in_flight",
        replay_safe=True,
        reason="provider_request",
    )

    checkpoint = asyncio.run(
        recorder.record(CheckpointBoundary.BEFORE_MODEL_REQUEST, pending_operations=[operation])
    )

    assert checkpoint.metadata.recovery.safe_to_resume is True
    assert checkpoint.metadata.recovery.action is RecoveryAction.RESUME


def test_uncertain_pending_operation_blocks_safe_resume() -> None:
    config = make_config()
    sink = InMemoryEventSink()
    recorder = CheckpointRecorder(
        config=config,
        state=ExecutionState(execution_id=config.execution_id),
        context=ExecutionContext(),
        emitter=EventEmitter(
            execution_id=config.execution_id,
            correlation_id=config.correlation_id or config.execution_id,
            sink=sink,
        ),
    )
    uncertain = PendingOperation(
        operation_id="tool:call-1",
        kind="tool_call",
        reference_id="call-1",
        status="uncertain",
        replay_safe=False,
        reason="completion_unknown",
    )

    checkpoint = asyncio.run(
        recorder.record(CheckpointBoundary.BEFORE_MODEL_REQUEST, pending_operations=[uncertain])
    )

    assert checkpoint.metadata.recovery.safe_to_resume is False
    assert checkpoint.metadata.recovery.action is RecoveryAction.RECONCILE
