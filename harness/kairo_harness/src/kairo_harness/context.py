from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from kairo_harness.config import ExecutionConfig
from kairo_harness.domain import ModelMessage, ModelRole, ToolSpec
from kairo_harness.state import ExecutionState

DEFAULT_SYSTEM_INSTRUCTIONS = (
    "You are a Kairo agent. Complete the user's task. Prefer native tool calls when a tool is "
    "needed. If native tool calls are unavailable, respond with exactly one JSON object of the "
    'form {"type":"tool_call","tool_calls":[{"id":"...","name":"...","arguments":{}}]}. '
    "Plain text is treated as the final answer. Do not reveal hidden chain-of-thought."
)


class ExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ModelMessage] = Field(default_factory=list)

    def add(self, message: ModelMessage) -> None:
        self.messages.append(message)

    def snapshot(self) -> list[ModelMessage]:
        return [message.model_copy(deep=True) for message in self.messages]


class ModelContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_instructions: list[str] = Field(default_factory=list)
    messages: list[ModelMessage] = Field(default_factory=list)
    tool_definitions: list[ToolSpec] = Field(default_factory=list)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    def as_messages(self) -> list[ModelMessage]:
        instructions = [
            ModelMessage(role=ModelRole.SYSTEM, content=instruction)
            for instruction in self.system_instructions
        ]
        return instructions + [message.model_copy(deep=True) for message in self.messages]


class ContextBuilder(ABC):
    @abstractmethod
    def build(
        self,
        *,
        config: ExecutionConfig,
        state: ExecutionState,
        history: Sequence[ModelMessage],
        tools: Sequence[ToolSpec],
    ) -> ModelContext: ...


class DefaultContextBuilder(ContextBuilder):
    def __init__(self, system_instructions: str = DEFAULT_SYSTEM_INSTRUCTIONS) -> None:
        if not system_instructions.strip():
            raise ValueError("system instructions must not be blank")
        self.system_instructions = system_instructions

    def build(
        self,
        *,
        config: ExecutionConfig,
        state: ExecutionState,
        history: Sequence[ModelMessage],
        tools: Sequence[ToolSpec],
    ) -> ModelContext:
        instructions = [self.system_instructions]
        if config.system_instructions:
            instructions.append(config.system_instructions)
        return ModelContext(
            system_instructions=instructions,
            messages=[message.model_copy(deep=True) for message in history],
            tool_definitions=[tool.model_copy(deep=True) for tool in tools],
            metadata={
                "executionId": str(config.execution_id),
                "agentId": config.agent_id,
                "correlationId": str(config.correlation_id or config.execution_id),
                "iteration": state.iteration,
                "toolCount": len(tools),
            },
        )
