import asyncio
from collections.abc import Sequence

from kairo_harness.config import ExecutionConfig
from kairo_harness.context import (
    DEFAULT_SYSTEM_INSTRUCTIONS,
    ContextBuilder,
    DefaultContextBuilder,
    ModelContext,
)
from kairo_harness.domain import ModelMessage, ModelRole, ToolSpec
from kairo_harness.events import InMemoryEventSink
from kairo_harness.execution import ExecutionRunner
from kairo_harness.providers.mock import MockProvider
from kairo_harness.state import ExecutionState, ExecutionStatus
from support import ScriptedToolExecutor, make_config, make_tool, response


def test_default_builder_separates_harness_state_from_model_context() -> None:
    config = make_config()
    config.system_instructions = "Extra agent guidance"
    state = ExecutionState(execution_id=config.execution_id)
    state.iteration = 2
    history = [ModelMessage(role=ModelRole.USER, content="Do the task")]
    tools = [make_tool("echo")]

    context = DefaultContextBuilder().build(
        config=config,
        state=state,
        history=history,
        tools=tools,
    )

    assert context.system_instructions == [DEFAULT_SYSTEM_INSTRUCTIONS, "Extra agent guidance"]
    assert context.messages == history
    assert context.tool_definitions == tools
    assert context.metadata == {
        "executionId": str(config.execution_id),
        "agentId": config.agent_id,
        "correlationId": str(config.correlation_id),
        "iteration": 2,
        "toolCount": 1,
    }
    assert state.iteration == 2
    assert history[0].content == "Do the task"


def test_model_context_instructions_are_converted_without_mutating_history() -> None:
    history = [ModelMessage(role=ModelRole.USER, content="Task")]
    context = ModelContext(
        system_instructions=["one", "two"],
        messages=history,
        metadata={"iteration": 1},
    )

    messages = context.as_messages()

    assert [message.role for message in messages] == [
        ModelRole.SYSTEM,
        ModelRole.SYSTEM,
        ModelRole.USER,
    ]
    assert [message.content for message in messages] == ["one", "two", "Task"]
    assert history == [ModelMessage(role=ModelRole.USER, content="Task")]


def test_runner_uses_an_injected_provider_independent_context_builder() -> None:
    class CapturingBuilder(ContextBuilder):
        def __init__(self) -> None:
            self.calls: list[tuple[ExecutionConfig, ExecutionState, ToolSpec | None]] = []

        def build(
            self,
            *,
            config: ExecutionConfig,
            state: ExecutionState,
            history: Sequence[ModelMessage],
            tools: Sequence[ToolSpec],
        ) -> ModelContext:
            self.calls.append((config, state, tools[0] if tools else None))
            return ModelContext(
                system_instructions=["custom instructions"],
                messages=list(history),
                tool_definitions=list(tools),
                metadata={"iteration": state.iteration},
            )

    config = make_config()
    builder = CapturingBuilder()
    provider = MockProvider([response("done")])
    runner = ExecutionRunner(
        config,
        provider,
        ScriptedToolExecutor(),
        InMemoryEventSink(),
        context_builder=builder,
    )

    result = asyncio.run(runner.run())

    assert result.status == ExecutionStatus.COMPLETED
    assert builder.calls[0][0] is config
    assert builder.calls[0][1].iteration == 1
    assert builder.calls[0][2] is None
    assert provider.requests[0].messages[0].content == "custom instructions"
    assert all("Kairo agent" not in message.content for message in provider.requests[0].messages)
