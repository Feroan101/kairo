import asyncio
import json
from collections.abc import Callable

import httpx
import pytest
from kairo_harness.domain import (
    FinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    Usage,
    aggregate_stream_chunks,
)
from kairo_harness.errors import ProviderError
from kairo_harness.providers.ollama import OllamaConfig, OllamaProvider

BASE_URL = "http://ollama.test:11434"


def make_request() -> ModelRequest:
    return ModelRequest(
        request_id="request-1",
        model="gemma3:270m",
        messages=[ModelMessage(role=ModelRole.USER, content="hello")],
        max_tokens=20,
    )


def provider_for(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[OllamaProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    provider = OllamaProvider(OllamaConfig(base_url=BASE_URL), client=client)
    return provider, client


def test_complete_normalizes_ollama_chat_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["stream"] is False
        assert body["options"]["num_predict"] == 20
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "hello"},
                "prompt_eval_count": 4,
                "eval_count": 2,
                "done_reason": "stop",
            },
        )

    provider, client = provider_for(handler)

    async def scenario() -> None:
        async with client:
            result = await provider.complete(make_request())
            assert result.content == "hello"
            assert result.usage.input_tokens == 4
            assert result.usage.output_tokens == 2
            assert result.usage.total_tokens == 6
            assert result.finish_reason == FinishReason.STOP

    asyncio.run(scenario())


def test_complete_normalizes_native_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "echo",
                                "arguments": json.dumps({"value": "hi"}),
                            }
                        }
                    ],
                },
                "eval_count": 1,
            },
        )

    provider, client = provider_for(handler)

    async def scenario() -> None:
        async with client:
            result = await provider.complete(make_request())
            assert len(result.tool_calls) == 1
            assert result.tool_calls[0].name == "echo"
            assert result.tool_calls[0].arguments == {"value": "hi"}
            assert result.finish_reason == FinishReason.TOOL_CALL

    asyncio.run(scenario())


def test_list_models_uses_configured_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "gemma3:270m"}]})

    provider, client = provider_for(handler)

    async def scenario() -> None:
        async with client:
            models = await provider.list_models()
            assert [model.id for model in models] == ["gemma3:270m"]
            assert models[0].capabilities.tool_calls is True

    asyncio.run(scenario())


def test_stream_parses_ndjson_chunks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        return httpx.Response(
            200,
            text=(
                '{"message":{"content":"he"},"done":false}\n'
                '{"message":{"content":"llo"},"prompt_eval_count":5,"eval_count":2,"done":true}\n'
            ),
        )

    provider, client = provider_for(handler)

    async def scenario() -> None:
        async with client:
            chunks = [chunk async for chunk in provider.stream(make_request())]
            assert "".join(chunk.content_delta for chunk in chunks) == "hello"
            assert chunks[-1].usage.total_tokens == 7
            assert chunks[-1].done is True

    asyncio.run(scenario())


def test_stream_normalizes_cumulative_usage_to_deltas() -> None:
    payloads = [
        {
            "message": {"content": "he"},
            "prompt_eval_count": 5,
            "eval_count": 2,
            "done": False,
        },
        {
            "message": {"content": "llo"},
            "prompt_eval_count": 5,
            "eval_count": 4,
            "done": False,
        },
        {
            "message": {"content": ""},
            "prompt_eval_count": 5,
            "eval_count": 6,
            "done": True,
            "done_reason": "stop",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="\n".join(json.dumps(item) for item in payloads))

    provider, client = provider_for(handler)

    async def scenario() -> tuple[list[Usage], Usage]:
        async with client:
            chunks = [chunk async for chunk in provider.stream(make_request())]
            return [chunk.usage for chunk in chunks], aggregate_stream_chunks(chunks).usage

    chunk_usage, aggregated_usage = asyncio.run(scenario())

    assert chunk_usage == [
        Usage(input_tokens=5, output_tokens=2, total_tokens=7),
        Usage(input_tokens=0, output_tokens=2, total_tokens=2),
        Usage(input_tokens=0, output_tokens=2, total_tokens=2),
    ]
    assert aggregated_usage == Usage(input_tokens=5, output_tokens=6, total_tokens=11)


def test_stream_derives_total_from_sparse_cumulative_usage() -> None:
    payloads = [
        {
            "message": {"content": "he"},
            "prompt_eval_count": 5,
            "done": False,
        },
        {
            "message": {"content": "llo"},
            "eval_count": 6,
            "done": True,
            "done_reason": "stop",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="\n".join(json.dumps(item) for item in payloads))

    provider, client = provider_for(handler)

    async def scenario() -> tuple[list[Usage], Usage]:
        async with client:
            chunks = [chunk async for chunk in provider.stream(make_request())]
            return [chunk.usage for chunk in chunks], aggregate_stream_chunks(chunks).usage

    chunk_usage, aggregated_usage = asyncio.run(scenario())

    assert chunk_usage == [Usage(input_tokens=5), Usage(output_tokens=6)]
    assert aggregated_usage == Usage(input_tokens=5, output_tokens=6, total_tokens=11)


def test_stream_reconstructs_native_tool_calls_and_finish_reason() -> None:
    first = {
        "message": {
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {"name": "echo", "arguments": '{"value":'},
                }
            ]
        },
        "done": False,
    }
    second = {
        "message": {
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {"name": "echo", "arguments": '"hi"}'},
                }
            ]
        },
        "done": True,
        "done_reason": "stop",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, text="\n".join(json.dumps(item) for item in (first, second)))

    provider, client = provider_for(handler)

    async def scenario() -> None:
        async with client:
            chunks = [chunk async for chunk in provider.stream(make_request())]
            assert chunks[0].finish_reason is None
            assert chunks[1].finish_reason == FinishReason.TOOL_CALL
            aggregated = aggregate_stream_chunks(chunks)
            assert aggregated.finish_reason == FinishReason.TOOL_CALL
            assert aggregated.tool_calls[0].id == "call-1"
            assert aggregated.tool_calls[0].name == "echo"
            assert aggregated.tool_calls[0].arguments == {"value": "hi"}

    asyncio.run(scenario())


def test_stream_reconstructs_tool_call_fragments_without_repeated_ids() -> None:
    first = {
        "message": {
            "tool_calls": [
                {
                    "id": "call-a",
                    "function": {"name": "echo", "arguments": '{"value":'},
                },
                {
                    "id": "call-b",
                    "function": {"name": "sum", "arguments": '{"value":'},
                },
            ]
        },
        "done": False,
    }
    second = {
        "message": {
            "tool_calls": [
                {"function": {"name": "echo", "arguments": '"a"}'}},
                {"function": {"name": "sum", "arguments": '"b"}'}},
            ]
        },
        "done": True,
        "done_reason": "stop",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, text="\n".join(json.dumps(item) for item in (first, second)))

    provider, client = provider_for(handler)

    async def scenario() -> ModelResponse:
        async with client:
            chunks = [chunk async for chunk in provider.stream(make_request())]
            return aggregate_stream_chunks(chunks)

    aggregated = asyncio.run(scenario())

    assert [call.id for call in aggregated.tool_calls] == ["call-a", "call-b"]
    assert [call.name for call in aggregated.tool_calls] == ["echo", "sum"]
    assert [call.arguments for call in aggregated.tool_calls] == [
        {"value": "a"},
        {"value": "b"},
    ]


def test_http_status_errors_are_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    provider, client = provider_for(handler)

    async def scenario() -> None:
        async with client:
            await provider.complete(make_request())

    with pytest.raises(ProviderError) as error_info:
        asyncio.run(scenario())
    assert error_info.value.code == "provider.http_503"
    assert error_info.value.retryable is True
    assert "unavailable" not in str(error_info.value)


def test_malformed_chat_response_fails_safely() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    provider, client = provider_for(handler)

    async def scenario() -> None:
        async with client:
            await provider.complete(make_request())

    with pytest.raises(ProviderError) as error_info:
        asyncio.run(scenario())
    assert error_info.value.code == "provider.invalid_response"
