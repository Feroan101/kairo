from collections import deque
from collections.abc import AsyncIterator, Sequence

from kairo_harness.domain import (
    FinishReason,
    ModelCapabilities,
    ModelDescriptor,
    ModelRequest,
    ModelResponse,
    ModelStreamChunk,
    ToolCallDelta,
)
from kairo_harness.errors import ProviderError
from kairo_harness.providers.base import ModelProvider


class MockProvider(ModelProvider):
    def __init__(
        self,
        responses: Sequence[ModelResponse | Exception] = (),
        *,
        models: Sequence[ModelDescriptor] | None = None,
    ) -> None:
        self._responses: deque[ModelResponse | Exception] = deque(responses)
        self._models = list(
            models
            or [
                ModelDescriptor(
                    id="mock-model",
                    name="Mock model",
                    capabilities=ModelCapabilities(streaming=True, tool_calls=True),
                )
            ]
        )
        self.requests: list[ModelRequest] = []

    @property
    def name(self) -> str:
        return "mock"

    async def list_models(self) -> list[ModelDescriptor]:
        return [model.model_copy(deep=True) for model in self._models]

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request.model_copy(deep=True))
        if not self._responses:
            raise ProviderError(
                "Mock provider has no queued response",
                code="mock.no_queued_response",
                retryable=False,
            )

        item = self._responses.popleft()
        if isinstance(item, Exception):
            raise item
        return item.model_copy(deep=True)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamChunk]:
        response = await self.complete(request)
        tool_calls = [
            ToolCallDelta(index=index, id=call.id, name=call.name, arguments=call.arguments)
            for index, call in enumerate(response.tool_calls)
        ]
        yield ModelStreamChunk(
            content_delta=response.content,
            tool_calls=tool_calls,
            usage=response.usage,
            done=True,
            finish_reason=FinishReason.TOOL_CALL if tool_calls else FinishReason.STOP,
        )
