from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from kairo_harness.contracts import (
    CONTRACT_SCHEMA_VERSION,
    EventEnvelope,
    Source,
    to_event_envelope,
)
from kairo_harness.errors import ConfigError

MAX_PAYLOAD_STRING_LENGTH = 4096
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "authorization",
    "credential",
    "privatekey",
    "accesskey",
    "prompt",
    "messages",
    "systemprompt",
    "task",
)
_BEARER_TOKEN = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


class EventType:
    EXECUTION_STARTED = "execution.started"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    EXECUTION_CANCELLED = "execution.cancelled"
    MODEL_REQUESTED = "model.requested"
    MODEL_RESPONDED = "model.responded"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"


class EventSink(ABC):
    @abstractmethod
    async def emit(self, event: EventEnvelope) -> None: ...


class InMemoryEventSink(EventSink):
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    async def emit(self, event: EventEnvelope) -> None:
        self.events.append(event)


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(str(key)) else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        redacted = _BEARER_TOKEN.sub("[REDACTED]", value)
        if len(redacted) > MAX_PAYLOAD_STRING_LENGTH:
            return redacted[:MAX_PAYLOAD_STRING_LENGTH] + "...[TRUNCATED]"
        return redacted
    return value


class EventEmitter:
    def __init__(
        self,
        *,
        execution_id: UUID,
        correlation_id: UUID,
        sink: EventSink,
        instance_id: str | None = None,
    ) -> None:
        if not execution_id:
            raise ConfigError("execution_id is required")
        self.execution_id = execution_id
        self.correlation_id = correlation_id
        self.sink = sink
        self.instance_id = instance_id or str(execution_id)

    async def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        causation_id: str | None = None,
    ) -> str:
        event = EventEnvelope(
            eventId=str(uuid4()),
            type=event_type,
            schemaVersion=CONTRACT_SCHEMA_VERSION,
            occurredAt=datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            correlationId=str(self.correlation_id),
            causationId=causation_id,
            source=Source(component="kairo-harness", instanceId=self.instance_id),
            payload=redact_payload(payload),
        )
        envelope = to_event_envelope(event.model_dump(mode="json", exclude_none=True))
        await self.sink.emit(envelope)
        return envelope.eventId
