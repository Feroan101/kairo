from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from kairo_harness.config import ExecutionConfig
from kairo_harness.context import ExecutionContext
from kairo_harness.domain import ModelMessage
from kairo_harness.events import EventEmitter, EventType
from kairo_harness.state import ExecutionState

CHECKPOINT_SCHEMA_VERSION = 1


class CheckpointBoundary(StrEnum):
    EXECUTION_STARTED = "execution.started"
    BEFORE_MODEL_REQUEST = "before_model_request"
    AFTER_MODEL_RESPONSE = "after_model_response"
    AFTER_TOOL_RESULT = "after_tool_result"
    BEFORE_COMPLETION = "before_completion"


SAFE_CHECKPOINT_BOUNDARIES = frozenset(CheckpointBoundary)


class RecoveryAction(StrEnum):
    RESUME = "resume"
    RECONCILE = "reconcile"
    MANUAL_INTERVENTION = "manual_intervention"


class RecoveryInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    safe_to_resume: bool
    action: RecoveryAction
    reason: str = Field(min_length=1, max_length=200)


class CompletedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str = Field(min_length=1, max_length=200)
    tool_name: str = Field(min_length=1, max_length=64)
    completion_event_id: str | None = None
    status: Literal["ok", "error"]
    retryable: bool = False


class PendingOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=1, max_length=200)
    kind: Literal["model_request", "tool_call"]
    reference_id: str = Field(min_length=1, max_length=200)
    status: Literal["planned", "in_flight", "uncertain"]
    replay_safe: bool
    reason: str = Field(min_length=1, max_length=200)


class CheckpointMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: UUID
    schema_version: int = Field(default=CHECKPOINT_SCHEMA_VERSION, ge=1)
    boundary: CheckpointBoundary
    sequence: int = Field(ge=1)
    created_at: str
    correlation_id: UUID
    recovery: RecoveryInfo
    event_id: str | None = None


class CheckpointState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: UUID
    agent_id: str = Field(min_length=1, max_length=200)
    state: ExecutionState
    conversation: list[ModelMessage] = Field(default_factory=list)
    completed_tool_calls: list[CompletedToolCall] = Field(default_factory=list)
    pending_operations: list[PendingOperation] = Field(default_factory=list)


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: CheckpointMetadata
    state: CheckpointState


def pending_tool_operation(call_id: str) -> PendingOperation:
    return PendingOperation(
        operation_id=f"tool:{call_id}",
        kind="tool_call",
        reference_id=call_id,
        status="planned",
        replay_safe=True,
        reason="not_started",
    )


def pending_model_operation(request_id: str) -> PendingOperation:
    return PendingOperation(
        operation_id=f"model:{request_id}",
        kind="model_request",
        reference_id=request_id,
        status="planned",
        replay_safe=True,
        reason="not_started",
    )


def _recovery_info(operations: Sequence[PendingOperation]) -> RecoveryInfo:
    if any(
        operation.status in {"in_flight", "uncertain"} and not operation.replay_safe
        for operation in operations
    ):
        return RecoveryInfo(
            safe_to_resume=False,
            action=RecoveryAction.RECONCILE,
            reason="uncertain_pending_operation",
        )
    return RecoveryInfo(
        safe_to_resume=True,
        action=RecoveryAction.RESUME,
        reason="safe_execution_boundary",
    )


class CheckpointRecorder:
    def __init__(
        self,
        *,
        config: ExecutionConfig,
        state: ExecutionState,
        context: ExecutionContext,
        emitter: EventEmitter,
    ) -> None:
        self.config = config
        self.state = state
        self.context = context
        self.emitter = emitter
        self.checkpoints: list[Checkpoint] = []

    async def record(
        self,
        boundary: CheckpointBoundary,
        *,
        completed_tool_calls: Sequence[CompletedToolCall] = (),
        pending_operations: Sequence[PendingOperation] = (),
        causation_id: str | None = None,
    ) -> Checkpoint:
        pending = [operation.model_copy(deep=True) for operation in pending_operations]
        checkpoint = Checkpoint(
            metadata=CheckpointMetadata(
                checkpoint_id=uuid4(),
                boundary=boundary,
                sequence=len(self.checkpoints) + 1,
                created_at=datetime.now(UTC)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z"),
                correlation_id=self.config.correlation_id or self.config.execution_id,
                recovery=_recovery_info(pending),
            ),
            state=CheckpointState(
                execution_id=self.config.execution_id,
                agent_id=self.config.agent_id,
                state=self.state.model_copy(deep=True),
                conversation=self.context.snapshot(),
                completed_tool_calls=[call.model_copy(deep=True) for call in completed_tool_calls],
                pending_operations=pending,
            ),
        )
        checkpoint.metadata.event_id = await self.emitter.emit(
            EventType.EXECUTION_CHECKPOINTED,
            {
                "executionId": str(checkpoint.state.execution_id),
                "agentId": checkpoint.state.agent_id,
                "checkpointId": str(checkpoint.metadata.checkpoint_id),
                "schemaVersion": checkpoint.metadata.schema_version,
                "boundary": checkpoint.metadata.boundary.value,
                "sequence": checkpoint.metadata.sequence,
                "iteration": checkpoint.state.state.iteration,
                "modelRequests": checkpoint.state.state.model_requests,
                "toolCalls": checkpoint.state.state.tool_calls,
                "completedToolCallIds": [
                    call.tool_call_id for call in checkpoint.state.completed_tool_calls
                ],
                "pendingOperationIds": [
                    operation.operation_id for operation in checkpoint.state.pending_operations
                ],
                "safeToResume": checkpoint.metadata.recovery.safe_to_resume,
                "recoveryAction": checkpoint.metadata.recovery.action.value,
            },
            causation_id=causation_id,
        )
        self.checkpoints.append(checkpoint)
        return checkpoint

    @property
    def latest(self) -> Checkpoint | None:
        return self.checkpoints[-1] if self.checkpoints else None
