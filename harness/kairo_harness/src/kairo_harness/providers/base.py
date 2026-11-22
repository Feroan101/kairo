from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from kairo_harness.domain import ModelDescriptor, ModelRequest, ModelResponse, ModelStreamChunk


class ModelProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def list_models(self) -> list[ModelDescriptor]: ...

    @abstractmethod
    async def complete(self, request: ModelRequest) -> ModelResponse: ...

    @abstractmethod
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamChunk]: ...
