from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel, ConfigDict

type EnvelopeKind = Literal["message-envelope", "event-envelope"]

CONTRACT_SCHEMA_VERSION = "1.0.0"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _find_contracts_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        root = candidate / "packages" / "contracts"
        if (root / "schemas" / "v1").is_dir():
            return root
    raise FileNotFoundError("Could not locate packages/contracts from the harness package")


CONTRACTS_ROOT = _find_contracts_root(Path(__file__).resolve())
SCHEMAS_ROOT = CONTRACTS_ROOT / "schemas" / "v1"


@dataclass(frozen=True)
class ValidationIssue:
    keyword: str
    instance_path: str
    schema_path: str
    message: str


class ContractValidationError(ValueError):
    def __init__(self, kind: EnvelopeKind, issues: tuple[ValidationIssue, ...]) -> None:
        super().__init__(f"{kind} validation failed with {len(issues)} issue(s)")
        self.kind = kind
        self.issues = issues


def _json_pointer(parts: Any) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _load_schema(kind: EnvelopeKind) -> dict[str, Any]:
    path = SCHEMAS_ROOT / f"{kind}.schema.json"
    with path.open(encoding="utf-8") as stream:
        schema = json.load(stream)
    if not isinstance(schema, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return schema


VALIDATORS: dict[EnvelopeKind, Draft202012Validator] = {
    kind: Draft202012Validator(_load_schema(kind))
    for kind in ("message-envelope", "event-envelope")
}


def _to_issue(error: ValidationError) -> ValidationIssue:
    return ValidationIssue(
        keyword=error.validator or "unknown",
        instance_path=_json_pointer(error.absolute_path),
        schema_path="#" + _json_pointer(error.absolute_schema_path),
        message=error.message,
    )


def validate_envelope(kind: EnvelopeKind, value: object) -> dict[str, Any]:
    errors = sorted(
        VALIDATORS[kind].iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ContractValidationError(kind, tuple(_to_issue(error) for error in errors))
    if not isinstance(value, dict):
        raise TypeError(f"{kind} schema requires an object")
    return value


class Participant(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    kind: str


class Source(BaseModel):
    model_config = ConfigDict(extra="ignore")

    component: str
    instanceId: str | None = None


class MessageEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messageId: str
    type: str
    schemaVersion: str
    createdAt: str
    correlationId: str | None = None
    causationId: str | None = None
    sender: Participant | None = None
    recipient: Participant | None = None
    payload: dict[str, Any]


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    eventId: str
    type: str
    schemaVersion: str
    occurredAt: str
    correlationId: str | None = None
    causationId: str | None = None
    source: Source
    payload: dict[str, Any]


def to_message_envelope(value: object) -> MessageEnvelope:
    return MessageEnvelope.model_validate(validate_envelope("message-envelope", value))


def to_event_envelope(value: object) -> EventEnvelope:
    return EventEnvelope.model_validate(validate_envelope("event-envelope", value))
