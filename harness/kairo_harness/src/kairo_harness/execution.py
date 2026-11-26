from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from time import perf_counter
from typing import Any

from kairo_harness.checkpoint import (
    CheckpointBoundary,
    CheckpointRecorder,
    CompletedToolCall,
    pending_model_operation,
    pending_tool_operation,
)
from kairo_harness.config import ExecutionConfig
from kairo_harness.context import ContextBuilder, DefaultContextBuilder, ExecutionContext
from kairo_harness.domain import (
    FinalDecision,
    FinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelStreamChunk,
    ToolCallDecision,
    ToolCallRequest,
    ToolErrorInfo,
    ToolResult,
    Usage,
    aggregate_stream_chunks,
    parse_model_decision,
)
from kairo_harness.errors import (
    ConfigError,
    ExecutionLimitError,
    ExecutionTimeoutError,
    HarnessError,
    InvalidModelResponseError,
    ProviderError,
    ToolExecutionError,
)
from kairo_harness.events import EventEmitter, EventSink, EventType, InMemoryEventSink
from kairo_harness.providers.base import ModelProvider
from kairo_harness.state import ExecutionResult, ExecutionState, ExecutionStatus, TerminalReason
from kairo_harness.tools import (
    RegistryToolExecutor,
    ToolCallValidator,
    ToolExecutor,
    ToolRegistrySnapshot,
)


class ExecutionRunner:
    def __init__(
        self,
        config: ExecutionConfig,
        provider: ModelProvider,
        tool_executor: ToolExecutor,
        event_sink: EventSink | None = None,
        *,
        tool_registry: ToolRegistrySnapshot | None = None,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        if provider.name != config.model.provider:
            raise ConfigError(
                "Provider does not match execution configuration",
                details={"configured": config.model.provider, "provided": provider.name},
            )

        self.config = config
        self.provider = provider
        self.tool_executor = tool_executor
        self.sink = event_sink or InMemoryEventSink()
        self.emitter = EventEmitter(
            execution_id=config.execution_id,
            correlation_id=config.correlation_id or config.execution_id,
            sink=self.sink,
        )
        registry_snapshot = tool_registry or (
            tool_executor.snapshot if isinstance(tool_executor, RegistryToolExecutor) else None
        )
        tool_specs = registry_snapshot.specs() if registry_snapshot else config.tools
        self._granted_permissions = frozenset(config.granted_permissions)
        self.validator = ToolCallValidator(tool_specs, self._granted_permissions)
        if isinstance(self.tool_executor, RegistryToolExecutor):
            self.tool_executor.bind_validator(self.validator)
        self.state = ExecutionState(execution_id=config.execution_id)
        self.context = ExecutionContext()
        self.context_builder = context_builder or DefaultContextBuilder()
        self.checkpoints = CheckpointRecorder(
            config=config,
            state=self.state,
            context=self.context,
            emitter=self.emitter,
        )
        self._last_model_response_event_id: str | None = None
        self._shutdown_requested = False
        self._run_task: asyncio.Task[ExecutionResult] | None = None
        self._active_tool_tasks: dict[str, tuple[ToolCallRequest, asyncio.Task[ToolResult]]] = {}
        self._model_request_in_flight = False
        self._interrupted_operation: str | None = None

    async def run(self) -> ExecutionResult:
        if self.state.status != ExecutionStatus.QUEUED:
            raise ConfigError(
                "Execution has already been started", code="execution.already_started"
            )

        self._run_task = asyncio.current_task()
        try:
            try:
                self._ensure_running()
                self.state.status = ExecutionStatus.RUNNING
                self.context.add(ModelMessage(role=ModelRole.USER, content=self.config.task))
                await self.emitter.emit(
                    EventType.EXECUTION_STARTED,
                    {
                        "executionId": str(self.config.execution_id),
                        "agentId": self.config.agent_id,
                        "provider": self.config.model.provider,
                        "model": self.config.model.model,
                    },
                )
                await self.checkpoints.record(CheckpointBoundary.EXECUTION_STARTED)

                async with asyncio.timeout(self.config.timeout_seconds):
                    output = await self._react()
            except TimeoutError:
                if self._interrupted_operation is None:
                    self._interrupted_operation = "execution"
                failure = ExecutionTimeoutError(
                    "Execution timed out",
                    details={"limitSeconds": self.config.timeout_seconds},
                )
                return await self._fail(failure, TerminalReason.TIMEOUT, "timeout")
            except asyncio.CancelledError:
                self.state.status = ExecutionStatus.CANCELLED
                self.state.terminal_reason = TerminalReason.CANCELLED
                await self.emitter.emit(
                    EventType.EXECUTION_CANCELLED,
                    {
                        "executionId": str(self.config.execution_id),
                        "reason": "shutdown" if self._shutdown_requested else "cancelled",
                        "interruptedOperation": self._interrupted_operation,
                        "safeToResume": self._interrupted_operation is None,
                    },
                )
                raise
            except HarnessError as error:
                return await self._fail(error, self._terminal_reason(error), "expected")
            except Exception as error:
                failure = HarnessError(
                    "Unexpected harness failure",
                    code="execution.unexpected",
                    details={"errorType": type(error).__name__},
                )
                return await self._fail(failure, TerminalReason.INTERNAL_ERROR, "unexpected")

            self.state.status = ExecutionStatus.COMPLETED
            self.state.terminal_reason = TerminalReason.COMPLETED
            latest = self.checkpoints.latest
            await self.emitter.emit(
                EventType.EXECUTION_COMPLETED,
                {
                    "executionId": str(self.config.execution_id),
                    "output": output,
                    "iterations": self.state.iteration,
                    "modelRequests": self.state.model_requests,
                    "toolCalls": self.state.tool_calls,
                    "usage": self.state.usage.model_dump(mode="json", exclude_none=True),
                    "checkpointCount": len(self.checkpoints.checkpoints),
                    "lastCheckpointId": (
                        str(latest.metadata.checkpoint_id) if latest is not None else None
                    ),
                },
            )
            return ExecutionResult(
                execution_id=self.config.execution_id,
                status=ExecutionStatus.COMPLETED,
                output=output,
                state=self.state.model_copy(deep=True),
            )
        finally:
            await self._cleanup_resources()

    async def shutdown(self) -> None:
        if self._run_task is None or self._run_task.done():
            self._shutdown_requested = True
            return
        if not self._shutdown_requested:
            self._shutdown_requested = True
            with suppress(Exception):
                await self.emitter.emit(
                    EventType.EXECUTION_SHUTDOWN,
                    {
                        "executionId": str(self.config.execution_id),
                        "agentId": self.config.agent_id,
                    },
                )
        await self._cancel_active_tools()
        self._run_task.cancel()

    async def _react(self) -> str:
        while True:
            self._ensure_running()
            if self.state.iteration >= self.config.max_iterations:
                raise ExecutionLimitError(
                    "Execution reached the iteration limit",
                    details={"limit": self.config.max_iterations},
                )
            if self.state.model_requests >= self.config.max_model_requests:
                raise ExecutionLimitError(
                    "Execution reached the model request limit",
                    details={"limit": self.config.max_model_requests},
                )

            self.state.iteration += 1
            decision = await self._reason()
            if isinstance(decision, FinalDecision):
                await self.checkpoints.record(
                    CheckpointBoundary.BEFORE_COMPLETION,
                    causation_id=self._last_model_response_event_id,
                )
                return decision.content

            pending = [pending_tool_operation(call.id) for call in decision.tool_calls]
            await self.checkpoints.record(
                CheckpointBoundary.AFTER_MODEL_RESPONSE,
                pending_operations=pending,
                causation_id=self._last_model_response_event_id,
            )

            for index, call in enumerate(decision.tool_calls):
                self._ensure_running()
                if self.state.tool_calls >= self.config.max_tool_calls:
                    raise ExecutionLimitError(
                        "Execution reached the tool call limit",
                        details={"limit": self.config.max_tool_calls},
                    )
                completed = await self._act_and_observe(call, self._last_model_response_event_id)
                remaining = [
                    pending_tool_operation(item.id) for item in decision.tool_calls[index + 1 :]
                ]
                await self.checkpoints.record(
                    CheckpointBoundary.AFTER_TOOL_RESULT,
                    completed_tool_calls=[completed],
                    pending_operations=remaining,
                    causation_id=completed.completion_event_id,
                )

    async def _reason(self) -> FinalDecision | ToolCallDecision:
        request_id = str(uuid.uuid4())
        await self.checkpoints.record(
            CheckpointBoundary.BEFORE_MODEL_REQUEST,
            pending_operations=[pending_model_operation(request_id)],
            causation_id=(
                self.checkpoints.latest.metadata.event_id if self.checkpoints.latest else None
            ),
        )
        self._ensure_running()

        model_context = self.context_builder.build(
            config=self.config,
            state=self.state,
            history=self.context.snapshot(),
            tools=self.validator.authorized_specs(),
        )
        allowed_tools = list(model_context.tool_definitions)
        request = ModelRequest(
            request_id=request_id,
            model=self.config.model.model,
            messages=model_context.as_messages(),
            tools=[spec.model_copy(deep=True) for spec in allowed_tools],
            options=dict(self.config.model.options),
            temperature=self.config.model.temperature,
            max_tokens=self.config.model.max_tokens,
        )
        self.provider.require_capabilities(
            request.model,
            streaming=self.config.model.stream_responses,
            tool_calls=bool(request.tools),
        )
        request_event_id = await self.emitter.emit(
            EventType.MODEL_REQUESTED,
            {
                "requestId": request_id,
                "executionId": str(self.config.execution_id),
                "agentId": self.config.agent_id,
                "provider": self.config.model.provider,
                "model": self.config.model.model,
                "iteration": self.state.iteration,
                "toolNames": [spec.name for spec in allowed_tools],
                "messageCount": len(request.messages),
            },
        )

        stream_metadata: dict[str, Any] = {}
        self._model_request_in_flight = True
        try:
            if self.config.model.stream_responses:
                chunks, stream_metadata = await self._stream_chunks(request, request_event_id)
                try:
                    response = aggregate_stream_chunks(chunks)
                except InvalidModelResponseError as error:
                    self.state.model_requests += 1
                    await self._emit_invalid_response(
                        request_id,
                        FinishReason.INCOMPLETE,
                        error,
                        request_event_id,
                        stream_metadata,
                    )
                    raise
            else:
                response = await self._complete_response(request)

            self.state.model_requests += 1
            self._add_usage(response.usage)

            if response.finish_reason == FinishReason.INCOMPLETE:
                error = InvalidModelResponseError(
                    "Model stream ended before completion",
                    code="model.incomplete_stream",
                    details={
                        "requestId": request_id,
                        "chunkCount": stream_metadata.get("chunkCount", 0),
                    },
                )
                await self._emit_invalid_response(
                    request_id,
                    response.finish_reason,
                    error,
                    request_event_id,
                    stream_metadata,
                )
                raise error

            try:
                decision = parse_model_decision(response)
            except InvalidModelResponseError as error:
                await self._emit_invalid_response(
                    request_id,
                    response.finish_reason,
                    error,
                    request_event_id,
                    stream_metadata,
                )
                raise

            self.context.add(
                ModelMessage(
                    role=ModelRole.ASSISTANT,
                    content=response.content,
                    tool_calls=[call.model_copy(deep=True) for call in response.tool_calls],
                )
            )
            self._last_model_response_event_id = await self.emitter.emit(
                EventType.MODEL_RESPONDED,
                {
                    "requestId": request_id,
                    "executionId": str(self.config.execution_id),
                    "decisionType": decision.type,
                    "finishReason": response.finish_reason.value,
                    "toolNames": [call.name for call in response.tool_calls],
                    "usage": response.usage.model_dump(mode="json", exclude_none=True),
                    **stream_metadata,
                },
                causation_id=request_event_id,
            )
            return decision
        except asyncio.CancelledError:
            self._interrupted_operation = f"model:{request_id}"
            raise
        finally:
            self._model_request_in_flight = False

    async def _complete_response(self, request: ModelRequest) -> ModelResponse:
        try:
            return await asyncio.wait_for(
                self.provider.complete(request), timeout=self.config.model.timeout_seconds
            )
        except TimeoutError as error:
            self._interrupted_operation = f"model:{request.request_id}"
            raise ExecutionTimeoutError(
                "Model request timed out",
                code="model.timeout",
                details={
                    "requestId": request.request_id,
                    "model": self.config.model.model,
                },
            ) from error
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(
                "Model provider raised an unexpected error",
                code="provider.unexpected",
                retryable=False,
                details={
                    "requestId": request.request_id,
                    "errorType": type(error).__name__,
                },
            ) from error

    async def _stream_chunks(
        self, request: ModelRequest, request_event_id: str
    ) -> tuple[list[ModelStreamChunk], dict[str, Any]]:
        stream: AsyncIterator[ModelStreamChunk] | None = None
        chunks: list[ModelStreamChunk] = []
        try:
            stream = self.provider.stream(request)
            try:
                async with asyncio.timeout(self.config.model.timeout_seconds):
                    async for chunk in stream:
                        chunks.append(chunk)
                        try:
                            await self.emitter.emit(
                                EventType.MODEL_STREAM_CHUNK,
                                {
                                    "requestId": request.request_id,
                                    "executionId": str(self.config.execution_id),
                                    "iteration": self.state.iteration,
                                    "sequence": len(chunks) - 1,
                                    "contentDeltaLength": len(chunk.content_delta),
                                    "toolCallDeltaCount": len(chunk.tool_calls),
                                    "done": chunk.done,
                                    "finishReason": (
                                        chunk.finish_reason.value if chunk.finish_reason else None
                                    ),
                                    "usageReported": any(
                                        value is not None
                                        for value in (
                                            chunk.usage.input_tokens,
                                            chunk.usage.output_tokens,
                                            chunk.usage.total_tokens,
                                        )
                                    ),
                                },
                                causation_id=request_event_id,
                            )
                        except HarnessError:
                            raise
                        except Exception as error:
                            raise HarnessError(
                                "Failed to emit model stream event",
                                code="event.emit_failed",
                                retryable=False,
                                details={
                                    "requestId": request.request_id,
                                    "errorType": type(error).__name__,
                                },
                            ) from error
            except TimeoutError as error:
                self._interrupted_operation = f"model:{request.request_id}"
                raise ExecutionTimeoutError(
                    "Model stream timed out",
                    code="model.timeout",
                    details={
                        "requestId": request.request_id,
                        "model": self.config.model.model,
                    },
                ) from error
            except ProviderError:
                raise
            except HarnessError:
                raise
            except Exception as error:
                raise ProviderError(
                    "Model provider raised an unexpected error",
                    code="provider.unexpected",
                    retryable=False,
                    details={
                        "requestId": request.request_id,
                        "errorType": type(error).__name__,
                    },
                ) from error
        except asyncio.CancelledError:
            self._interrupted_operation = f"model:{request.request_id}"
            raise
        finally:
            if stream is not None:
                await self._close_stream(stream)
        return chunks, {"streamed": True, "chunkCount": len(chunks)}

    @staticmethod
    def _consume_task_result(task: asyncio.Task[Any]) -> None:
        if not task.cancelled():
            task.exception()

    @classmethod
    async def _close_stream(cls, stream: AsyncIterator[ModelStreamChunk]) -> None:
        close = getattr(stream, "aclose", None)
        if close is None:
            return
        cleanup = asyncio.create_task(close())
        cleanup.add_done_callback(cls._consume_task_result)
        with suppress(Exception, asyncio.CancelledError):
            await asyncio.shield(cleanup)

    async def _emit_invalid_response(
        self,
        request_id: str,
        finish_reason: FinishReason,
        error: InvalidModelResponseError,
        request_event_id: str,
        metadata: dict[str, Any],
    ) -> None:
        await self.emitter.emit(
            EventType.MODEL_RESPONDED,
            {
                "requestId": request_id,
                "executionId": str(self.config.execution_id),
                "decisionType": "invalid",
                "finishReason": finish_reason.value,
                "errorCode": error.code,
                **metadata,
            },
            causation_id=request_event_id,
        )

    async def _act_and_observe(
        self, call: ToolCallRequest, causation_id: str | None
    ) -> CompletedToolCall:
        spec = self.validator.validate(call)
        self.state.tool_calls += 1
        started_at = perf_counter()
        tool_event_id = await self.emitter.emit(
            EventType.TOOL_STARTED,
            {
                "executionId": str(self.config.execution_id),
                "toolCallId": call.id,
                "toolName": spec.name,
            },
            causation_id=causation_id,
        )

        task = asyncio.create_task(self.tool_executor.execute(call, spec), name=f"tool:{call.id}")
        self._active_tool_tasks[call.id] = (call, task)
        try:
            result = await asyncio.wait_for(task, timeout=spec.timeout_seconds)
            result = ToolResult.model_validate(result)
        except TimeoutError:
            with suppress(Exception, asyncio.CancelledError):
                await self.tool_executor.cancel(call)
            result = ToolResult(
                tool_call_id=call.id,
                status="error",
                error=ToolErrorInfo(
                    code="tool.timeout",
                    message="Tool execution timed out",
                    retryable=True,
                ),
            )
        except asyncio.CancelledError:
            self._interrupted_operation = f"tool:{call.id}"
            await self._cancel_tool_resources(call, task)
            raise
        except ToolExecutionError as error:
            result = ToolResult(
                tool_call_id=call.id,
                status="error",
                error=ToolErrorInfo(
                    code=error.code,
                    message=error.message,
                    retryable=error.retryable,
                ),
            )
        except Exception:
            result = ToolResult(
                tool_call_id=call.id,
                status="error",
                error=ToolErrorInfo(
                    code="tool.unexpected",
                    message="Tool execution failed",
                    retryable=False,
                ),
            )
        finally:
            self._active_tool_tasks.pop(call.id, None)

        if result.tool_call_id != call.id:
            raise ToolExecutionError(
                "Tool result did not match the requested call",
                code="tool.invalid_result",
                details={"expectedToolCallId": call.id},
            )

        duration_ms = round((perf_counter() - started_at) * 1000, 3)
        if result.status == "ok":
            completion_event_id = await self.emitter.emit(
                EventType.TOOL_COMPLETED,
                {
                    "executionId": str(self.config.execution_id),
                    "toolCallId": call.id,
                    "toolName": spec.name,
                    "durationMs": duration_ms,
                    "output": result.output,
                },
                causation_id=tool_event_id,
            )
        else:
            error = result.error
            assert error is not None
            completion_event_id = await self.emitter.emit(
                EventType.TOOL_FAILED,
                {
                    "executionId": str(self.config.execution_id),
                    "toolCallId": call.id,
                    "toolName": spec.name,
                    "durationMs": duration_ms,
                    "error": error.model_dump(mode="json"),
                },
                causation_id=tool_event_id,
            )

        self.context.add(
            ModelMessage(
                role=ModelRole.TOOL,
                content=self._observation_text(result),
                tool_call_id=call.id,
                tool_name=spec.name,
            )
        )
        return CompletedToolCall(
            tool_call_id=call.id,
            tool_name=spec.name,
            completion_event_id=completion_event_id,
            status=result.status,
            retryable=result.error.retryable if result.error is not None else False,
        )

    async def _cancel_tool_resources(
        self, call: ToolCallRequest, task: asyncio.Task[ToolResult]
    ) -> None:
        if not task.done():
            task.cancel()
        with suppress(Exception, asyncio.CancelledError):
            await task
        with suppress(Exception, asyncio.CancelledError):
            await self.tool_executor.cancel(call)

    async def _cancel_active_tools(self) -> None:
        active = list(self._active_tool_tasks.values())
        for call, task in active:
            if not task.done():
                task.cancel()
        if active:
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.gather(*(task for _, task in active), return_exceptions=True)
        for call, _ in active:
            with suppress(Exception, asyncio.CancelledError):
                await self.tool_executor.cancel(call)

    async def _cleanup_resources(self) -> None:
        await self._cancel_active_tools()
        with suppress(Exception, asyncio.CancelledError):
            await self.tool_executor.aclose()

    def _ensure_running(self) -> None:
        if self._shutdown_requested:
            raise asyncio.CancelledError

    async def _fail(
        self,
        error: HarnessError,
        reason: TerminalReason,
        error_kind: str = "expected",
    ) -> ExecutionResult:
        if reason is TerminalReason.TIMEOUT:
            error_kind = "timeout"
        info = error.error_info()
        self.state.status = ExecutionStatus.FAILED
        self.state.terminal_reason = reason
        self.state.error = info
        if reason is TerminalReason.TIMEOUT:
            await self.emitter.emit(
                EventType.EXECUTION_TIMED_OUT,
                {
                    "executionId": str(self.config.execution_id),
                    "reason": reason.value,
                    "errorCode": info.code,
                    "interruptedOperation": self._interrupted_operation,
                },
            )
        await self.emitter.emit(
            EventType.EXECUTION_FAILED,
            {
                "executionId": str(self.config.execution_id),
                "error": info.model_dump(mode="json"),
                "reason": reason.value,
                "errorKind": error_kind,
                "interruptedOperation": self._interrupted_operation,
                "iterations": self.state.iteration,
                "modelRequests": self.state.model_requests,
                "toolCalls": self.state.tool_calls,
            },
        )
        return ExecutionResult(
            execution_id=self.config.execution_id,
            status=ExecutionStatus.FAILED,
            error=info,
            state=self.state.model_copy(deep=True),
        )

    def _terminal_reason(self, error: HarnessError) -> TerminalReason:
        if isinstance(error, InvalidModelResponseError):
            return TerminalReason.INVALID_MODEL_RESPONSE
        if isinstance(error, ExecutionLimitError):
            return TerminalReason.LIMIT_EXCEEDED
        if isinstance(error, ExecutionTimeoutError):
            return TerminalReason.TIMEOUT
        if isinstance(error, ToolExecutionError):
            return TerminalReason.TOOL_ERROR
        if isinstance(error, ProviderError):
            return TerminalReason.MODEL_ERROR
        if error.code == "event.emit_failed":
            return TerminalReason.INTERNAL_ERROR
        return TerminalReason.CONFIGURATION_ERROR

    def _add_usage(self, usage: Usage) -> None:
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            current = getattr(self.state.usage, field)
            incoming = getattr(usage, field)
            if incoming is None:
                continue
            setattr(self.state.usage, field, incoming if current is None else current + incoming)

    @staticmethod
    def _observation_text(result: ToolResult) -> str:
        if result.status == "error":
            assert result.error is not None
            return f"Tool failed ({result.error.code}): {result.error.message}"
        if result.output is None:
            return "Tool completed with no output."
        if isinstance(result.output, str):
            return result.output
        return json.dumps(result.output, sort_keys=True, default=str)
