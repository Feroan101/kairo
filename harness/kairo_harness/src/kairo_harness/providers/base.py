from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pydantic import BaseModel, ConfigDict, Field

from kairo_harness.domain import (
    ModelCapabilities,
    ModelDescriptor,
    ModelRequest,
    ModelResponse,
    ModelStreamChunk,
)
from kairo_harness.errors import ConfigError


class ProviderAdapterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: ModelCapabilities = Field(
        default_factory=lambda: ModelCapabilities(streaming=True, tool_calls=True)
    )
    model_capabilities: dict[str, ModelCapabilities] = Field(default_factory=dict)


class ModelProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> ModelCapabilities: ...

    def capabilities_for(self, model: str) -> ModelCapabilities:
        return self.capabilities

    def require_capabilities(
        self,
        model: str,
        *,
        streaming: bool = False,
        tool_calls: bool = False,
    ) -> None:
        capabilities = self.capabilities_for(model)
        missing: list[str] = []
        if streaming and not capabilities.streaming:
            missing.append("streaming")
        if tool_calls and not capabilities.tool_calls:
            missing.append("tool_calls")
        if missing:
            raise ConfigError(
                "Model does not support requested capabilities",
                code="provider.capability_unsupported",
                details={
                    "provider": self.name,
                    "model": model,
                    "capabilities": ",".join(missing),
                },
            )

    @abstractmethod
    async def list_models(self) -> list[ModelDescriptor]: ...

    @abstractmethod
    async def complete(self, request: ModelRequest) -> ModelResponse: ...

    @abstractmethod
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamChunk]: ...
