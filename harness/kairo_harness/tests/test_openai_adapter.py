import asyncio
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from kairo_harness.config import ExecutionConfig, ModelConfig
from kairo_harness.domain import (
    FinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    Usage,
    aggregate_stream_chunks,
)
from kairo_harness.errors import ConfigError, ProviderError
from kairo_harness.execution import ExecutionRunner
from kairo_harness.providers.openai import OpenAIConfig, OpenAIProvider
from openai import AuthenticationError, RateLimitError
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from support import ScriptedToolExecutor, make_config, make_tool, tool_call

TEST_KEY_ENV = "KAIRO_TEST_OPENAI_KEY"
MODEL = "gpt-4o-mini"


class FakeCompletions:
    def __init__(self, responses: Sequence[Any] = (), chunks: Sequence[Any] = ()) -> None:
        self._responses = list(responses)
        self._chunks = list(chunks)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return self._stream()
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def _stream(self) -> Any:
        for chunk in self._chunks:
            yield chunk


class FakeOpenAIClient:
    def __init__(self, responses: Sequence[Any] = (), chunks: Sequence[Any] = ()) -> None:
        self.completions = FakeCompletions(responses, chunks)
        self.chat = SimpleNamespace(completions=self.completions)
        self.models = SimpleNamespace(list=self._list_models)
        self.closed = False

    async def _list_models(self) -> Any:
        return SimpleNamespace(data=[SimpleNamespace(id=MODEL)])

    async def close(self) -> None:
        self.closed = True


def provider_for(
    responses: Sequence[Any] = (),
    chunks: Sequence[Any] = (),
) -> tuple[OpenAIProvider, FakeOpenAIClient]:
    client = FakeOpenAIClient(responses, chunks)
    return OpenAIProvider(OpenAIConfig(api_key_env=TEST_KEY_ENV), client=client), client


def completion(
    content: str = "",
    tool_calls: Sequence[dict[str, Any]] = (),
    finish_reason: str = "stop",
    usage: dict[str, int] | None = None,
) -> ChatCompletion:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = list(tool_calls)
    payload: dict[str, Any] = {
        "id": "completion-1",
        "object": "chat.completion",
        "created": 1,
        "model": MODEL,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }
    if usage:
        payload["usage"] = usage
    return ChatCompletion.model_validate(payload)


def chunk(
    content: str = "",
    tool_calls: Sequence[dict[str, Any]] = (),
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
) -> ChatCompletionChunk:
    delta: dict[str, Any] = {"content": content}
    if tool_calls:
        delta["tool_calls"] = list(tool_calls)
    payload: dict[str, Any] = {
        "id": "chunk-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": MODEL,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage:
        payload["choices"] = []
        payload["usage"] = usage
    return ChatCompletionChunk.model_validate(payload)


def make_request() -> ModelRequest:
    return ModelRequest(
        request_id="request-1",
        model=MODEL,
        messages=[
            ModelMessage(role=ModelRole.SYSTEM, content="system"),
            ModelMessage(role=ModelRole.USER, content="hello"),
        ],
        max_tokens=20,
    )


def test_complete_normalizes_openai_response_and_payload() -> None:
    provider, client = provider_for(
        [
            completion(
                "hello",
                finish_reason="stop",
                usage={"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            )
        ]
    )

    result = asyncio.run(provider.complete(make_request()))

    assert result.content == "hello"
    assert result.usage == Usage(input_tokens=4, output_tokens=2, total_tokens=6)
    assert result.finish_reason == FinishReason.STOP
    payload = client.completions.calls[0]
    assert payload["model"] == MODEL
    assert payload["messages"][0] == {"role": "system", "content": "system"}
    assert payload["max_tokens"] == 20
    assert payload["stream"] is False


def test_complete_normalizes_native_tool_calls_and_follow_up_messages() -> None:
    request = ModelRequest(
        request_id="request-2",
        model=MODEL,
        messages=[
            ModelMessage(role=ModelRole.SYSTEM, content="system"),
            ModelMessage(role=ModelRole.USER, content="echo hi"),
            ModelMessage(
                role=ModelRole.ASSISTANT,
                content="",
                tool_calls=[tool_call("call-1", "echo", value="hi")],
            ),
            ModelMessage(
                role=ModelRole.TOOL,
                content='{"echo": "hi"}',
                tool_call_id="call-1",
                tool_name="echo",
            ),
        ],
        tools=[make_tool()],
    )
    provider, client = provider_for(
        [
            completion(
                tool_calls=[
                    {
                        "id": "call-2",
                        "type": "function",
                        "function": {"name": "echo", "arguments": '{"value": "bye"}'},
                    }
                ],
                finish_reason="tool_calls",
            )
        ]
    )

    result = asyncio.run(provider.complete(request))

    assert result.finish_reason == FinishReason.TOOL_CALL
    assert result.tool_calls[0].arguments == {"value": "bye"}
    payload = client.completions.calls[0]
    assert payload["tools"][0]["function"]["name"] == "echo"
    assert payload["messages"][2]["tool_calls"][0]["id"] == "call-1"
    assert payload["messages"][3] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"echo": "hi"}',
    }


def test_stream_normalizes_tool_call_fragments_and_cumulative_usage() -> None:
    provider, client = provider_for(
        chunks=[
            chunk(content="thinking"),
            chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "echo", "arguments": '{"value":'},
                    }
                ]
            ),
            chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "type": "function",
                        "function": {"arguments": '"hi"}'},
                    }
                ],
                finish_reason="tool_calls",
            ),
            chunk(usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}),
        ]
    )

    async def scenario() -> tuple[list[Usage], ModelResponse]:
        chunks = [item async for item in provider.stream(make_request())]
        return [item.usage for item in chunks], aggregate_stream_chunks(chunks)

    chunk_usage, aggregated = asyncio.run(scenario())

    assert chunk_usage == [
        Usage(),
        Usage(),
        Usage(),
        Usage(input_tokens=5, output_tokens=3, total_tokens=8),
    ]
    assert aggregated.content == "thinking"
    assert aggregated.finish_reason == FinishReason.TOOL_CALL
    assert aggregated.tool_calls[0].arguments == {"value": "hi"}
    assert aggregated.usage == Usage(input_tokens=5, output_tokens=3, total_tokens=8)
    assert client.completions.calls[0]["stream_options"] == {"include_usage": True}


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (
            AuthenticationError(
                "SECRET_KEY",
                response=httpx.Response(401, request=httpx.Request("POST", "https://x.test")),
                body=None,
            ),
            "provider.auth",
            False,
        ),
        (
            RateLimitError(
                "SECRET_KEY",
                response=httpx.Response(429, request=httpx.Request("POST", "https://x.test")),
                body=None,
            ),
            "provider.rate_limited",
            True,
        ),
    ],
)
def test_cloud_errors_are_classified_without_leaking_secrets(
    error: Exception, code: str, retryable: bool
) -> None:
    provider, _ = provider_for([error])

    with pytest.raises(ProviderError) as error_info:
        asyncio.run(provider.complete(make_request()))

    assert error_info.value.code == code
    assert error_info.value.retryable is retryable
    assert "SECRET_KEY" not in str(error_info.value)
    assert "SECRET_KEY" not in str(error_info.value.details)


def test_malformed_completion_fails_safely() -> None:
    malformed = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="", tool_calls=None),
                finish_reason="unexpected",
            )
        ],
        usage=None,
    )
    provider, _ = provider_for([malformed])

    with pytest.raises(ProviderError) as error_info:
        asyncio.run(provider.complete(make_request()))

    assert error_info.value.code == "provider.invalid_finish_reason"


def test_list_models_uses_advertised_capabilities() -> None:
    provider, _ = provider_for()

    models = asyncio.run(provider.list_models())

    assert [model.id for model in models] == [MODEL]
    assert models[0].capabilities.streaming is True
    assert models[0].capabilities.tool_calls is True


def test_openai_credentials_are_not_part_of_model_configuration() -> None:
    config = ExecutionConfig(
        agent_id="agent-1",
        execution_id=uuid4(),
        task="hello",
        model=ModelConfig(provider="openai", model=MODEL),
    )

    assert TEST_KEY_ENV not in str(config.model_dump())
    with pytest.raises(ConfigError):
        OpenAIConfig(api_key_env="KAIRO_MISSING_KEY").api_key({})


def test_runner_uses_selected_openai_provider_and_model() -> None:
    provider, client = provider_for(
        [
            completion(
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "echo", "arguments": '{"value": "hi"}'},
                    }
                ],
                finish_reason="tool_calls",
            ),
            completion("done", finish_reason="stop"),
        ]
    )
    config = make_config(
        provider="openai",
        model=MODEL,
        tools=[make_tool()],
        max_iterations=3,
        max_model_requests=3,
        max_tool_calls=1,
    )
    runner = ExecutionRunner(config, provider, ScriptedToolExecutor())

    result = asyncio.run(runner.run())

    assert result.status.value == "completed"
    assert result.output == "done"
    assert [call["model"] for call in client.completions.calls] == [MODEL, MODEL]
