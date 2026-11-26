import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import httpx
import pytest
from anthropic.types import (
    Message,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RawMessageDeltaEvent,
    RawMessageStartEvent,
    RawMessageStopEvent,
)
from google.genai import types
from kairo_harness.domain import (
    FinishReason,
    ModelCapabilities,
    ModelMessage,
    ModelRequest,
    ModelRole,
    ToolCallRequest,
    ToolSpec,
)
from kairo_harness.errors import ConfigError, ProviderError
from kairo_harness.events import EventEnvelope, EventType, InMemoryEventSink
from kairo_harness.execution import ExecutionRunner
from kairo_harness.providers.anthropic import AnthropicConfig, AnthropicProvider
from kairo_harness.providers.base import ModelProvider
from kairo_harness.providers.gemini import GeminiConfig, GeminiProvider
from kairo_harness.providers.ollama import OllamaConfig, OllamaProvider
from kairo_harness.providers.openai import OpenAIConfig, OpenAIProvider
from kairo_harness.tools import RegistryToolExecutor, Tool, ToolRegistry
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from support import make_config, make_tool

ProviderName = Literal["openai", "anthropic", "gemini", "ollama"]
PROVIDER_NAMES: tuple[ProviderName, ...] = ("openai", "anthropic", "gemini", "ollama")
PROVIDER_MODELS: dict[ProviderName, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5",
    "gemini": "gemini-2.5-flash",
    "ollama": "gemma3:270m",
}
BASE_URL = "http://ollama.test:11434"


@dataclass
class ProviderStub:
    name: ProviderName
    provider: ModelProvider
    payloads: list[dict[str, Any]]


class _OpenAICompletions:
    def __init__(
        self,
        responses: list[Any],
        streams: list[list[Any]],
        payloads: list[dict[str, Any]],
    ) -> None:
        self.responses = responses
        self.streams = streams
        self.payloads = payloads

    async def create(self, **kwargs: Any) -> Any:
        self.payloads.append(kwargs)
        if kwargs.get("stream"):
            return self._stream(self.streams.pop(0))
        return self.responses.pop(0)

    async def _stream(self, chunks: Sequence[Any]) -> Any:
        for chunk in chunks:
            yield chunk


class _OpenAIClient:
    def __init__(
        self,
        responses: Sequence[Any],
        streams: Sequence[Sequence[Any]],
        payloads: list[dict[str, Any]],
    ) -> None:
        self.chat = SimpleNamespace(
            completions=_OpenAICompletions(list(responses), [list(s) for s in streams], payloads)
        )


class _AnthropicMessages:
    def __init__(
        self,
        responses: list[Any],
        streams: list[list[Any]],
        payloads: list[dict[str, Any]],
    ) -> None:
        self.responses = responses
        self.streams = streams
        self.payloads = payloads

    async def create(self, **kwargs: Any) -> Any:
        self.payloads.append(kwargs)
        if kwargs.get("stream"):
            return self._stream(self.streams.pop(0))
        return self.responses.pop(0)

    async def _stream(self, events: Sequence[Any]) -> Any:
        for event in events:
            yield event


class _AnthropicClient:
    def __init__(
        self,
        responses: Sequence[Any],
        streams: Sequence[Sequence[Any]],
        payloads: list[dict[str, Any]],
    ) -> None:
        self.messages = _AnthropicMessages(list(responses), [list(s) for s in streams], payloads)


class _GeminiModels:
    def __init__(
        self,
        responses: list[Any],
        streams: list[list[Any]],
        payloads: list[dict[str, Any]],
    ) -> None:
        self.responses = responses
        self.streams = streams
        self.payloads = payloads

    async def generate_content(self, **kwargs: Any) -> Any:
        self.payloads.append(kwargs)
        return self.responses.pop(0)

    def generate_content_stream(self, **kwargs: Any) -> Any:
        self.payloads.append(kwargs)
        return self._stream(self.streams.pop(0))

    async def _stream(self, responses: Sequence[Any]) -> Any:
        for response in responses:
            yield response


class _GeminiClient:
    def __init__(
        self,
        responses: Sequence[Any],
        streams: Sequence[Sequence[Any]],
        payloads: list[dict[str, Any]],
    ) -> None:
        self.aio = SimpleNamespace(
            models=_GeminiModels(list(responses), [list(s) for s in streams], payloads)
        )

    def close(self) -> None:
        return None


class _OllamaTransport:
    def __init__(
        self,
        responses: list[dict[str, Any]],
        streams: list[list[str]],
        payloads: list[dict[str, Any]],
    ) -> None:
        self.responses = responses
        self.streams = streams
        self.payloads = payloads

    def __call__(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.payloads.append(payload)
        if payload.get("stream"):
            return httpx.Response(200, text="\n".join(self.streams.pop(0)))
        return httpx.Response(200, json=self.responses.pop(0))


def make_stub(
    name: ProviderName,
    *,
    responses: Sequence[Any] = (),
    streams: Sequence[Sequence[Any]] = (),
    config: Any = None,
) -> ProviderStub:
    payloads: list[dict[str, Any]] = []
    if name == "openai":
        client = _OpenAIClient(responses, streams, payloads)
        settings = config or OpenAIConfig(api_key_env="KAIRO_TEST_OPENAI_KEY")
        provider = OpenAIProvider(settings, client=client)
    elif name == "anthropic":
        client = _AnthropicClient(responses, streams, payloads)
        settings = config or AnthropicConfig(api_key_env="KAIRO_TEST_ANTHROPIC_KEY")
        provider = AnthropicProvider(settings, client=client)
    elif name == "gemini":
        client = _GeminiClient(responses, streams, payloads)
        settings = config or GeminiConfig(api_key_env="KAIRO_TEST_GEMINI_KEY")
        provider = GeminiProvider(settings, client=client)
    else:
        transport = _OllamaTransport(list(responses), [list(s) for s in streams], payloads)
        client = httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(transport))
        settings = config or OllamaConfig(base_url=BASE_URL)
        provider = OllamaProvider(settings, client=client)
    return ProviderStub(name, provider, payloads)


def call_spec(
    call_id: str | None,
    name: str,
    arguments: Any,
) -> dict[str, Any]:
    return {"id": call_id, "name": name, "arguments": arguments}


def openai_completion(
    content: str = "",
    calls: Sequence[dict[str, Any]] = (),
    *,
    finish_reason: str | None = None,
) -> ChatCompletion:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"]
                    if isinstance(call["arguments"], str)
                    else json.dumps(call["arguments"]),
                },
            }
            for call in calls
        ]
    payload: dict[str, Any] = {
        "id": "completion-1",
        "object": "chat.completion",
        "created": 1,
        "model": PROVIDER_MODELS["openai"],
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason or ("tool_calls" if calls else "stop"),
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }
    return ChatCompletion.model_validate(payload)


def openai_stream(
    content: str = "",
    calls: Sequence[dict[str, Any]] = (),
) -> list[ChatCompletionChunk]:
    chunks: list[ChatCompletionChunk] = []
    for index, call in enumerate(calls):
        arguments = call["arguments"]
        arguments = arguments if isinstance(arguments, str) else json.dumps(arguments)
        middle = max(1, len(arguments) // 2)
        chunks.append(
            ChatCompletionChunk.model_validate(
                {
                    "id": f"chunk-{index}-a",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": PROVIDER_MODELS["openai"],
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": index,
                                        "id": call["id"],
                                        "type": "function",
                                        "function": {
                                            "name": call["name"],
                                            "arguments": arguments[:middle],
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )
        )
        chunks.append(
            ChatCompletionChunk.model_validate(
                {
                    "id": f"chunk-{index}-b",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": PROVIDER_MODELS["openai"],
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": index,
                                        "type": "function",
                                        "function": {"arguments": arguments[middle:]},
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )
        )
    chunks.append(
        ChatCompletionChunk.model_validate(
            {
                "id": "chunk-final",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": PROVIDER_MODELS["openai"],
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": content} if content else {},
                        "finish_reason": "tool_calls" if calls else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
        )
    )
    return chunks


def anthropic_message(
    content: str = "",
    calls: Sequence[dict[str, Any]] = (),
    *,
    stop_reason: str | None = None,
) -> Message:
    blocks: list[dict[str, Any]] = []
    if content:
        blocks.append({"type": "text", "text": content})
    for call in calls:
        blocks.append(
            {
                "type": "tool_use",
                "id": call["id"],
                "name": call["name"],
                "input": call["arguments"],
            }
        )
    payload: dict[str, Any] = {
        "id": "message-1",
        "type": "message",
        "role": "assistant",
        "model": PROVIDER_MODELS["anthropic"],
        "content": blocks,
        "stop_reason": stop_reason or ("tool_use" if calls else "end_turn"),
        "stop_sequence": None,
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }
    return Message.model_validate(payload)


def anthropic_stream(
    content: str = "",
    calls: Sequence[dict[str, Any]] = (),
) -> list[Any]:
    events: list[Any] = []
    events.append(
        RawMessageStartEvent.model_validate(
            {
                "type": "message_start",
                "message": {
                    "id": "message-1",
                    "type": "message",
                    "role": "assistant",
                    "model": PROVIDER_MODELS["anthropic"],
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 3, "output_tokens": 0},
                },
            }
        )
    )
    for index, call in enumerate(calls):
        events.append(
            RawContentBlockStartEvent.model_validate(
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["name"],
                        "input": {},
                    },
                }
            )
        )
        arguments = call["arguments"]
        arguments = arguments if isinstance(arguments, str) else json.dumps(arguments)
        middle = max(1, len(arguments) // 2)
        for fragment in (arguments[:middle], arguments[middle:]):
            events.append(
                RawContentBlockDeltaEvent.model_validate(
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "input_json_delta", "partial_json": fragment},
                    }
                )
            )
    if content:
        events.append(
            RawContentBlockDeltaEvent.model_validate(
                {
                    "type": "content_block_delta",
                    "index": len(calls),
                    "delta": {"type": "text_delta", "text": content},
                }
            )
        )
    events.append(
        RawMessageDeltaEvent.model_validate(
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": "tool_use" if calls else "end_turn",
                    "stop_sequence": None,
                },
                "usage": {"output_tokens": 2},
            }
        )
    )
    events.append(RawMessageStopEvent.model_validate({"type": "message_stop"}))
    return events


def gemini_response(
    content: str = "",
    calls: Sequence[dict[str, Any]] = (),
    *,
    finish_reason: str = "STOP",
) -> Any:
    parts: list[dict[str, Any]] = []
    if content:
        parts.append({"text": content})
    for index, call in enumerate(calls):
        function_call: dict[str, Any] = {
            "id": call["id"] or f"gemini-call-{index}",
            "name": call["name"],
            "args": call["arguments"],
        }
        parts.append({"function_call": function_call})
    return types.GenerateContentResponse.model_validate(
        {
            "candidates": [
                {
                    "content": {"role": "model", "parts": parts},
                    "finish_reason": finish_reason,
                }
            ],
            "usage_metadata": {
                "prompt_token_count": 3,
                "candidates_token_count": 2,
                "total_token_count": 5,
            },
        }
    )


def ollama_response(content: str = "", calls: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [
            {
                "id": call["id"] or f"ollama-call-{index}",
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"]
                    if isinstance(call["arguments"], str)
                    else json.dumps(call["arguments"]),
                },
            }
            for index, call in enumerate(calls)
        ]
    return {
        "message": message,
        "done_reason": "tool_calls" if calls else "stop",
        "prompt_eval_count": 3,
        "eval_count": 2,
    }


def ollama_stream(
    content: str = "",
    calls: Sequence[dict[str, Any]] = (),
) -> list[str]:
    message: dict[str, Any] = {"content": content}
    if calls:
        message["tool_calls"] = [
            {
                "id": call["id"] or f"ollama-call-{index}",
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"]
                    if isinstance(call["arguments"], str)
                    else json.dumps(call["arguments"]),
                },
            }
            for index, call in enumerate(calls)
        ]
    return [
        json.dumps(
            {
                "message": message,
                "done": True,
                "done_reason": "tool_calls" if calls else "stop",
                "prompt_eval_count": 3,
                "eval_count": 2,
            }
        )
    ]


def build_response(
    name: ProviderName,
    *,
    content: str = "",
    calls: Sequence[dict[str, Any]] = (),
) -> Any:
    if name == "openai":
        return openai_completion(content, calls)
    if name == "anthropic":
        return anthropic_message(content, calls)
    if name == "gemini":
        return gemini_response(content, calls)
    return ollama_response(content, calls)


def build_stream(
    name: ProviderName,
    *,
    content: str = "",
    calls: Sequence[dict[str, Any]] = (),
) -> Sequence[Any]:
    if name == "openai":
        return openai_stream(content, calls)
    if name == "anthropic":
        return anthropic_stream(content, calls)
    if name == "gemini":
        return [gemini_response(content, calls)]
    return ollama_stream(content, calls)


def make_request(name: ProviderName, tools: Sequence[ToolSpec]) -> ModelRequest:
    return ModelRequest(
        request_id="request-1",
        model=PROVIDER_MODELS[name],
        messages=[
            ModelMessage(role=ModelRole.SYSTEM, content="system"),
            ModelMessage(role=ModelRole.USER, content="echo hi"),
        ],
        tools=list(tools),
    )


def echo_handler(arguments: dict[str, Any]) -> str:
    return json.dumps({"echo": arguments.get("value")})


def recording_handler(invoked: list[dict[str, Any]]) -> Any:
    def handler(arguments: dict[str, Any]) -> str:
        invoked.append(arguments)
        return echo_handler(arguments)

    return handler


def make_registry(
    specs: Sequence[ToolSpec],
    handler: Any = echo_handler,
) -> ToolRegistry:
    return ToolRegistry([Tool(spec, handler) for spec in specs])


def make_runner(
    stub: ProviderStub,
    *,
    specs: Sequence[ToolSpec],
    handler: Any = echo_handler,
    granted_permissions: frozenset[str] = frozenset(),
    stream: bool = False,
    sink: InMemoryEventSink | None = None,
) -> ExecutionRunner:
    registry = make_registry(specs, handler)
    config = make_config(
        provider=stub.name,
        model=PROVIDER_MODELS[stub.name],
        tools=list(specs),
        granted_permissions=granted_permissions,
        stream_responses=stream,
        max_iterations=4,
        max_model_requests=4,
        max_tool_calls=4,
    )
    executor = RegistryToolExecutor(registry, granted_permissions)
    return ExecutionRunner(config, stub.provider, executor, sink)


def events_of(sink: InMemoryEventSink, event_type: str) -> list[EventEnvelope]:
    return [event for event in sink.events if event.type == event_type]


def assert_tool_declarations(name: ProviderName, payload: dict[str, Any]) -> None:
    if name == "openai":
        declarations = [tool["function"] for tool in payload["tools"]]
        schema_key = "parameters"
    elif name == "anthropic":
        declarations = payload["tools"]
        schema_key = "input_schema"
    elif name == "gemini":
        declarations = [
            declaration
            for tool in payload["config"].tools
            for declaration in tool.function_declarations
        ]
        schema_key = "parameters"
    else:
        declarations = [tool["function"] for tool in payload["tools"]]
        schema_key = "parameters"

    names = {
        getattr(declaration, "name", None) or declaration["name"] for declaration in declarations
    }
    assert names == {"echo", "echo_two"}
    for declaration in declarations:
        description = getattr(declaration, "description", None) or declaration["description"]
        schema = getattr(declaration, schema_key, None) or declaration[schema_key]
        if hasattr(schema, "properties"):
            schema = schema.model_dump(exclude_none=True)
        schema_type = getattr(schema["type"], "value", schema["type"])
        value_type = schema["properties"]["value"]["type"]
        value_type = getattr(value_type, "value", value_type)
        assert description == "Echo a value"
        assert str(schema_type).lower() == "object"
        assert str(value_type).lower() == "string"


def assert_follow_up(
    name: ProviderName,
    payload: dict[str, Any],
    call_ids: Sequence[str],
    *,
    expected_contents: Sequence[str],
    expected_names: Sequence[str],
) -> None:
    if name == "openai":
        tool_messages = [
            message for message in payload["messages"] if message.get("role") == "tool"
        ]
        assert [message["tool_call_id"] for message in tool_messages] == list(call_ids)
        assert [message["content"] for message in tool_messages] == list(expected_contents)
        assistant_calls = [
            call for message in payload["messages"] for call in message.get("tool_calls", [])
        ]
        assert [call["id"] for call in assistant_calls] == list(call_ids)
    elif name == "anthropic":
        results = [
            block
            for message in payload["messages"]
            for block in message.get("content", [])
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        assert [block["tool_use_id"] for block in results] == list(call_ids)
        assert [block["content"] for block in results] == list(expected_contents)
        tool_uses = [
            block
            for message in payload["messages"]
            for block in message.get("content", [])
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
        assert [block["id"] for block in tool_uses] == list(call_ids)
    elif name == "gemini":
        responses = [
            part.function_response
            for content in payload["contents"]
            for part in content.parts
            if part.function_response is not None
        ]
        assert [response.id for response in responses] == list(call_ids)
        assert [response.name for response in responses] == list(expected_names)
        assert [response.response for response in responses] == [
            {"output": content} for content in expected_contents
        ]
        calls = [
            part.function_call
            for content in payload["contents"]
            for part in content.parts
            if part.function_call is not None
        ]
        assert [call.id for call in calls] == list(call_ids)
    else:
        tool_messages = [
            message for message in payload["messages"] if message.get("role") == "tool"
        ]
        assert [message["tool_name"] for message in tool_messages] == list(expected_names)
        assert [message["content"] for message in tool_messages] == list(expected_contents)
        assistant_calls = [
            call for message in payload["messages"] for call in message.get("tool_calls", [])
        ]
        assert [call["id"] for call in assistant_calls] == list(call_ids)


@pytest.mark.parametrize("name", PROVIDER_NAMES)
def test_adapter_complete_normalizes_multiple_tool_calls_and_schemas(name: ProviderName) -> None:
    calls = [
        call_spec("call-a" if name in {"openai", "anthropic"} else None, "echo", {"value": "one"}),
        call_spec(
            "call-b" if name in {"openai", "anthropic"} else None, "echo_two", {"value": "two"}
        ),
    ]
    stub = make_stub(name, responses=[build_response(name, calls=calls)])
    specs = [make_tool("echo"), make_tool("echo_two")]

    result = asyncio.run(stub.provider.complete(make_request(name, specs)))

    assert result.finish_reason == FinishReason.TOOL_CALL
    assert all(isinstance(call, ToolCallRequest) for call in result.tool_calls)
    assert [(call.name, call.arguments) for call in result.tool_calls] == [
        ("echo", {"value": "one"}),
        ("echo_two", {"value": "two"}),
    ]
    assert [call.id for call in result.tool_calls] == [
        "call-a" if name in {"openai", "anthropic"} else result.tool_calls[0].id,
        "call-b" if name in {"openai", "anthropic"} else result.tool_calls[1].id,
    ]
    if name in {"gemini", "ollama"}:
        assert result.tool_calls[0].id != result.tool_calls[1].id
    assert_tool_declarations(name, stub.payloads[0])


def malformed_response(name: ProviderName) -> Any:
    if name == "anthropic":
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id="call-a",
                    name="echo",
                    input=["not-an-object"],
                )
            ],
            stop_reason="tool_use",
            usage=None,
        )
    if name == "gemini":
        part = SimpleNamespace(
            text=None,
            function_call=SimpleNamespace(
                id="call-a",
                name="echo",
                args=["not-an-object"],
            ),
        )
        return SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(parts=[part]),
                    finish_reason=types.FinishReason.STOP,
                )
            ],
            usage_metadata=None,
        )
    calls = [call_spec("call-a", "echo", "{not-json")]
    return build_response(name, calls=calls)


@pytest.mark.parametrize("name", PROVIDER_NAMES)
def test_adapter_complete_rejects_malformed_tool_arguments(name: ProviderName) -> None:
    stub = make_stub(name, responses=[malformed_response(name)])

    with pytest.raises(ProviderError) as error_info:
        asyncio.run(stub.provider.complete(make_request(name, [make_tool()])))

    assert error_info.value.code == "provider.invalid_tool_arguments"
    assert error_info.value.retryable is False


@pytest.mark.parametrize("name", PROVIDER_NAMES)
def test_runner_enforces_permissions_for_adapter_tool_calls(name: ProviderName) -> None:
    calls = [call_spec("call-a", "admin", {"value": "hi"})]
    stub = make_stub(
        name,
        responses=[
            build_response(name, calls=calls),
            build_response(name, content="done"),
        ],
    )
    sink = InMemoryEventSink()
    specs = [
        make_tool("echo"),
        make_tool("admin", required_permissions=frozenset({"admin.use"})),
    ]
    invoked: list[dict[str, Any]] = []
    runner = make_runner(stub, specs=specs, handler=invoked.append, sink=sink)

    result = asyncio.run(runner.run())

    assert result.status.value == "failed"
    assert result.error is not None
    assert result.error.code == "tool.permission_denied"
    assert invoked == []
    assert events_of(sink, EventType.TOOL_STARTED) == []
    assert events_of(sink, EventType.TOOL_COMPLETED) == []
    assert events_of(sink, EventType.TOOL_FAILED) == []
    assert len(stub.payloads) == 1


@pytest.mark.parametrize("name", PROVIDER_NAMES)
def test_adapter_complete_missing_tool_call_id_behavior(name: ProviderName) -> None:
    if name == "openai":
        raw_response: Any = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        tool_calls=[
                            SimpleNamespace(
                                id=None,
                                function=SimpleNamespace(name="echo", arguments="{}"),
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=None,
        )
    elif name == "anthropic":
        raw_response = SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", id=None, name="echo", input={"value": "hi"})],
            stop_reason="tool_use",
            usage=None,
        )
    else:
        raw_response = build_response(name, calls=[call_spec(None, "echo", {"value": "hi"})])
    stub = make_stub(name, responses=[raw_response])

    if name in {"openai", "anthropic"}:
        with pytest.raises(ProviderError) as error_info:
            asyncio.run(stub.provider.complete(make_request(name, [make_tool()])))
        assert error_info.value.code == "provider.invalid_tool_call"
        return

    result = asyncio.run(stub.provider.complete(make_request(name, [make_tool()])))

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id
    assert result.tool_calls[0].arguments == {"value": "hi"}


def test_runner_permission_snapshot_is_authoritative_for_registry_executor() -> None:
    name: ProviderName = "openai"
    spec = make_tool("echo", required_permissions=frozenset({"admin.use"}))
    stub = make_stub(
        name,
        responses=[
            build_response(name, calls=[call_spec("call-a", "echo", {"value": "hi"})]),
            build_response(name, content="done"),
        ],
    )
    sink = InMemoryEventSink()
    invoked: list[dict[str, Any]] = []
    executor = RegistryToolExecutor(
        make_registry([spec], recording_handler(invoked)),
        granted_permissions=frozenset({"admin.use"}),
    )
    config = make_config(
        provider=name,
        model=PROVIDER_MODELS[name],
        tools=[spec],
        granted_permissions=frozenset(),
    )
    runner = ExecutionRunner(config, stub.provider, executor, sink)

    result = asyncio.run(runner.run())

    assert result.status.value == "failed"
    assert result.error is not None
    assert result.error.code == "tool.permission_denied"
    assert invoked == []
    assert events_of(sink, EventType.TOOL_STARTED) == []
    assert events_of(sink, EventType.TOOL_FAILED) == []
    assert events_of(sink, EventType.EXECUTION_FAILED)
    assert len(stub.payloads) == 1


@pytest.mark.parametrize("name", PROVIDER_NAMES)
def test_runner_executes_multiple_adapter_tool_calls_with_registry_executor(
    name: ProviderName,
) -> None:
    calls = [
        call_spec("call-a" if name in {"openai", "anthropic"} else None, "echo", {"value": "one"}),
        call_spec(
            "call-b" if name in {"openai", "anthropic"} else None, "echo_two", {"value": "two"}
        ),
    ]
    stub = make_stub(
        name,
        responses=[
            build_response(name, calls=calls),
            build_response(name, content="done"),
        ],
    )
    sink = InMemoryEventSink()
    invoked: list[dict[str, Any]] = []
    specs = [make_tool("echo"), make_tool("echo_two")]
    runner = make_runner(stub, specs=specs, handler=recording_handler(invoked), sink=sink)

    result = asyncio.run(runner.run())

    assert result.status.value == "completed"
    assert result.output == "done"
    assert result.state.tool_calls == 2
    assert [arguments["value"] for arguments in invoked] == ["one", "two"]
    started = events_of(sink, EventType.TOOL_STARTED)
    completed = events_of(sink, EventType.TOOL_COMPLETED)
    assert [event.payload["toolName"] for event in started] == ["echo", "echo_two"]
    assert [event.payload["toolName"] for event in completed] == ["echo", "echo_two"]
    call_ids = [event.payload["toolCallId"] for event in started]
    assert len(set(call_ids)) == 2
    assert_follow_up(
        name,
        stub.payloads[1],
        call_ids,
        expected_contents=['{"echo": "one"}', '{"echo": "two"}'],
        expected_names=["echo", "echo_two"],
    )


@pytest.mark.parametrize("name", PROVIDER_NAMES)
def test_runner_executes_streamed_adapter_tool_calls(name: ProviderName) -> None:
    calls = [
        call_spec("call-a" if name in {"openai", "anthropic"} else None, "echo", {"value": "hi"})
    ]
    stub = make_stub(
        name,
        streams=[
            build_stream(name, calls=calls),
            build_stream(name, content="done"),
        ],
    )
    sink = InMemoryEventSink()
    invoked: list[dict[str, Any]] = []
    runner = make_runner(
        stub,
        specs=[make_tool()],
        handler=recording_handler(invoked),
        stream=True,
        sink=sink,
    )

    result = asyncio.run(runner.run())

    assert result.status.value == "completed"
    assert result.output == "done"
    assert result.state.tool_calls == 1
    assert invoked == [{"value": "hi"}]
    assert events_of(sink, EventType.MODEL_STREAM_CHUNK)
    started = events_of(sink, EventType.TOOL_STARTED)
    completed = events_of(sink, EventType.TOOL_COMPLETED)
    assert len(started) == 1
    assert completed[0].causationId == started[0].eventId
    call_id = started[0].payload["toolCallId"]
    assert_follow_up(
        name,
        stub.payloads[1],
        [call_id],
        expected_contents=['{"echo": "hi"}'],
        expected_names=["echo"],
    )


@pytest.mark.parametrize("name", PROVIDER_NAMES)
def test_runner_observes_adapter_originated_handler_error_safely(name: ProviderName) -> None:
    calls = [call_spec("call-a", "echo", {"value": "hi"})]
    stub = make_stub(
        name,
        responses=[
            build_response(name, calls=calls),
            build_response(name, content="done"),
        ],
    )
    sink = InMemoryEventSink()

    def failing_handler(arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("SECRET_HANDLER_DETAIL")

    runner = make_runner(stub, specs=[make_tool()], handler=failing_handler, sink=sink)

    result = asyncio.run(runner.run())

    assert result.status.value == "completed"
    failed = events_of(sink, EventType.TOOL_FAILED)
    assert len(failed) == 1
    assert failed[0].payload["error"]["code"] == "tool.unexpected"
    assert failed[0].payload["error"]["message"] == "Tool execution failed"
    assert "SECRET_HANDLER_DETAIL" not in str([event.model_dump() for event in sink.events])
    call_id = failed[0].payload["toolCallId"]
    assert_follow_up(
        name,
        stub.payloads[1],
        [call_id],
        expected_contents=["Tool failed (tool.unexpected): Tool execution failed"],
        expected_names=["echo"],
    )


@pytest.mark.parametrize("name", PROVIDER_NAMES)
def test_runner_observes_adapter_originated_timeout_safely(name: ProviderName) -> None:
    calls = [call_spec("call-a", "echo", {"value": "hi"})]
    stub = make_stub(
        name,
        responses=[
            build_response(name, calls=calls),
            build_response(name, content="done"),
        ],
    )
    sink = InMemoryEventSink()
    spec = make_tool()
    spec.timeout_seconds = 0.01

    async def slow_handler(arguments: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return {"echo": arguments.get("value")}

    runner = make_runner(stub, specs=[spec], handler=slow_handler, sink=sink)

    result = asyncio.run(runner.run())

    assert result.status.value == "completed"
    failed = events_of(sink, EventType.TOOL_FAILED)
    assert len(failed) == 1
    assert failed[0].payload["error"]["code"] == "tool.timeout"
    assert failed[0].payload["error"]["retryable"] is True
    call_id = failed[0].payload["toolCallId"]
    assert_follow_up(
        name,
        stub.payloads[1],
        [call_id],
        expected_contents=["Tool failed (tool.timeout): Tool execution timed out"],
        expected_names=["echo"],
    )


@pytest.mark.parametrize("name", PROVIDER_NAMES)
def test_adapter_capability_override_blocks_tool_requests(name: ProviderName) -> None:
    config: Any
    if name == "openai":
        config = OpenAIConfig(
            api_key_env="KAIRO_TEST_OPENAI_KEY",
            model_capabilities={
                PROVIDER_MODELS[name]: ModelCapabilities(streaming=True, tool_calls=False)
            },
        )
    elif name == "anthropic":
        config = AnthropicConfig(
            api_key_env="KAIRO_TEST_ANTHROPIC_KEY",
            model_capabilities={
                PROVIDER_MODELS[name]: ModelCapabilities(streaming=True, tool_calls=False)
            },
        )
    elif name == "gemini":
        config = GeminiConfig(
            api_key_env="KAIRO_TEST_GEMINI_KEY",
            model_capabilities={
                PROVIDER_MODELS[name]: ModelCapabilities(streaming=True, tool_calls=False)
            },
        )
    else:
        config = OllamaConfig(
            base_url=BASE_URL,
            model_capabilities={
                PROVIDER_MODELS[name]: ModelCapabilities(streaming=True, tool_calls=False)
            },
        )
    stub = make_stub(name, config=config)
    request = make_request(name, [make_tool()])

    with pytest.raises(ConfigError) as error_info:
        asyncio.run(stub.provider.complete(request))
    assert error_info.value.code == "provider.capability_unsupported"

    async def collect() -> None:
        async for _ in stub.provider.stream(request):
            pass

    with pytest.raises(ConfigError):
        asyncio.run(collect())
    assert stub.payloads == []


def test_runner_capability_gate_blocks_tools_before_provider_request() -> None:
    config = OpenAIConfig(
        api_key_env="KAIRO_TEST_OPENAI_KEY",
        model_capabilities={
            PROVIDER_MODELS["openai"]: ModelCapabilities(streaming=True, tool_calls=False)
        },
    )
    stub = make_stub("openai", config=config)
    sink = InMemoryEventSink()
    runner = make_runner(stub, specs=[make_tool()], sink=sink)

    result = asyncio.run(runner.run())

    assert result.status.value == "failed"
    assert result.error is not None
    assert result.error.code == "provider.capability_unsupported"
    assert stub.payloads == []
    assert events_of(sink, EventType.TOOL_STARTED) == []


def test_core_tool_modules_do_not_import_provider_sdks() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "kairo_harness"
    forbidden = ("openai", "anthropic", "google.genai", "genai", "httpx")
    for name in ("execution.py", "tools.py"):
        source = (root / name).read_text(encoding="utf-8")
        for module in forbidden:
            assert f"import {module}" not in source
            assert f"from {module}" not in source


def test_provider_stub_responses_are_domain_models() -> None:
    stub = make_stub(
        "openai",
        responses=[build_response("openai", calls=[call_spec("call-a", "echo", {"value": "hi"})])],
    )
    result = asyncio.run(stub.provider.complete(make_request("openai", [make_tool()])))
    call = result.tool_calls[0]

    assert isinstance(call, ToolCallRequest)
    assert call.id == "call-a"
    assert call.name == "echo"
    assert call.arguments == {"value": "hi"}


def test_multiple_tool_calls_share_model_response_causation() -> None:
    name: ProviderName = "gemini"
    calls = [
        call_spec(None, "echo", {"value": "one"}),
        call_spec(None, "echo_two", {"value": "two"}),
    ]
    stub = make_stub(
        name,
        responses=[
            build_response(name, calls=calls),
            build_response(name, content="done"),
        ],
    )
    sink = InMemoryEventSink()
    runner = make_runner(stub, specs=[make_tool("echo"), make_tool("echo_two")], sink=sink)

    result = asyncio.run(runner.run())

    assert result.status.value == "completed"
    responded = events_of(sink, EventType.MODEL_RESPONDED)
    started = events_of(sink, EventType.TOOL_STARTED)
    assert [event.payload["toolNames"] for event in responded] == [
        ["echo", "echo_two"],
        [],
    ]
    assert all(event.causationId == responded[0].eventId for event in started)
