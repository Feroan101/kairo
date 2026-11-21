# AGENTS.md

Instructions for AI coding agents working on the Kairo repository.

These instructions apply to the entire repository unless a more specific `AGENTS.md` overrides them in a subdirectory.

## 1. Project Overview

Kairo is an open-source, cloud-native platform for building, running, and managing AI agents.

Kairo provides:

- A native agent harness.
- Managed execution infrastructure.
- Isolated container-based agent execution.
- Model provider integrations.
- Agent tools and capabilities.
- Persistent agent memory.
- Multi-agent coordination.
- Execution observability and recovery.
- A web interface for managing and monitoring agents.

The initial focus is coding agents, with an architecture designed to support general-purpose autonomous workloads.

Kairo owns its native execution engine, orchestration logic, coordination layer, and platform interfaces.

Do not treat Kairo as a thin wrapper around an external agent framework.

## 2. Authoritative Project Documents

Before making architectural or cross-cutting changes, consult the relevant project documents:

| Document | Authority |
|---|---|
| `docs/PROJECT.md` | Project identity and direction |
| `docs/PRODUCT.md` | Product scope and behavior |
| `docs/ARCHITECTURE.md` | System architecture and component boundaries |
| `docs/REQUIREMENTS.md` | Functional and non-functional requirements |
| `docs/SECURITY.md` | Security model and requirements |
| `docs/TECH_STACK.md` | Technology and dependency decisions |
| `docs/ROADMAP.md` | Implementation sequence and milestones |

These documents define the intended system.

Do not silently contradict them, weaken their requirements, or introduce competing architectural decisions.

When implementation reveals a genuine issue:

1. Identify the conflict or limitation.
2. Determine whether the issue can be solved within the existing design.
3. If not, explain the trade-off and propose a coherent change.
4. Update the relevant documentation alongside the implementation when an approved architectural change is made.

Do not create undocumented architectural exceptions.

## 3. Core Engineering Principles

### 3.1 Keep Kairo native

Kairo owns its:

- Agent execution loop.
- Tool execution system.
- Agent lifecycle.
- Execution state.
- Context management.
- Memory interfaces.
- Checkpointing.
- Agent coordination.
- Model provider abstraction.
- Runtime abstraction.

Use established libraries for standard infrastructure problems. Do not introduce an external agent framework to replace Kairo's native responsibilities.

### 3.2 Prefer simplicity

- Prefer the smallest solution that fully satisfies the requirement.
- Avoid unnecessary abstractions and indirection.
- Avoid premature microservices.
- Avoid adding infrastructure without a demonstrated need.
- Prefer existing project utilities over duplicate implementations.
- Keep dependencies purposeful and minimal.

Lightweight does not mean incomplete. Do not remove necessary security, reliability, or platform capabilities merely to reduce code.

### 3.3 Respect component boundaries

The system has distinct responsibilities:

- **Frontend:** User interface and presentation.
- **Control plane:** Authentication, authorization, orchestration, persistence, coordination, and API access.
- **Worker:** Job execution, container lifecycle, workspace materialization, and execution reporting.
- **Native harness:** Agent reasoning and action execution.
- **Runtime:** Isolated execution environments.
- **Storage:** Durable structured state and large artifacts.

Do not move responsibilities between these components without architectural justification.

### 3.4 Design for replacement

Model providers, container runtimes, storage backends, and external integrations must be accessed through defined interfaces.

Implementations should be replaceable without changing unrelated core components.

Do not introduce abstractions for hypothetical requirements. Abstractions must represent real system boundaries.

## 4. Technology Rules

Follow `docs/TECH_STACK.md`.

### Frontend

- React with TypeScript.
- Vite.
- Tailwind CSS.
- shadcn/ui.
- Lucide React.
- React Router.
- TanStack Query for server state.
- Zustand for client state.
- Zod for frontend validation.
- Recharts for charts.

Do not introduce another UI framework or component library without a clear requirement.

### Control Plane

- Node.js with TypeScript.
- Fastify.
- TypeBox.
- Drizzle ORM.
- PostgreSQL.

Use Fastify's plugin architecture and typed request schemas.

### Worker

- Node.js with TypeScript.
- Docker Engine API through a maintained client.
- Shared TypeScript contracts.

The worker is a separate application, not a module that runs inside the control plane process.

### Native Harness

- Python.
- asyncio.
- Pydantic v2.
- HTTPX.
- Official provider SDKs and Kairo-owned adapters.

Do not introduce LangChain, LangGraph, or LiteLLM as core execution dependencies.

### Testing and Quality

- Vitest for TypeScript.
- pytest for Python.
- Playwright for end-to-end browser tests.
- Biome for TypeScript formatting and linting.
- Ruff for Python formatting and linting.

Do not add competing tools without justification.

## 5. Native Harness Rules

The native harness is one of Kairo's most important components.

It must remain independent of the control plane and capable of running inside an isolated execution container.

### 5.1 ReAct execution

Implement the harness using a ReAct-style execution cycle:

1. Reason.
2. Act.
3. Observe.
4. Continue or complete.

The harness controls execution state and tool invocation.

The model may request actions, but the harness validates permissions, validates arguments, executes tools, and records results.

Never allow model output to directly bypass execution controls.

### 5.2 Tool execution

Every tool must:

- Have a defined name and schema.
- Validate its input.
- Enforce applicable permissions.
- Have controlled execution behavior.
- Return a structured result.
- Produce appropriate execution events.
- Handle errors and timeouts.

Avoid arbitrary tool execution paths that bypass the registry or permission system.

### 5.3 Model integration

All providers must implement the Kairo provider interface.

Provider-specific behavior belongs in adapters, not throughout the execution engine.

Normalize common behavior while retaining access to provider-specific capabilities where necessary.

### 5.4 Execution state

Keep model context, harness state, and platform execution metadata distinct.

Execution state must support safe checkpointing and recovery.

Do not serialize arbitrary process memory or assume a running Python process can be restored from a checkpoint.

Do not expose hidden model reasoning as ordinary logs or persisted execution history.

## 6. Communication and Contracts

Communication between components must use explicit, versioned contracts.

- REST for primary API operations.
- Authenticated WebSockets for worker-to-control-plane communication.
- JSON Schema for shared message and event payloads.
- OpenAPI for HTTP API documentation.

TypeScript and Python implementations must validate against the same contract definitions and shared test fixtures.

All relevant messages must include appropriate identifiers, correlation information, sender information, and schema versions.

Do not introduce direct uncontrolled communication between agents. Agent-to-agent communication must pass through Kairo's coordination layer.

Do not treat WebSocket delivery as durable job state. PostgreSQL-backed records and leases remain authoritative.

## 7. Database and Storage Rules

PostgreSQL is the authoritative store for structured platform state.

Use Drizzle ORM for TypeScript database access and versioned migrations.

- Do not access the platform database directly from the Python harness.
- Do not store large binary artifacts directly in PostgreSQL.
- Use the S3-compatible storage interface for large artifacts and checkpoint payloads.
- Treat worker-local storage as temporary unless explicitly persisted.
- Do not introduce Redis, Elasticsearch, Kafka, a dedicated vector database, or another infrastructure service without demonstrated requirements.

Database changes must include appropriate migrations and tests.

Avoid destructive migrations that could silently discard existing user data.

## 8. Execution and Runtime Security

Security is mandatory.

### Containers

- Never run agent workloads as root by default.
- Never use privileged containers by default.
- Drop unnecessary Linux capabilities.
- Apply CPU, memory, process, and disk limits.
- Restrict network access according to execution permissions.
- Use workspace-scoped mounts.
- Prefer read-only root filesystems where practical.
- Never expose the host Docker socket to agent workloads.
- Never mount unrestricted host filesystem paths into agent containers.

### Credentials

- Never hardcode secrets.
- Never commit credentials or tokens.
- Never expose provider credentials to arbitrary repository scripts.
- Never pass credentials through untrusted model context.
- Redact sensitive values from logs and events.
- Use scoped credentials and explicit authorization.

### Authorization

- Validate permissions at the component responsible for the action.
- Do not rely solely on frontend visibility or model instructions.
- Enforce user, organization, agent, execution, and workspace boundaries.
- Reject unauthorized operations by default.

Consult `docs/SECURITY.md` before modifying security-sensitive code.

## 9. Reliability and Execution Safety

Execution failures must be explicit and recoverable where possible.

- Use durable job records and leases.
- Make message handling idempotent where applicable.
- Distinguish worker disconnection from execution completion.
- Reconcile worker state after reconnection.
- Classify retryable and non-retryable failures.
- Checkpoint only at safe execution boundaries.
- Do not blindly replay operations with uncertain external side effects.
- Preserve execution history when an execution fails.
- Clean up expired temporary resources.

Do not hide failures behind broad exception handling or silently mark unsuccessful executions as complete.

## 10. Observability

Important platform operations must produce structured events.

Examples include:

- `execution.created`
- `agent.started`
- `model.requested`
- `tool.started`
- `tool.completed`
- `memory.updated`
- `agent.delegated`
- `execution.checkpointed`
- `execution.completed`
- `execution.failed`

Events and logs should include relevant execution, agent, worker, and correlation identifiers.

Use OpenTelemetry for instrumentation and trace propagation.

Do not log secrets, credentials, or hidden model reasoning.

Observability must explain what the system did, what tools it invoked, what results it received, and where failures occurred.

## 11. Code Quality

### TypeScript

- Enable strict TypeScript settings.
- Avoid `any` unless there is a documented and justified reason.
- Prefer explicit types and runtime validation at system boundaries.
- Avoid duplicated schemas.
- Keep modules focused.
- Handle asynchronous failures explicitly.

### Python

- Use type annotations.
- Use Pydantic models at external data boundaries.
- Prefer asyncio-compatible libraries.
- Avoid blocking operations in asynchronous execution paths.
- Handle cancellation and resource cleanup correctly.
- Avoid broad exception handling that obscures failures.

### General

- Write readable code.
- Use descriptive names.
- Keep functions focused.
- Avoid unnecessary comments that merely restate code.
- Document non-obvious decisions and constraints.
- Remove dead code rather than leaving unused implementations.
- Do not add dependencies for functionality already provided by the stack.

## 12. Testing Requirements

Tests must verify behavior, not merely implementation details.

### Unit tests

Cover:

- Core business logic.
- Agent execution transitions.
- Tool validation.
- Provider adapters.
- Permission checks.
- Schema validation.
- Error handling.

### Integration tests

Cover:

- Database persistence.
- API operations.
- Worker registration.
- Job dispatch and leases.
- Container lifecycle.
- Harness communication.
- Event persistence.
- Checkpoint creation and recovery.

### End-to-end tests

Cover important user workflows:

- Authentication.
- Agent creation.
- Provider configuration.
- Model selection.
- Execution creation.
- Live execution monitoring.
- Tool inspection.
- Execution completion.
- Execution history.

Security-sensitive behavior must have explicit tests.

Do not remove, skip, or weaken tests simply to make a build pass.

## 13. Implementation Workflow

Before implementing a task:

1. Read the relevant requirements.
2. Inspect the existing implementation.
3. Identify affected components and contracts.
4. Check the architecture and security implications.
5. Determine the smallest complete implementation.

While implementing:

1. Follow existing project conventions.
2. Keep changes within the appropriate component.
3. Update schemas and contracts when necessary.
4. Add or update tests.
5. Update documentation when behavior or configuration changes.
6. Avoid unrelated refactoring.

After implementing:

1. Run relevant tests.
2. Run type checks.
3. Run linting and formatting checks.
4. Validate builds.
5. Inspect the final diff.
6. Report what changed and any remaining limitations.

Never claim that tests passed unless they were actually executed and passed.

## 14. Dependency and Architecture Changes

Do not introduce a new framework, infrastructure service, database, or major dependency merely because it is popular or convenient.

Before adding one:

1. Identify the requirement it satisfies.
2. Check whether the existing stack already supports it.
3. Evaluate operational and maintenance costs.
4. Consider its impact on self-hosted deployments.
5. Determine whether it creates unnecessary coupling.
6. Explain why it is better than the existing approach.

Do not silently change the selected stack.

When a change is necessary, update the relevant documentation and explain the consequences.

## 15. Git and Repository Practices

- Keep changes focused and reviewable.
- Use descriptive commit messages.
- Do not commit generated secrets, local databases, build outputs, or temporary execution artifacts.
- Do not rewrite shared Git history unless explicitly instructed.
- Do not push or open pull requests unless requested or authorized.
- Preserve unrelated user changes.
- Inspect repository state before making potentially destructive changes.

## 16. Definition of Done

A task is complete only when:

- The requested behavior is implemented.
- Existing architecture and security requirements are respected.
- Relevant tests are added or updated.
- Type checks and linting pass.
- Relevant documentation is updated.
- No unrelated changes are introduced.
- The implementation has been reviewed for failure cases and resource cleanup.

For cross-component features, verify that the complete workflow works across the affected applications.

A successful build alone does not mean a feature is complete.

## 17. Final Instruction

Build Kairo as one coherent platform.

Favor explicit contracts, clear ownership, reliable execution, observable behavior, and minimal infrastructure.

Do not sacrifice architectural consistency for short-term convenience. Do not introduce complexity without a concrete reason.

When uncertain, inspect the existing implementation and authoritative project documents before making a decision.
