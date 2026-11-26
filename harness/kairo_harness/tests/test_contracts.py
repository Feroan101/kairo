import json
from typing import Any

import pytest
from kairo_harness.contracts import (
    CONTRACT_SCHEMA_VERSION,
    CONTRACTS_ROOT,
    JSON_SCHEMA_DIALECT,
    SCHEMAS_ROOT,
    VALIDATORS,
    ContractValidationError,
    to_event_envelope,
    to_message_envelope,
    validate_envelope,
)

FIXTURES_ROOT = CONTRACTS_ROOT / "fixtures" / "v1"

FIXTURE_FILES = [
    ("message-envelope", "message-envelope.json"),
    ("event-envelope", "event-envelope.json"),
]


def load_fixtures(filename: str) -> dict[str, Any]:
    with (FIXTURES_ROOT / filename).open(encoding="utf-8") as stream:
        fixtures = json.load(stream)
    if not isinstance(fixtures, dict):
        raise TypeError(f"{filename} must contain a JSON object")
    return fixtures


def test_contract_paths_point_at_versioned_contract_files() -> None:
    assert (SCHEMAS_ROOT / "message-envelope.schema.json").is_file()
    assert (SCHEMAS_ROOT / "event-envelope.schema.json").is_file()
    assert (FIXTURES_ROOT / "message-envelope.json").is_file()
    assert (FIXTURES_ROOT / "event-envelope.json").is_file()


def test_schemas_use_json_schema_draft_2020_12() -> None:
    for validator in VALIDATORS.values():
        assert validator.schema["$schema"] == JSON_SCHEMA_DIALECT


@pytest.mark.parametrize(("kind", "filename"), FIXTURE_FILES)
def test_valid_fixtures_pass(kind: str, filename: str) -> None:
    fixtures = load_fixtures(filename)
    assert fixtures["schemaVersion"] == CONTRACT_SCHEMA_VERSION
    for case in fixtures["valid"]:
        assert validate_envelope(kind, case["value"]) == case["value"]


@pytest.mark.parametrize(("kind", "filename"), FIXTURE_FILES)
def test_invalid_fixtures_fail(kind: str, filename: str) -> None:
    fixtures = load_fixtures(filename)
    for case in fixtures["invalid"]:
        with pytest.raises(ContractValidationError) as error_info:
            validate_envelope(kind, case["value"])
        assert error_info.value.issues
        assert all(issue.keyword for issue in error_info.value.issues)


def test_pydantic_models_wrap_validated_envelopes() -> None:
    message = load_fixtures("message-envelope.json")["valid"][0]["value"]
    event = load_fixtures("event-envelope.json")["valid"][0]["value"]

    message_envelope = to_message_envelope(message)
    event_envelope = to_event_envelope(event)

    assert message_envelope.type == "agent.delegation.requested"
    assert message_envelope.payload["taskId"] == "22222222-2222-4222-8222-222222222222"
    assert event_envelope.type == "execution.started"
    assert event_envelope.source.component == "control-plane"
