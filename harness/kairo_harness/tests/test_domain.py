import json

import pytest
from kairo_harness.domain import (
    TOOL_CALL_ACTION_TYPE,
    FinalDecision,
    ModelResponse,
    ToolCallDecision,
    ToolSpec,
    Usage,
    parse_model_decision,
)
from kairo_harness.errors import InvalidModelResponseError
from support import tool_call


def test_usage_has_one_canonical_definition() -> None:
    usage = Usage(input_tokens=2, output_tokens=3, total_tokens=5)
    assert usage.model_dump(exclude_none=True) == {
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
    }


def test_parse_model_decision_treats_plain_text_as_final() -> None:
    decision = parse_model_decision(ModelResponse(content="done"))
    assert isinstance(decision, FinalDecision)
    assert decision.content == "done"


def test_native_tool_calls_take_precedence_over_json_content() -> None:
    action = {
        "type": TOOL_CALL_ACTION_TYPE,
        "tool_calls": [
            {"id": "json-call", "name": "other", "arguments": {"value": "json"}},
        ],
    }
    response = ModelResponse(
        content=json.dumps(action),
        tool_calls=[tool_call("native-call", value="native")],
    )

    decision = parse_model_decision(response)

    assert isinstance(decision, ToolCallDecision)
    assert [call.id for call in decision.tool_calls] == ["native-call"]


def test_strict_json_action_format_is_validated() -> None:
    action = {
        "type": TOOL_CALL_ACTION_TYPE,
        "tool_calls": [
            {"id": "call-1", "name": "echo", "arguments": {"value": "hello"}},
        ],
    }
    decision = parse_model_decision(ModelResponse(content=json.dumps(action)))
    assert isinstance(decision, ToolCallDecision)
    assert decision.tool_calls[0].arguments == {"value": "hello"}


def test_malformed_tool_action_fails_safely() -> None:
    action = {"type": TOOL_CALL_ACTION_TYPE, "tool_calls": [{"name": "echo"}], "extra": True}
    with pytest.raises(InvalidModelResponseError) as error_info:
        parse_model_decision(ModelResponse(content=json.dumps(action)))
    assert error_info.value.code == "model.invalid_response"


def test_empty_model_response_is_invalid() -> None:
    with pytest.raises(InvalidModelResponseError):
        parse_model_decision(ModelResponse())


def test_tool_spec_rejects_non_object_schema() -> None:
    with pytest.raises(ValueError, match="object"):
        ToolSpec(
            name="bad",
            description="Bad tool",
            input_schema={"type": "string"},
            allowed=True,
        )
