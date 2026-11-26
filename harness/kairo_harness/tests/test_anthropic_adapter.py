import asyncio
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from anthropic import AuthenticationError, RateLimitError
from anthropic.types import Message
from anthropic.types.raw_content_block_delta_event import RawContentBlockDeltaEvent
from anthropic.types.raw_content_block_start_event import RawContentBlockStartEvent
from anthropic.types.raw_message_delta_event import RawMessageDeltaEvent
from anthropic.types.raw_message_start_event import RawMessageStartEvent
from anthropic.types.raw_message_stop_event import RawMessageStopEvent
from kairo_harness.domain import (
    FinishReason,
    ModelCapabilities,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    Usage,
    aggregate_stream_chunks,
)
from kairo_harness.errors import ConfigError, ProviderError
from kairo_harness.providers.anthropic import AnthropicConfig, AnthropicProvider
from support import make_tool, tool_call

MODEL = "claude-sonnet-4-5"
TEST_KEY_ENV = "KAIRO_TEST_ANTHROPIC_KEY"


class FakeMessages:
    def __init__(self, response: Any = None, events: Sequence[Any] = ()) -> None:
        self.response = response
        self.events = list(events)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return self._stream()
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def _stream(self) -> Any:
        for event in self.events:
            yield event


class FakeAnthropicClient:
    def __init__(self, response: Any = None, events: Sequence[Any] = ()) -> None:
        self.messages = FakeMessages(response, events)
        self.models = SimpleNamespace(list=self._list_models)
        self.closed = False

    async def _list_models(self) -> Any:
        return SimpleNamespace(data=[SimpleNamespace(id=MODEL)])

    async def close(self) -> None:
        self.closed = True


def provider_for(
    response: Any = None,
    events: Sequence[Any] = (),
    config: AnthropicConfig | None = None,
) -> tuple[AnthropicProvider, FakeAnthropicClient]:
    client = FakeAnthropicClient(response, events)
    settings = config or AnthropicConfig(api_key_env=TEST_KEY_ENV)
    return AnthropicProvider(settings, client=client), client


def message(
    content: Sequence[dict[str, Any]],
    *,
    stop_reason: str = "end_turn",
    usage: dict[str, int] | None = None,
) -> Message:
    payload: dict[str, Any] = {
        "id": "message-1",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": list(content),
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage or {"input_tokens": 3, "output_tokens": 2},
    }
    return Message.model_validate(payload)


def make_request() -> ModelRequest:
    return ModelRequest(
        request_id="request-1",
        model=MODEL,
        messages=[
            ModelMessage(role=ModelRole.SYSTEM, content="system"),
            ModelMessage(role=ModelRole.USER, content="hello"),
        ],
    )


def test_complete_normalizes_anthropic_response_and_payload() -> None:
    provider, client = provider_for(
        message([{"type": "text", "text": "hello"}], usage={"input_tokens": 4, "output_tokens": 2})
    )

    result = asyncio.run(provider.complete(make_request()))

    assert result.content == "hello"
    assert result.usage == Usage(input_tokens=4, output_tokens=2, total_tokens=6)
    assert result.finish_reason == FinishReason.STOP
    payload = client.messages.calls[0]
    assert payload["model"] == MODEL
    assert payload["system"] == "system"
    assert payload["max_tokens"] == 1024
    assert payload["stream"] is False


def test_complete_normalizes_native_tool_use_and_follow_up_messages() -> None:
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
        message(
            [
                {"type": "tool_use", "id": "call-2", "name": "echo", "input": {"value": "bye"}},
            ],
            stop_reason="tool_use",
        )
    )

    result = asyncio.run(provider.complete(request))

    assert result.finish_reason == FinishReason.TOOL_CALL
    assert result.tool_calls[0].arguments == {"value": "bye"}
    payload = client.messages.calls[0]
    assert payload["tools"][0]["name"] == "echo"
    assert payload["messages"][1]["content"][0]["type"] == "tool_use"
    assert payload["messages"][2]["content"][0]["type"] == "tool_result"
    assert payload["messages"][2]["content"][0]["tool_use_id"] == "call-1"


def test_stream_normalizes_tool_use_fragments_and_cumulative_usage() -> None:
    start = message([], usage={"input_tokens": 3, "output_tokens": 0})
    events = [
        RawMessageStartEvent.model_validate(
            {"type": "message_start", "message": start.model_dump()}
        ),
        RawContentBlockStartEvent.model_validate(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "call-1", "name": "echo", "input": {}},
            }
        ),
        RawContentBlockDeltaEvent.model_validate(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"value":'},
            }
        ),
        RawContentBlockDeltaEvent.model_validate(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '"hi"}'},
            }
        ),
        RawMessageDeltaEvent.model_validate(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 2},
            }
        ),
        RawMessageStopEvent.model_validate({"type": "message_stop"}),
    ]
    provider, _ = provider_for(events=events)

    async def scenario() -> ModelResponse:
        return aggregate_stream_chunks([chunk async for chunk in provider.stream(make_request())])

    result = asyncio.run(scenario())

    assert result.finish_reason == FinishReason.TOOL_CALL
    assert result.tool_calls[0].arguments == {"value": "hi"}
    assert result.usage == Usage(input_tokens=3, output_tokens=2, total_tokens=5)


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (
            AuthenticationError(
                "SECRET_KEY",
                response=httpx2.Response(
                    401, request=httpx2.Request("POST", "https://x.test/v1/messages")
                ),
                body=None,
            ),
            "provider.auth",
            False,
        ),
        (
            RateLimitError(
                "SECRET_KEY",
                response=httpx2.Response(
                    429, request=httpx2.Request("POST", "https://x.test/v1/messages")
                ),
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
    provider, _ = provider_for(response=error)

    with pytest.raises(ProviderError) as error_info:
        asyncio.run(provider.complete(make_request()))

    assert error_info.value.code == code
    assert error_info.value.retryable is retryable
    assert "SECRET_KEY" not in str(error_info.value)
    assert "SECRET_KEY" not in str(error_info.value.details)


def test_capability_override_blocks_tools_and_streaming_before_request() -> None:
    config = AnthropicConfig(
        api_key_env=TEST_KEY_ENV,
        model_capabilities={MODEL: ModelCapabilities(streaming=False, tool_calls=False)},
    )
    provider, client = provider_for(config=config)
    request = make_request()
    request.tools = [make_tool()]

    with pytest.raises(ConfigError) as error_info:
        asyncio.run(provider.complete(request))
    assert error_info.value.code == "provider.capability_unsupported"

    with pytest.raises(ConfigError):
        asyncio.run(collect_stream(provider, make_request()))
    assert client.messages.calls == []


async def collect_stream(provider: AnthropicProvider, request: ModelRequest) -> list[Any]:
    return [chunk async for chunk in provider.stream(request)]


def test_list_models_uses_advertised_capabilities() -> None:
    provider, _ = provider_for()

    models = asyncio.run(provider.list_models())

    assert [model.id for model in models] == [MODEL]
    assert models[0].capabilities.tool_calls is True
