from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from collections.abc import Sequence

from kairo_harness.config import ExecutionConfig, ModelConfig
from kairo_harness.domain import ModelResponse, Usage
from kairo_harness.errors import HarnessError
from kairo_harness.providers.mock import MockProvider
from kairo_harness.providers.registry import ProviderRegistry
from kairo_harness.providers.settings import ProviderSettings
from kairo_harness.standalone import StandaloneHarness

PROVIDERS = ("mock", "gemini", "anthropic", "openai", "ollama")
DEFAULT_MODELS = {"mock": "mock-model", "ollama": "gemma3:270m"}
DEFAULT_TASK = "Reply with a short confirmation that the Kairo harness is running."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kairo-harness")
    parser.add_argument("--task", help="Task text; defaults to KAIRO_TASK")
    parser.add_argument("--provider", choices=PROVIDERS, default="mock")
    parser.add_argument("--model", help="Model identifier; defaults to KAIRO_MODEL")
    parser.add_argument("--agent-id", default="standalone-agent")
    parser.add_argument("--execution-id", help="Optional execution UUID")
    parser.add_argument("--permission", action="append", default=[])
    parser.add_argument("--max-iterations", type=int, default=8)
    parser.add_argument("--max-model-requests", type=int, default=8)
    parser.add_argument("--max-tool-calls", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument(
        "--events", action="store_true", help="Print structured events as JSON lines"
    )
    parser.add_argument("--mock-response", default="Kairo harness is ready.")
    return parser


def build_config(parser: argparse.ArgumentParser, args: argparse.Namespace) -> ExecutionConfig:
    task = args.task or os.environ.get("KAIRO_TASK") or DEFAULT_TASK
    model = args.model or os.environ.get("KAIRO_MODEL") or DEFAULT_MODELS.get(args.provider)
    if not model:
        parser.error(f"--model is required for provider {args.provider}")

    execution_id = uuid.UUID(args.execution_id) if args.execution_id else uuid.uuid4()
    return ExecutionConfig(
        agent_id=args.agent_id,
        execution_id=execution_id,
        task=task,
        model=ModelConfig(
            provider=args.provider,
            model=model,
            stream_responses=args.stream,
        ),
        granted_permissions=frozenset(args.permission),
        max_iterations=args.max_iterations,
        max_model_requests=args.max_model_requests,
        max_tool_calls=args.max_tool_calls,
        timeout_seconds=args.timeout_seconds,
    )


def build_harness(args: argparse.Namespace) -> StandaloneHarness:
    if args.provider == "mock":
        provider = MockProvider(
            [
                ModelResponse(
                    content=args.mock_response,
                    usage=Usage(input_tokens=0, output_tokens=0, total_tokens=0),
                )
            ]
        )
        return StandaloneHarness(provider=provider)

    settings = ProviderSettings.from_env()
    registry = ProviderRegistry.from_settings(settings)
    return StandaloneHarness.from_registry(registry, close_registry=True)


async def execute(
    harness: StandaloneHarness,
    config: ExecutionConfig,
    *,
    print_events: bool,
) -> int:
    run = await harness.run(config)
    print(f"status={run.result.status.value}")
    if run.output is not None:
        print(f"output={run.output}")
    if run.error is not None:
        print(f"error={run.error.code}: {run.error.message}")
    usage = run.usage.model_dump(mode="json", exclude_none=True)
    if usage:
        print("usage=" + json.dumps(usage, sort_keys=True))
    if print_events:
        for event in run.events:
            print(json.dumps(event.model_dump(mode="json", exclude_none=True), sort_keys=True))
    return 0 if run.result.status.value == "completed" else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = build_config(parser, args)
    harness = build_harness(args)

    try:
        return asyncio.run(execute(harness, config, print_events=args.events))
    except HarnessError as error:
        print(f"error={error.code}: {error.message}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
