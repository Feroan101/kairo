from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from kairo_harness.domain import ModelMessage


class ExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ModelMessage] = Field(default_factory=list)

    def add(self, message: ModelMessage) -> None:
        self.messages.append(message)

    def snapshot(self) -> list[ModelMessage]:
        return [message.model_copy(deep=True) for message in self.messages]
