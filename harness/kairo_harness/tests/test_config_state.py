from uuid import uuid4

from kairo_harness.config import ExecutionConfig
from kairo_harness.state import ExecutionState, ExecutionStatus
from support import make_config


def test_config_defaults_correlation_id_to_execution_id() -> None:
    config = make_config()
    assert config.correlation_id == config.execution_id


def test_config_preserves_explicit_correlation_id() -> None:
    correlation_id = uuid4()
    config = make_config()
    config.correlation_id = correlation_id
    assert ExecutionConfig.model_validate(config.model_dump()).correlation_id == correlation_id


def test_execution_status_covers_platform_lifecycle() -> None:
    assert {status.value for status in ExecutionStatus} == {
        "queued",
        "starting",
        "running",
        "completed",
        "failed",
        "cancelled",
        "recovery",
    }


def test_execution_state_starts_queued_with_zero_counters() -> None:
    execution_id = uuid4()
    state = ExecutionState(execution_id=execution_id)
    assert state.status == ExecutionStatus.QUEUED
    assert state.iteration == 0
    assert state.model_requests == 0
    assert state.tool_calls == 0
