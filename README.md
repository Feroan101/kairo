# Kairo

An open-source platform for building, running, and managing AI agents.

Kairo provides the infrastructure to run AI agent harnesses in isolated environments, orchestrate their execution, and manage workloads across cloud and self-hosted deployments. Its native harness owns the execution loop, tool invocation, execution state, and model provider interface.

### Goals

- Open source: Designed for community development and contributions.
- Self-hostable: Run Kairo on your own infrastructure.
- Extensible: Support different agent frameworks and runtimes.
- Cloud-native: Built with scalable execution and orchestration in mind.

### Status

Early development. This repository currently contains the development foundation and application scaffolds; platform functionality is implemented in later phases.

## Repository layout

| Path | Purpose |
| --- | --- |
| `apps/web` | React frontend |
| `apps/control-plane` | Fastify control plane |
| `apps/worker` | Execution worker |
| `packages/contracts` | Shared API and message contracts |
| `packages/config` | Shared TypeScript configuration |
| `packages/sdk` | Public TypeScript client |
| `harness/kairo_harness` | Native Python harness project |
| `runtime/base` | Base harness image |
| `runtime/environments` | Specialized workload images |
| `deploy/compose` | Docker Compose deployment |
| `deploy/config` | Deployment configuration |
| `docs` | Authoritative project documentation |
| `tests/integration` | Integration tests |
| `tests/e2e` | Browser end-to-end tests |

## Prerequisites

- Docker Engine with the Compose v2 plugin, or a compatible Compose provider.
- Node.js 24.19.0 (pinned in `.node-version`)
- Corepack (included with Node.js)
- Python 3.13.13 (pinned in `.python-version`)
- uv `>=0.11.11,<0.12` (pinned in the harness project)

## Initial setup

```sh
cp .env.example .env
corepack enable
pnpm install
pnpm run python:sync
```

Edit `.env` before starting infrastructure. `.env` is ignored by Git; never commit real credentials.

## Environment configuration

| Variable | Purpose | Local default |
| --- | --- | --- |
| `POSTGRES_USER` | PostgreSQL role created by Compose | `kairo` |
| `POSTGRES_PASSWORD` | Password for that role | `change-me` |
| `POSTGRES_DB` | Default database created by Compose | `kairo` |
| `POSTGRES_PORT` | Host port bound to the container | `5432` |
| `DATABASE_URL` | Control plane connection string | matches the defaults above |
| `TEST_DATABASE_URL` | Integration test connection string | matches the defaults above |
| `DATABASE_SCHEMA` | Optional runtime search path | unset |
| `HOST` | Control-plane bind address | `127.0.0.1` |
| `PORT` | Control-plane HTTP port | `3000` |
| `SESSION_TTL_SECONDS` | Session lifetime | `604800` |
| `LOG_LEVEL` | Control-plane log level | `info` |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Gemini credential; `GOOGLE_API_KEY` is the fallback | unset |
| `ANTHROPIC_API_KEY` | Claude credential | unset |
| `OPENAI_API_KEY` | OpenAI credential | unset |
| `OPENAI_ORGANIZATION` | Optional OpenAI organization | unset |
| `KAIRO_GEMINI_API_KEY_ENV`, `KAIRO_ANTHROPIC_API_KEY_ENV`, `KAIRO_OPENAI_API_KEY_ENV` | Override the environment variable name that holds a provider key | provider default |
| `KAIRO_GEMINI_BASE_URL`, `KAIRO_ANTHROPIC_BASE_URL`, `KAIRO_OPENAI_BASE_URL`, `KAIRO_OLLAMA_BASE_URL` | Provider endpoints used by direct provider adapters | provider default or local Ollama |
| `KAIRO_*_TIMEOUT_SECONDS`, `KAIRO_ANTHROPIC_MAX_TOKENS` | Provider request settings | 30 seconds, 1024 tokens |

Compose binds PostgreSQL only to `127.0.0.1`. If you change `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, or `POSTGRES_PORT`, update `DATABASE_URL` and `TEST_DATABASE_URL` to match.

## Local environment commands

```sh
pnpm run dev:config
pnpm run dev:up
pnpm run dev:health
pnpm run dev:logs
pnpm run dev:down
```

`dev:config` validates and prints the resolved Compose configuration. `dev:up` starts PostgreSQL with a persistent named volume. `dev:down` stops and removes the container but keeps the volume. `dev:images:build` rebuilds any available application images; no application images are defined yet, so it currently performs no build.

## Database access

```sh
psql "$DATABASE_URL"
pnpm --filter @kairo/control-plane db:studio
```

Migrations are not generated or applied during application startup:

```sh
pnpm run db:migrate
pnpm --filter @kairo/control-plane db:generate
pnpm --filter @kairo/control-plane db:check
```

`db:migrate` also verifies that the control plane can connect to the Compose database and produces a redacted connection-failure message when it cannot.

Database integration tests require `TEST_DATABASE_URL` and a role with `CREATEDB`. The tests create and drop disposable databases and do not use the persistent development volume.

## Control-plane identity API

After migrating, `pnpm --filter @kairo/control-plane start` serves the identity and access API. Users register at `POST /v1/auth/register`, authenticate at `POST /v1/auth/login`, and use the returned bearer token for protected routes. Organizations are created at `POST /v1/organizations`; membership roles are owner, admin, and member. `GET /openapi.json` exposes the generated API contract, and `GET /health` checks the database connection. See `apps/control-plane/README.md` for the full route list.

## Resetting local data

```sh
pnpm run dev:db:reset
```

This removes the PostgreSQL named volume and all local development data, then starts a fresh PostgreSQL container. Do not use it when you need to preserve local data.

## Object storage

Local MinIO is not added in this phase. The current milestones have no runnable consumer of the S3-compatible storage interface, so adding it would introduce unused infrastructure. S3-compatible storage remains the architectural choice for artifacts and large files; an optional Compose profile can be added when that interface has an implementation to exercise.

## Native harness

The Python harness in `harness/kairo_harness` is independent of the control plane. Its ReAct loop, provider interface, tools boundary, and structured event emitter are usable directly from Python. Automated tests use the built-in mock provider and require neither Ollama nor network access:

```sh
pnpm run test:python
```

### Standalone execution interface

`StandaloneHarness` is the lightweight caller-facing interface. It accepts an `ExecutionConfig`, an explicit provider or provider registry, optional tools, and an optional `EventSink`. `run()` returns a `StandaloneRunResult` containing the `ExecutionResult`, structured events, and convenience access to status, output, errors, and usage. Cancellation is returned as a `cancelled` result; timeouts and failures remain explicit `failed` results with their terminal reason and error information.

```python
import asyncio
import uuid

from kairo_harness import ExecutionConfig, ModelConfig, StandaloneHarness
from kairo_harness.providers.mock import MockProvider
from kairo_harness.domain import ModelResponse

config = ExecutionConfig(
    agent_id="local-agent",
    execution_id=uuid.uuid4(),
    task="Confirm that the harness is running.",
    model=ModelConfig(provider="mock", model="mock-model"),
)

async def main() -> None:
    provider = MockProvider([ModelResponse(content="Kairo harness is ready.")])
    async with StandaloneHarness(provider=provider) as harness:
        run = await harness.run(config)
        print(run.status.value, run.output, run.usage.total_tokens)
        for event in run.events:
            print(event.type)

asyncio.run(main())
```

The equivalent command-line interface requires no control-plane or worker process:

```sh
uv run --project harness/kairo_harness python -m kairo_harness \
  --provider mock \
  --task "Confirm that the harness is running."

uv run --project harness/kairo_harness python -m kairo_harness \
  --provider ollama \
  --model gemma3:270m \
  --task "Summarize what you can do." \
  --events
```

The CLI uses `ProviderSettings.from_env()` for Gemini, Anthropic, OpenAI, and Ollama. `--provider mock` runs the built-in deterministic provider without credentials. `--events` prints the same versioned event envelopes exposed through the Python result. Structured events are redacted before emission and never include hidden model reasoning.

Provider adapters use the official SDKs for Gemini, Claude, and OpenAI, and a direct HTTP adapter for Ollama. `ProviderSettings.from_env()` enables only providers whose credentials or endpoints are present. `ModelConfig` selects the provider and model; API keys stay in the environment and are never stored in model or agent configuration.

Every adapter normalizes responses, native tool calls, tool results, token usage, finish reasons, model discovery, and retry-classified errors. Capability validation happens before a provider request, so unsupported streaming or tool use fails explicitly instead of producing a provider-specific error.

### Local and container execution

To exercise a real local model manually, keep using the existing smoke script, or use the CLI entrypoint with the same reachable Ollama endpoint:

```sh
KAIRO_OLLAMA_BASE_URL=http://127.0.0.1:11434 \
KAIRO_OLLAMA_MODEL=gemma3:270m \
uv run --project harness/kairo_harness python harness/kairo_harness/scripts/ollama_smoke.py

KAIRO_OLLAMA_BASE_URL=http://127.0.0.1:11434 \
uv run --project harness/kairo_harness python -m kairo_harness \
  --provider ollama --model gemma3:270m --task "Reply with a short confirmation."
```

The lightweight base image is defined in `runtime/base/Dockerfile`. It installs only the harness runtime and shared contract schemas, runs as a non-root user, and has no credentials or worker services baked into the image:

```sh
docker build -f runtime/base/Dockerfile -t kairo-harness:local .

docker run --rm kairo-harness:local \
  --provider mock --task "Confirm that the harness is running."

docker run --rm \
  -e KAIRO_OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  kairo-harness:local \
  --provider ollama --model gemma3:270m --task "Reply with a short confirmation."
```

`localhost` is only correct when the harness itself runs on the machine hosting Ollama. In a container or distributed deployment, configure a reachable host or gateway endpoint. Runtime resource limits, network policy, and workspace mounts remain the responsibility of the future execution runtime; this image only provides the standalone harness entrypoint.

Model tool decisions must be native provider tool calls or the strictly validated JSON action format `{"type":"tool_call","tool_calls":[...]}`. Plain text is treated only as a final answer and is never executed.

Model streaming is opt-in through `ModelConfig.stream_responses`, which defaults to `false`. The non-streaming execution path is unchanged. When streaming is enabled, the runner aggregates content, tool-call fragments, per-chunk usage deltas, and finish reasons before the normal decision-parsing and tool-execution pipeline. Provider adapters normalize cumulative provider counters into per-chunk deltas so the runner can sum usage without double-counting or undercounting. Stream events contain only operational metadata; raw model output and private reasoning are never emitted.

Tools are registered through `ToolRegistry` with unique names, JSON Schema definitions, handlers, and required permissions. A runner receives an immutable registry snapshot and an immutable set of execution permissions; later registry changes or handler output cannot grant access to additional tools. Authorization and schema validation happen before handler invocation, and handler errors, invalid results, and timeouts become structured `ToolResult` errors that the ReAct loop observes. Emitted events use the shared versioned envelopes, redact sensitive fields, and do not include hidden reasoning or raw prompts.

## Verification

```sh
pnpm run workspaces
pnpm run verify
```

`verify` runs TypeScript type checking, Biome and Ruff formatting/lint checks, all Vitest tests, and the pytest contract tests. The control-plane Vitest suite requires `TEST_DATABASE_URL` and a running PostgreSQL instance. `packages/contracts/README.md` describes the shared contract system; `apps/control-plane/README.md` describes database setup and migrations.

## Continuous integration

`.github/workflows/ci.yml` runs on pushes and pull requests targeting `main`, and can be started with workflow dispatch. It uses read-only `GITHUB_TOKEN` permissions and a disposable PostgreSQL 17 service container with non-production credentials.

CI checks:

- Pinned Node.js, pnpm through Corepack, frozen-lockfile installation, Biome checks, TypeScript typechecking, Vitest, and shared contract fixture validation.
- Pinned Python, uv with the committed lockfile, Ruff lint and format checks, and pytest against the same shared contract fixtures.
- PostgreSQL readiness, Drizzle migration consistency, migration application, and control-plane database integration tests through `TEST_DATABASE_URL`.
- Repository-wide verification through `pnpm run verify`, plus `git diff --check`.

Equivalent local checks:

```sh
corepack enable
pnpm install --frozen-lockfile
uv sync --locked --project harness/kairo_harness
pnpm run dev:up
export DATABASE_URL=postgresql://kairo:change-me@localhost:5432/kairo
export TEST_DATABASE_URL=postgresql://kairo:change-me@localhost:5432/kairo
until pg_isready -h 127.0.0.1 -p 5432 -U kairo -d kairo; do sleep 1; done
pnpm --filter @kairo/control-plane db:check
pnpm --filter @kairo/control-plane db:migrate
pnpm run verify
git diff --check
pnpm run dev:down
```

Use a local PostgreSQL 17 instance with equivalent credentials if Compose is unavailable. Phase 0.4 Compose startup, persistence, and health checks remain unverified on the current development host; CI uses a GitHub Actions service container and does not claim those Compose checks passed.

## Troubleshooting

- **`docker: command not found` or Compose plugin missing:** install Docker Engine with Compose v2 or enable a compatible Compose provider before using the `dev:*` scripts.
- **Port 5432 already in use:** set `POSTGRES_PORT` to another host port and update both connection strings in `.env`.
- **Authentication failed:** confirm `POSTGRES_USER` and `POSTGRES_PASSWORD` match the credentials embedded in `DATABASE_URL`.
- **Health check never becomes healthy:** inspect `pnpm run dev:logs` and `pnpm run dev:health`; verify the image can start and the data volume is writable.
- **Connection succeeds but tables are missing:** run `pnpm run db:migrate`.
- **Need a clean local database:** use `pnpm run dev:db:reset` only after confirming local data can be discarded.
