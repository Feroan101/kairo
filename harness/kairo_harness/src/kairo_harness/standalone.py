from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from kairo_harness.config import ExecutionConfig
from kairo_harness.context import ContextBuilder
from kairo_harness.contracts import EventEnvelope
from kairo_harness.domain import Usage
from kairo_harness.errors import ConfigError, ErrorInfo
from kairo_harness.events import EventSink
from kairo_harness.execution import ExecutionRunner
from kairo_harness.providers.base import ModelProvider
from kairo_harness.providers.registry import ProviderRegistry
from kairo_harness.providers.settings import ProviderSettings
from kairo_harness.state import ExecutionResult, ExecutionStatus, TerminalReason
from kairo_harness.tools import RegistryToolExecutor, Tool, ToolRegistry, ToolRegistrySnapshot

_TERMINAL_STATUSES = frozenset(
    {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}
)


class _CollectingEventSink(EventSink):
    def __init__(self, downstream: EventSink | None) -> None:
        self._downstream = downstream
        self.events: list[EventEnvelope] = []

    async def emit(self, event: EventEnvelope) -> None:
        self.events.append(event)
        if self._downstream is not None:
            await self._downstream.emit(event)


@dataclass(frozen=True)
class StandaloneRunResult:
    result: ExecutionResult
    events: tuple[EventEnvelope, ...]

    @property
    def status(self) -> ExecutionStatus:
        return self.result.status

    @property
    def output(self) -> str | None:
        return self.result.output

    @property
    def error(self) -> ErrorInfo | None:
        return self.result.error

    @property
    def usage(self) -> Usage:
        return self.result.state.usage


class StandaloneHarness:
    def __init__(
        self,
        *,
        provider: ModelProvider | None = None,
        registry: ProviderRegistry | None = None,
        tools: Iterable[Tool] = (),
        event_sink: EventSink | None = None,
        context_builder: ContextBuilder | None = None,
        close_registry: bool = False,
    ) -> None:
        if provider is not None and registry is not None:
            raise ConfigError("Choose a provider or a provider registry, not both")
        if provider is None and registry is None:
            raise ConfigError("A provider or provider registry is required")

        self._provider = provider
        self._registry = registry
        self._tools = tuple(tools)
        self._event_sink = event_sink
        self._context_builder = context_builder
        self._close_registry = close_registry
        self._runner: ExecutionRunner | None = None

    @classmethod
    def from_registry(
        cls,
        registry: ProviderRegistry,
        *,
        tools: Iterable[Tool] = (),
        event_sink: EventSink | None = None,
        context_builder: ContextBuilder | None = None,
        close_registry: bool = False,
    ) -> StandaloneHarness:
        return cls(
            registry=registry,
            tools=tools,
            event_sink=event_sink,
            context_builder=context_builder,
            close_registry=close_registry,
        )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        tools: Iterable[Tool] = (),
        event_sink: EventSink | None = None,
        context_builder: ContextBuilder | None = None,
    ) -> StandaloneHarness:
        settings = ProviderSettings.from_env(environ)
        return cls(
            registry=ProviderRegistry.from_settings(settings),
            tools=tools,
            event_sink=event_sink,
            context_builder=context_builder,
            close_registry=True,
        )

    @property
    def configured_provider_names(self) -> tuple[str, ...]:
        if self._provider is not None:
            return (self._provider.name,)
        if self._registry is not None:
            return self._registry.names
        return ()

    async def run(self, config: ExecutionConfig) -> StandaloneRunResult:
        sink = _CollectingEventSink(self._event_sink)
        tool_registry = ToolRegistry(self._tools)
        snapshot = tool_registry.snapshot()
        provider = self._select_provider(config, snapshot)
        executor = RegistryToolExecutor(snapshot, config.granted_permissions)
        runner = ExecutionRunner(
            config,
            provider,
            executor,
            sink,
            tool_registry=snapshot,
            context_builder=self._context_builder,
        )
        self._runner = runner

        try:
            result = await runner.run()
        except asyncio.CancelledError:
            state = runner.state.model_copy(deep=True)
            state.status = ExecutionStatus.CANCELLED
            if state.terminal_reason is None:
                state.terminal_reason = TerminalReason.CANCELLED
            result = ExecutionResult(
                execution_id=config.execution_id,
                status=ExecutionStatus.CANCELLED,
                state=state,
            )

        return StandaloneRunResult(result=result, events=tuple(sink.events))

    async def shutdown(self) -> None:
        if self._runner is not None and self._runner.state.status not in _TERMINAL_STATUSES:
            await self._runner.shutdown()

    async def aclose(self) -> None:
        await self.shutdown()
        if self._close_registry and self._registry is not None:
            await self._registry.aclose()

    async def __aenter__(self) -> StandaloneHarness:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.aclose()

    def _select_provider(
        self,
        config: ExecutionConfig,
        tool_registry: ToolRegistrySnapshot,
    ) -> ModelProvider:
        if self._provider is not None:
            return self._provider
        if self._registry is None:
            raise ConfigError("No provider registry is configured")
        return self._registry.select(config.model, tools=tool_registry.specs())
