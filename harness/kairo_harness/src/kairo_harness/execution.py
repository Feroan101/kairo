from __future__ import annotations

import asyncio
import json
import uuid
from time import perf_counter

from kairo_harness.config import ExecutionConfig
from kairo_harness.context import ExecutionContext
from kairo_harness.domain import (
    FinalDecision,
    ModelMessage,
    ModelRequest,
    ModelRole,
    ToolCallDecision,
    ToolCallRequest,
    ToolErrorInfo,
    ToolResult,
    Usage,
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
from kairo_harness.tools import ToolCallValidator, ToolExecutor

SYSTEM_PROMPT = (
    "You are a Kairo agent. Complete the user's task. Prefer native tool calls when a tool is "
    "needed. If native tool calls are unavailable, respond with exactly one JSON object of the "
    'form {"type":"tool_call","tool_calls":[{"id":"...","name":"...","arguments":{}}]}. '
    "Plain text is treated as the final answer. Do not reveal hidden chain-of-thought."
)


class ExecutionRunner:
    def __init__(
        self,
        config: ExecutionConfig,
        provider: ModelProvider,
        tool_executor: ToolExecutor,
        event_sink: EventSink | None = None,
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
        self.validator = ToolCallValidator(config.tools)
        self.state = ExecutionState(execution_id=config.execution_id)
        self.context = ExecutionContext()
        self._last_model_response_event_id: str | None = None

    async def run(self) -> ExecutionResult:
        if self.state.status != ExecutionStatus.QUEUED:
            raise ConfigError(
                "Execution has already been started", code="execution.already_started"
            )

        self.state.status = ExecutionStatus.RUNNING
        self.context.add(ModelMessage(role=ModelRole.SYSTEM, content=SYSTEM_PROMPT))
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

        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                output = await self._react()
        except TimeoutError:
            failure = ExecutionTimeoutError(
                "Execution timed out",
                details={"limitSeconds": self.config.timeout_seconds},
            )
            return await self._fail(failure, TerminalReason.TIMEOUT)
        except asyncio.CancelledError:
            self.state.status = ExecutionStatus.CANCELLED
            self.state.terminal_reason = TerminalReason.CANCELLED
            await self.emitter.emit(
                EventType.EXECUTION_CANCELLED,
                {"executionId": str(self.config.execution_id)},
            )
            raise
        except HarnessError as error:
            return await self._fail(error, self._terminal_reason(error))
        except Exception as error:
            failure = HarnessError(
                "Unexpected harness failure",
                code="execution.unexpected",
                details={"errorType": type(error).__name__},
            )
            return await self._fail(failure, TerminalReason.INTERNAL_ERROR)

        self.state.status = ExecutionStatus.COMPLETED
        self.state.terminal_reason = TerminalReason.COMPLETED
        await self.emitter.emit(
            EventType.EXECUTION_COMPLETED,
            {
                "executionId": str(self.config.execution_id),
                "output": output,
                "iterations": self.state.iteration,
                "modelRequests": self.state.model_requests,
                "toolCalls": self.state.tool_calls,
                "usage": self.state.usage.model_dump(mode="json", exclude_none=True),
            },
        )
        return ExecutionResult(
            execution_id=self.config.execution_id,
            status=ExecutionStatus.COMPLETED,
            output=output,
            state=self.state.model_copy(deep=True),
        )

    async def _react(self) -> str:
        while True:
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
                return decision.content

            for call in decision.tool_calls:
                if self.state.tool_calls >= self.config.max_tool_calls:
                    raise ExecutionLimitError(
                        "Execution reached the tool call limit",
                        details={"limit": self.config.max_tool_calls},
                    )
                await self._act_and_observe(call, self._last_model_response_event_id)

    async def _reason(self) -> FinalDecision | ToolCallDecision:
        request_id = str(uuid.uuid4())
        allowed_tools = [spec for spec in self.config.tools if spec.allowed]
        request = ModelRequest(
            request_id=request_id,
            model=self.config.model.model,
            messages=self.context.snapshot(),
            tools=[spec.model_copy(deep=True) for spec in allowed_tools],
            options=dict(self.config.model.options),
            temperature=self.config.model.temperature,
            max_tokens=self.config.model.max_tokens,
        )
        request_event_id = await self.emitter.emit(
            EventType.MODEL_REQUESTED,
            {
                "requestId": request_id,
                "executionId": str(self.config.execution_id),
                "provider": self.config.model.provider,
                "model": self.config.model.model,
                "iteration": self.state.iteration,
                "toolNames": [spec.name for spec in allowed_tools],
                "messageCount": len(request.messages),
            },
        )

        try:
            response = await asyncio.wait_for(
                self.provider.complete(request), timeout=self.config.model.timeout_seconds
            )
        except TimeoutError as error:
            raise ExecutionTimeoutError(
                "Model request timed out",
                code="model.timeout",
                details={"requestId": request_id, "model": self.config.model.model},
            ) from error
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(
                "Model provider raised an unexpected error",
                code="provider.unexpected",
                retryable=False,
                details={"requestId": request_id, "errorType": type(error).__name__},
            ) from error

        self.state.model_requests += 1
        self._add_usage(response.usage)

        try:
            decision = parse_model_decision(response)
        except InvalidModelResponseError as error:
            await self.emitter.emit(
                EventType.MODEL_RESPONDED,
                {
                    "requestId": request_id,
                    "executionId": str(self.config.execution_id),
                    "decisionType": "invalid",
                    "finishReason": response.finish_reason.value,
                    "errorCode": error.code,
                },
                causation_id=request_event_id,
            )
            raise

        self.context.add(ModelMessage(role=ModelRole.ASSISTANT, content=response.content))
        self._last_model_response_event_id = await self.emitter.emit(
            EventType.MODEL_RESPONDED,
            {
                "requestId": request_id,
                "executionId": str(self.config.execution_id),
                "decisionType": decision.type,
                "finishReason": response.finish_reason.value,
                "toolNames": [call.name for call in response.tool_calls],
                "usage": response.usage.model_dump(mode="json", exclude_none=True),
            },
            causation_id=request_event_id,
        )
        return decision

    async def _act_and_observe(self, call: ToolCallRequest, causation_id: str | None) -> None:
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

        try:
            result = await asyncio.wait_for(
                self.tool_executor.execute(call, spec), timeout=spec.timeout_seconds
            )
            result = ToolResult.model_validate(result)
        except TimeoutError:
            result = ToolResult(
                tool_call_id=call.id,
                status="error",
                error=ToolErrorInfo(
                    code="tool.timeout",
                    message="Tool execution timed out",
                    retryable=True,
                ),
            )
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

        if result.tool_call_id != call.id:
            raise ToolExecutionError(
                "Tool result did not match the requested call",
                code="tool.invalid_result",
                details={"expectedToolCallId": call.id},
            )

        duration_ms = round((perf_counter() - started_at) * 1000, 3)
        if result.status == "ok":
            await self.emitter.emit(
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
            await self.emitter.emit(
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

    async def _fail(self, error: HarnessError, reason: TerminalReason) -> ExecutionResult:
        info = error.error_info()
        self.state.status = ExecutionStatus.FAILED
        self.state.terminal_reason = reason
        self.state.error = info
        await self.emitter.emit(
            EventType.EXECUTION_FAILED,
            {
                "executionId": str(self.config.execution_id),
                "error": info.model_dump(mode="json"),
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
