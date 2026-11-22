from __future__ import annotations

import asyncio
import os
import uuid

from kairo_harness.config import ExecutionConfig, ModelConfig
from kairo_harness.domain import ToolCallRequest, ToolResult, ToolSpec
from kairo_harness.errors import ToolExecutionError
from kairo_harness.events import InMemoryEventSink
from kairo_harness.execution import ExecutionRunner
from kairo_harness.providers.ollama import OllamaConfig, OllamaProvider
from kairo_harness.tools import ToolExecutor

DEFAULT_MODEL = "gemma3:270m"
DEFAULT_TASK = "Reply with a short confirmation that the Kairo harness can reach this model."


class NoToolsExecutor(ToolExecutor):
    async def execute(self, call: ToolCallRequest, spec: ToolSpec) -> ToolResult:
        raise ToolExecutionError(
            "No tools are configured for the smoke execution",
            code="tool.unavailable",
        )


async def main() -> None:
    base_url = os.environ.get("KAIRO_OLLAMA_BASE_URL")
    if not base_url:
        raise SystemExit("Set KAIRO_OLLAMA_BASE_URL to an endpoint reachable from the harness")

    model = os.environ.get("KAIRO_OLLAMA_MODEL", DEFAULT_MODEL)
    config = ExecutionConfig(
        agent_id="smoke-agent",
        execution_id=uuid.uuid4(),
        task=os.environ.get("KAIRO_TASK", DEFAULT_TASK),
        model=ModelConfig(
            provider="ollama",
            model=model,
            timeout_seconds=60.0,
        ),
        max_iterations=2,
        max_model_requests=2,
        max_tool_calls=0,
        timeout_seconds=120.0,
    )

    provider = OllamaProvider(OllamaConfig(base_url=base_url))
    sink = InMemoryEventSink()
    runner = ExecutionRunner(config, provider, NoToolsExecutor(), sink)
    try:
        result = await runner.run()
    finally:
        await provider.aclose()

    print(f"status={result.status.value}")
    print(f"output={result.output or ''}")
    if result.error is not None:
        print(f"error={result.error.code}")
    print("events=" + ",".join(event.type for event in sink.events))


if __name__ == "__main__":
    asyncio.run(main())
