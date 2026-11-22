from collections import deque
from collections.abc import Sequence
from uuid import UUID, uuid4

from kairo_harness.config import ExecutionConfig, ModelConfig
from kairo_harness.domain import ModelResponse, ToolCallRequest, ToolResult, ToolSpec, Usage
from kairo_harness.tools import ToolExecutor

ECHO_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}


def make_tool(
    name: str = "echo",
    *,
    allowed: bool = True,
    required_permissions: frozenset[str] = frozenset(),
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Echo a value",
        input_schema=ECHO_SCHEMA,
        allowed=allowed,
        required_permissions=required_permissions,
        timeout_seconds=1.0,
    )


def make_config(
    *,
    tools: Sequence[ToolSpec] = (),
    task: str = "Echo hello",
    max_iterations: int = 4,
    max_model_requests: int = 4,
    max_tool_calls: int = 4,
    execution_id: UUID | None = None,
    granted_permissions: frozenset[str] = frozenset(),
    stream_responses: bool = False,
) -> ExecutionConfig:
    return ExecutionConfig(
        agent_id="agent-1",
        execution_id=execution_id or uuid4(),
        task=task,
        model=ModelConfig(
            provider="mock",
            model="mock-model",
            timeout_seconds=1.0,
            stream_responses=stream_responses,
        ),
        tools=list(tools),
        granted_permissions=granted_permissions,
        max_iterations=max_iterations,
        max_model_requests=max_model_requests,
        max_tool_calls=max_tool_calls,
        timeout_seconds=5.0,
    )


def tool_call(call_id: str = "call-1", name: str = "echo", **arguments: object) -> ToolCallRequest:
    return ToolCallRequest(id=call_id, name=name, arguments=arguments)


def response(
    content: str = "",
    tool_calls: Sequence[ToolCallRequest] = (),
    usage: Usage | None = None,
) -> ModelResponse:
    return ModelResponse(
        content=content,
        tool_calls=list(tool_calls),
        usage=usage or Usage(input_tokens=3, output_tokens=2, total_tokens=5),
    )


class ScriptedToolExecutor(ToolExecutor):
    def __init__(self, results: Sequence[ToolResult | Exception] = ()) -> None:
        self._results: deque[ToolResult | Exception] = deque(results)
        self.calls: list[ToolCallRequest] = []

    async def execute(self, call: ToolCallRequest, spec: ToolSpec) -> ToolResult:
        self.calls.append(call)
        if self._results:
            item = self._results.popleft()
            if isinstance(item, Exception):
                raise item
            return item
        return ToolResult(
            tool_call_id=call.id,
            status="ok",
            output={"echo": call.arguments.get("value")},
        )
