import asyncio

import pytest
from kairo_harness.domain import ModelRequest
from kairo_harness.errors import ProviderError
from kairo_harness.providers.mock import MockProvider
from support import response


def make_request() -> ModelRequest:
    return ModelRequest(request_id="request-1", model="mock-model", messages=[])


def test_mock_provider_returns_scripted_responses_in_order() -> None:
    provider = MockProvider([response("first"), response("second")])

    async def scenario() -> list[str]:
        return [(await provider.complete(make_request())).content for _ in range(2)]

    assert asyncio.run(scenario()) == ["first", "second"]
    assert len(provider.requests) == 2


def test_mock_provider_raises_scripted_error() -> None:
    provider = MockProvider([ProviderError("boom", code="mock.boom", retryable=False)])

    async def scenario() -> None:
        await provider.complete(make_request())

    with pytest.raises(ProviderError) as error_info:
        asyncio.run(scenario())
    assert error_info.value.code == "mock.boom"


def test_mock_provider_stream_is_deterministic() -> None:
    provider = MockProvider([response("chunk")])

    async def scenario() -> str:
        chunks = [chunk async for chunk in provider.stream(make_request())]
        return "".join(chunk.content_delta for chunk in chunks)

    assert asyncio.run(scenario()) == "chunk"
