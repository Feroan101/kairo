import asyncio
from uuid import uuid4

from kairo_harness.contracts import CONTRACT_SCHEMA_VERSION
from kairo_harness.events import EventEmitter, EventType, InMemoryEventSink, redact_payload


def test_redaction_removes_sensitive_keys_and_bearer_tokens() -> None:
    payload = {
        "toolName": "echo",
        "output": {
            "password": "hunter2",
            "authorization": "Bearer abc.def-ghi",
            "safe": "visible",
        },
    }
    redacted = redact_payload(payload)
    assert redacted["output"]["password"] == "[REDACTED]"
    assert redacted["output"]["authorization"] == "[REDACTED]"
    assert redacted["output"]["safe"] == "visible"
    assert "abc.def-ghi" not in str(redacted)


def test_emitted_events_are_contract_valid_and_correlated() -> None:
    execution_id = uuid4()
    sink = InMemoryEventSink()
    emitter = EventEmitter(execution_id=execution_id, correlation_id=execution_id, sink=sink)

    async def scenario() -> str:
        first = await emitter.emit(EventType.EXECUTION_STARTED, {"executionId": str(execution_id)})
        await emitter.emit(
            EventType.MODEL_REQUESTED,
            {"requestId": "request-1", "prompt": "secret task", "api_key": "abc"},
            causation_id=first,
        )
        return first

    first_id = asyncio.run(scenario())

    assert len(sink.events) == 2
    event = sink.events[1]
    assert event.schemaVersion == CONTRACT_SCHEMA_VERSION
    assert event.source.component == "kairo-harness"
    assert event.source.instanceId == str(execution_id)
    assert event.correlationId == str(execution_id)
    assert event.causationId == first_id
    assert event.payload["api_key"] == "[REDACTED]"
    assert "secret task" not in str(event.payload)
