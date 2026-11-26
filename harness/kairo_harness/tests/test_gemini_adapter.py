import asyncio
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from google.genai import errors as genai_errors
from google.genai import types
from kairo_harness.config import ExecutionConfig, ModelConfig
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
from kairo_harness.execution import ExecutionRunner
from kairo_harness.providers.gemini import GeminiConfig, GeminiProvider
from support import ScriptedToolExecutor, make_config, make_tool, tool_call

MODEL = "gemini-2.5-flash"
TEST_KEY_ENV = "KAIRO_TEST_GEMINI_KEY"


class _ModelPager:
    def __init__(self, models: Sequence[Any]) -> None:
        self._models = list(models)

    def __aiter__(self) -> Any:
        return self._iterate()

    async def _iterate(self) -> Any:
        for model in self._models:
            yield model


class FakeAsyncModels:
    def __init__(
        self,
        responses: Sequence[Any] = (),
        streams: Sequence[Sequence[Any]] = (),
        models: Sequence[Any] = (),
    ) -> None:
        self._responses = list(responses)
        self._streams = [list(stream) for stream in streams]
        self._models = list(models)
        self.complete_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> Any:
        self.complete_calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def generate_content_stream(self, **kwargs: Any) -> Any:
        self.stream_calls.append(kwargs)
        return self._stream()

    async def _stream(self) -> Any:
        for response in self._streams.pop(0):
            yield response

    async def list(self) -> Any:
        return _ModelPager(self._models)


class FakeGeminiClient:
    def __init__(
        self,
        responses: Sequence[Any] = (),
        streams: Sequence[Sequence[Any]] = (),
        models: Sequence[Any] = (),
    ) -> None:
        self.models_api = FakeAsyncModels(responses, streams, models)
        self.aio = SimpleNamespace(models=self.models_api)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def provider_for(
    responses: Sequence[Any] = (),
    streams: Sequence[Sequence[Any]] = (),
    models: Sequence[Any] = (),
    config: GeminiConfig | None = None,
) -> tuple[GeminiProvider, FakeGeminiClient]:
    client = FakeGeminiClient(responses, streams, models)
    settings = config or GeminiConfig(api_key_env=TEST_KEY_ENV)
    return GeminiProvider(settings, client=client), client


def response(
    text: str = "",
    function_calls: Sequence[dict[str, Any]] = (),
    *,
    finish_reason: str | None = "STOP",
    usage: dict[str, int] | None = None,
) -> Any:
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"text": text})
    parts.extend({"function_call": dict(call)} for call in function_calls)
    candidate: dict[str, Any] = {"content": {"role": "model", "parts": parts}}
    if finish_reason is not None:
        candidate["finish_reason"] = finish_reason
    payload: dict[str, Any] = {"candidates": [candidate]}
    if usage:
        payload["usage_metadata"] = usage
    return types.GenerateContentResponse.model_validate(payload)


def make_request() -> ModelRequest:
    return ModelRequest(
        request_id="request-1",
        model=MODEL,
        messages=[
            ModelMessage(role=ModelRole.SYSTEM, content="system"),
            ModelMessage(role=ModelRole.USER, content="hello"),
        ],
    )


def test_complete_normalizes_gemini_response_and_payload() -> None:
    provider, client = provider_for(
        [
            response(
                "hello",
                usage={
                    "prompt_token_count": 4,
                    "candidates_token_count": 2,
                    "total_token_count": 6,
                },
            )
        ]
    )

    result = asyncio.run(provider.complete(make_request()))

    assert result.content == "hello"
    assert result.usage == Usage(input_tokens=4, output_tokens=2, total_tokens=6)
    assert result.finish_reason == FinishReason.STOP
    call = client.models_api.complete_calls[0]
    assert call["model"] == MODEL
    assert call["contents"][0].role == "user"
    assert call["contents"][0].parts[0].text == "hello"
    config = call["config"]
    assert config.system_instruction == "system"
    assert config.automatic_function_calling.disable is True
    assert config.max_output_tokens is None


def test_complete_normalizes_native_function_call_and_follow_up_messages() -> None:
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
        [response(function_calls=[{"id": "call-2", "name": "echo", "args": {"value": "bye"}}])]
    )

    result = asyncio.run(provider.complete(request))

    assert result.finish_reason == FinishReason.TOOL_CALL
    assert result.tool_calls[0].arguments == {"value": "bye"}
    call = client.models_api.complete_calls[0]
    config = call["config"]
    assert config.tools[0].function_declarations[0].name == "echo"
    contents = call["contents"]
    assert contents[1].role == "model"
    assert contents[1].parts[0].function_call.args == {"value": "hi"}
    assert contents[2].parts[0].function_response.id == "call-1"
    assert contents[2].parts[0].function_response.response == {"output": '{"echo": "hi"}'}


def test_stream_normalizes_function_call_arguments_and_cumulative_usage() -> None:
    responses = [
        response(
            "thinking",
            usage={
                "prompt_token_count": 3,
                "candidates_token_count": 1,
                "total_token_count": 4,
            },
        ),
        response(
            function_calls=[{"id": "call-1", "name": "echo", "args": {"value": "hi"}}],
            usage={
                "prompt_token_count": 3,
                "candidates_token_count": 3,
                "total_token_count": 6,
            },
        ),
    ]
    provider, client = provider_for(streams=[responses])

    async def scenario() -> tuple[list[Usage], ModelResponse]:
        chunks = [chunk async for chunk in provider.stream(make_request())]
        return [chunk.usage for chunk in chunks], aggregate_stream_chunks(chunks)

    chunk_usage, aggregated = asyncio.run(scenario())

    assert chunk_usage == [
        Usage(input_tokens=3, output_tokens=1, total_tokens=4),
        Usage(input_tokens=0, output_tokens=2, total_tokens=2),
    ]
    assert aggregated.content == "thinking"
    assert aggregated.finish_reason == FinishReason.TOOL_CALL
    assert aggregated.tool_calls[0].arguments == {"value": "hi"}
    assert aggregated.usage == Usage(input_tokens=3, output_tokens=3, total_tokens=6)
    assert client.models_api.stream_calls[0]["model"] == MODEL


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("STOP", FinishReason.STOP),
        ("MAX_TOKENS", FinishReason.LENGTH),
        ("SAFETY", FinishReason.INCOMPLETE),
    ],
)
def test_finish_reason_mapping(raw: str, expected: FinishReason) -> None:
    assert GeminiProvider._finish_reason(response(finish_reason=raw), False) is expected


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (genai_errors.APIError(403, {"error": {"message": "SECRET_KEY"}}), "provider.auth", False),
        (
            genai_errors.APIError(429, {"error": {"message": "SECRET_KEY"}}),
            "provider.rate_limited",
            True,
        ),
    ],
)
def test_api_errors_are_classified_without_leaking_secrets(
    error: Exception, code: str, retryable: bool
) -> None:
    provider, _ = provider_for([error])

    with pytest.raises(ProviderError) as error_info:
        asyncio.run(provider.complete(make_request()))

    assert error_info.value.code == code
    assert error_info.value.retryable is retryable
    assert "SECRET_KEY" not in str(error_info.value)
    assert "SECRET_KEY" not in str(error_info.value.details)


def test_missing_candidates_fails_safely() -> None:
    invalid = types.GenerateContentResponse.model_validate({"candidates": []})
    provider, _ = provider_for([invalid])

    with pytest.raises(ProviderError) as error_info:
        asyncio.run(provider.complete(make_request()))

    assert error_info.value.code == "provider.invalid_response"


def test_capability_override_blocks_tools_and_streaming_before_request() -> None:
    config = GeminiConfig(
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
    assert client.models_api.complete_calls == []
    assert client.models_api.stream_calls == []


async def collect_stream(provider: GeminiProvider, request: ModelRequest) -> list[Any]:
    return [chunk async for chunk in provider.stream(request)]


def test_list_models_uses_advertised_capabilities() -> None:
    models = [SimpleNamespace(name=f"models/{MODEL}", display_name="Gemini 2.5 Flash")]
    provider, _ = provider_for(models=models)

    descriptors = asyncio.run(provider.list_models())

    assert descriptors[0].id == f"models/{MODEL}"
    assert descriptors[0].name == "Gemini 2.5 Flash"
    assert descriptors[0].capabilities.tool_calls is True
    assert descriptors[0].capabilities.streaming is True


def test_credentials_are_not_part_of_model_configuration() -> None:
    config = ExecutionConfig(
        agent_id="agent-1",
        execution_id=uuid4(),
        task="hello",
        model=ModelConfig(provider="gemini", model=MODEL),
    )

    assert TEST_KEY_ENV not in str(config.model_dump())
    configured = GeminiConfig.from_env({"GEMINI_API_KEY": "secret-value"})
    assert configured is not None
    assert "secret-value" not in str(configured.model_dump())

    with pytest.raises(ConfigError):
        GeminiConfig(api_key_env="KAIRO_MISSING_KEY").api_key({})


def test_runner_uses_selected_gemini_provider_and_model() -> None:
    provider, client = provider_for(
        responses=[
            response(function_calls=[{"id": "call-1", "name": "echo", "args": {"value": "hi"}}]),
            response("done"),
        ]
    )
    config = make_config(
        provider="gemini",
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
    assert [call["model"] for call in client.models_api.complete_calls] == [MODEL, MODEL]
