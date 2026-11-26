import asyncio
import json
from pathlib import Path

import pytest
from kairo_harness.cli import main as cli_main
from kairo_harness.config import ExecutionConfig
from kairo_harness.errors import ProviderError
from kairo_harness.events import EventSink, EventType
from kairo_harness.providers.mock import MockProvider
from kairo_harness.providers.registry import ProviderRegistry
from kairo_harness.standalone import StandaloneHarness, StandaloneRunResult
from kairo_harness.state import ExecutionStatus, TerminalReason
from support import make_config, response


class RecordingSink(EventSink):
    def __init__(self) -> None:
        self.events: list[object] = []

    async def emit(self, event: object) -> None:
        self.events.append(event)


class FailingSink(EventSink):
    async def emit(self, event: object) -> None:
        if getattr(event, "type", None) == EventType.EXECUTION_STARTED:
            raise RuntimeError("sink unavailable")


class SlowProvider(MockProvider):
    async def complete(self, request: object) -> object:
        await asyncio.sleep(10)
        return response("never")


class ClosableProvider(MockProvider):
    def __init__(self) -> None:
        super().__init__([response("done")])
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def event_types(run: StandaloneRunResult) -> list[str]:
    return [event.type for event in run.events]


def test_standalone_invocation_returns_result_and_events() -> None:
    provider = MockProvider([response("done")])
    harness = StandaloneHarness(provider=provider)

    run = asyncio.run(harness.run(make_config()))

    assert isinstance(run, StandaloneRunResult)
    assert run.status == ExecutionStatus.COMPLETED
    assert run.output == "done"
    assert run.usage.total_tokens == 5
    assert EventType.EXECUTION_STARTED in event_types(run)
    assert EventType.MODEL_RESPONDED in event_types(run)
    assert EventType.EXECUTION_COMPLETED in event_types(run)


def test_standalone_failure_preserves_error_and_usage() -> None:
    provider = MockProvider([ProviderError("provider unavailable", code="provider.connection")])
    harness = StandaloneHarness(provider=provider)

    run = asyncio.run(harness.run(make_config()))

    assert run.status == ExecutionStatus.FAILED
    assert run.error is not None
    assert run.error.code == "provider.connection"
    assert run.result.state.terminal_reason == TerminalReason.MODEL_ERROR
    assert EventType.EXECUTION_FAILED in event_types(run)


def test_standalone_timeout_is_a_failed_result() -> None:
    config = make_config()
    config.model.timeout_seconds = 0.01
    harness = StandaloneHarness(provider=SlowProvider())

    run = asyncio.run(harness.run(config))

    assert run.status == ExecutionStatus.FAILED
    assert run.result.state.terminal_reason == TerminalReason.TIMEOUT
    assert run.error is not None
    assert run.error.code == "model.timeout"
    assert EventType.EXECUTION_TIMED_OUT in event_types(run)


def test_standalone_shutdown_returns_cancelled_result() -> None:
    harness = StandaloneHarness(provider=SlowProvider())

    async def scenario() -> StandaloneRunResult:
        task = asyncio.create_task(harness.run(make_config()))
        await asyncio.sleep(0.01)
        await harness.shutdown()
        return await task

    run = asyncio.run(scenario())

    assert run.status == ExecutionStatus.CANCELLED
    assert run.result.state.terminal_reason == TerminalReason.CANCELLED
    assert EventType.EXECUTION_SHUTDOWN in event_types(run)
    assert EventType.EXECUTION_CANCELLED in event_types(run)


def test_standalone_delivers_events_to_caller_sink() -> None:
    sink = RecordingSink()
    harness = StandaloneHarness(provider=MockProvider([response("done")]), event_sink=sink)

    run = asyncio.run(harness.run(make_config()))

    assert [getattr(event, "type", None) for event in sink.events] == event_types(run)


def test_standalone_event_sink_failure_is_not_silently_ignored() -> None:
    harness = StandaloneHarness(provider=MockProvider([response("done")]), event_sink=FailingSink())

    run = asyncio.run(harness.run(make_config()))

    assert run.status == ExecutionStatus.FAILED
    assert run.result.state.terminal_reason == TerminalReason.INTERNAL_ERROR
    assert EventType.EXECUTION_STARTED in event_types(run)
    assert EventType.EXECUTION_FAILED in event_types(run)


def test_standalone_provider_configuration_uses_environment() -> None:
    ollama = StandaloneHarness.from_env({"KAIRO_OLLAMA_BASE_URL": "http://127.0.0.1:11434"})
    empty = StandaloneHarness.from_env({})

    assert ollama.configured_provider_names == ("ollama",)
    assert empty.configured_provider_names == ()
    assert StandaloneHarness(provider=MockProvider()).configured_provider_names == ("mock",)

    asyncio.run(ollama.aclose())


def test_standalone_closes_owned_provider_registry() -> None:
    provider = ClosableProvider()
    registry = ProviderRegistry({"mock": provider})

    async def scenario() -> StandaloneRunResult:
        async with StandaloneHarness.from_registry(registry, close_registry=True) as harness:
            return await harness.run(make_config())

    run = asyncio.run(scenario())

    assert run.status == ExecutionStatus.COMPLETED
    assert provider.closed is True


def test_cli_runs_mock_provider_and_prints_events(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli_main(
        [
            "--provider",
            "mock",
            "--task",
            "Say hello",
            "--mock-response",
            "hello",
            "--events",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "status=completed" in output
    assert "output=hello" in output
    assert (
        json.loads(next(line for line in output.splitlines() if line.startswith("{")))["type"]
        == EventType.EXECUTION_STARTED
    )


def test_container_definition_is_minimal_and_non_root() -> None:
    dockerfile = Path(__file__).resolve().parents[3] / "runtime" / "base" / "Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")

    assert "USER kairo" in content
    assert 'ENTRYPOINT ["python", "-m", "kairo_harness"]' in content
    assert "--no-dev" in content
    assert "packages/contracts/schemas" in content


def test_standalone_config_accepts_explicit_execution_identity() -> None:
    config = make_config()
    assert isinstance(config, ExecutionConfig)
    assert config.correlation_id == config.execution_id
