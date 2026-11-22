from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kairo_harness.domain import OptionValue, ToolSpec, validate_permission_names


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.-]*$")
    model: str = Field(min_length=1, max_length=200)
    options: dict[str, OptionValue] = Field(default_factory=dict)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    stream_responses: bool = False


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=200)
    execution_id: UUID
    task: str = Field(min_length=1)
    model: ModelConfig
    tools: list[ToolSpec] = Field(default_factory=list)
    granted_permissions: frozenset[str] = Field(default_factory=frozenset)
    max_iterations: int = Field(default=8, ge=1, le=100)
    max_model_requests: int = Field(default=8, ge=1, le=100)
    max_tool_calls: int = Field(default=4, ge=0, le=100)
    timeout_seconds: float = Field(default=120.0, gt=0, le=3600)
    correlation_id: UUID | None = None

    @field_validator("granted_permissions")
    @classmethod
    def validate_granted_permissions(cls, value: frozenset[str]) -> frozenset[str]:
        return validate_permission_names(value)

    @model_validator(mode="after")
    def apply_default_correlation_id(self) -> ExecutionConfig:
        if self.correlation_id is None:
            self.correlation_id = self.execution_id
        return self
