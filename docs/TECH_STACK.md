# Kairo Technology Stack

## 1. Purpose

This document defines the technologies, libraries, and infrastructure selected to build Kairo.

The stack is designed around three priorities:

1. **Lightweight:** Minimize infrastructure, dependencies, and operational overhead.
2. **Ownership:** Keep Kairo's core execution, orchestration, and coordination logic under its control.
3. **Extensibility:** Make integrations and infrastructure replaceable without redesigning the platform.

Kairo uses established technologies where they solve well-understood problems and implements its own abstractions where platform ownership matters.

The technology choices in this document are the implementation baseline for Kairo.

## 2. Technology Overview

| Area | Technology |
|---|---|
| Frontend | React + TypeScript |
| Frontend build | Vite |
| Styling | Tailwind CSS |
| UI components | shadcn/ui |
| Icons | Lucide React |
| Frontend routing | React Router |
| Server state | TanStack Query |
| Client state | Zustand |
| Frontend validation | Zod |
| Charts | Recharts |
| Control plane | Node.js + TypeScript |
| HTTP framework | Fastify |
| API schemas | TypeBox |
| Database toolkit | Drizzle ORM |
| Primary database | PostgreSQL |
| Execution worker | Node.js + TypeScript |
| Container management | Docker Engine API |
| Native harness | Python + asyncio |
| Harness validation | Pydantic v2 |
| Harness HTTP client | HTTPX |
| Model integrations | Official provider SDKs and custom adapters |
| Local model support | Ollama |
| Shared contracts | OpenAPI and JSON Schema |
| Object storage | S3-compatible storage |
| Worker communication | WebSocket |
| API communication | REST |
| Observability | OpenTelemetry |
| TypeScript logging | Pino |
| Python logging | Structlog |
| Testing | Vitest, pytest, Playwright |
| TypeScript tooling | Biome |
| Python tooling | Ruff |
| Deployment | Docker Compose |
| CI/CD | GitHub Actions |
| Container images | Dockerfiles + BuildKit |

## 3. Frontend

### 3.1 Framework and Build System

**React + TypeScript + Vite**

React provides the component-based interface, TypeScript provides static typing, and Vite handles development and production builds.

The frontend is a standalone application that communicates with the control plane through its API.

Next.js is not required because Kairo's primary interface is an authenticated application rather than a server-rendered content platform.

### 3.2 UI and Styling

**Tailwind CSS + shadcn/ui + Lucide React**

- Tailwind CSS provides utility-based styling.
- shadcn/ui provides accessible, customizable interface components maintained directly in the codebase.
- Lucide React provides consistent SVG icons.

Components must remain reusable and follow a shared design system. The application must avoid introducing multiple competing component libraries.

### 3.3 Frontend State and Data

| Library | Responsibility |
|---|---|
| TanStack Query | API requests, caching, mutations, server state |
| Zustand | Lightweight client-side state |
| Zod | Runtime validation |
| React Router | Application routing |
| Recharts | Charts and execution metrics |

Server state and local interface state must remain separate. API data should not be duplicated unnecessarily in global client state.

### 3.4 Live Updates

The frontend uses authenticated WebSocket connections for live execution events, status updates, and streaming information where appropriate.

REST remains the primary interface for resource creation, configuration, and retrieval.

## 4. Control Plane

### 4.1 Language and Runtime

**TypeScript on Node.js**

The control plane is a modular application with explicit internal boundaries.

It owns authentication, authorization, agent management, orchestration, persistence, scheduling, coordination, and API access.

### 4.2 HTTP Framework

**Fastify**

Fastify provides:

- HTTP routing and middleware.
- Request validation and serialization.
- Plugin-based modularity.
- TypeScript integration.
- WebSocket support through its ecosystem.

The control plane must remain a modular application rather than being divided into independently deployed microservices prematurely.

### 4.3 API Schemas

**TypeBox**

TypeBox provides runtime schemas and TypeScript types for API requests and responses.

Fastify routes must use explicit schemas for validation and serialization.

OpenAPI documentation must be generated from the API definitions.

### 4.4 Database Access

**Drizzle ORM**

Drizzle provides typed PostgreSQL queries, schema definitions, and migration tooling.

The control plane is the primary owner of database access and migrations.

The Python harness must not access the platform database directly. Platform state is accessed through defined interfaces and authorized operations.

## 5. Native Agent Harness

### 5.1 Language and Runtime

**Python + asyncio**

The native harness is a Kairo-owned execution engine.

Python provides the ecosystem required for model integrations and AI workloads. Asyncio provides concurrent execution of model requests, tools, and asynchronous operations.

### 5.2 Core Libraries

| Library | Responsibility |
|---|---|
| Pydantic v2 | Data models, validation, configuration schemas |
| HTTPX | Asynchronous HTTP communication |
| asyncio | Asynchronous execution |
| Official provider SDKs | Model-specific communication |
| Structlog | Structured logging |

### 5.3 Native Execution Engine

Kairo implements its own:

- Agent execution loop.
- Model request lifecycle.
- Tool registry and invocation.
- Context management.
- Execution state management.
- Memory interface.
- Checkpointing and recovery.
- Delegation interface.
- Event emission.
- Permission enforcement.

The harness must not depend on an external agent framework to perform these responsibilities.

### 5.4 ReAct Execution Pattern

The native harness uses a ReAct-style execution cycle: Reason, Act, Observe, and repeat until the task reaches a terminal state.

The execution cycle is:

1. **Reason:** Provide the model with the authorized task context and available tools so it can determine its next action.
2. **Act:** Validate and execute the selected tool call or other permitted action.
3. **Observe:** Collect the tool result, execution events, and relevant state changes.
4. **Continue:** Update the execution context and request the model's next decision.
5. **Complete:** Return a structured result when the model determines that the task is complete or a terminal condition is reached.

The harness controls this cycle. The model does not control execution permissions, checkpointing, or platform lifecycle transitions.

ReAct is an execution pattern, not a dependency or a rigid prompt format. Kairo must support native model tool-calling capabilities while retaining control over the execution loop.

Private model reasoning must not be treated as ordinary execution logs. Observability records structured decisions, tool calls, results, and state transitions without requiring exposure or storage of hidden chain-of-thought.

## 6. Model Provider Integration

### 6.1 Kairo Provider Interface

Kairo defines and owns a common model provider interface.

Provider adapters translate between this interface and individual provider APIs.

The interface must support:

- Model discovery where supported.
- Model selection and capability information.
- Standardized request configuration.
- Streaming responses.
- Tool calls and tool results.
- Usage information.
- Provider errors and retry classification.
- Provider-specific configuration where necessary.

### 6.2 Provider Implementations

Initial integrations prioritize:

- OpenAI.
- Anthropic.
- Google Gemini.
- Ollama.

Official provider SDKs are preferred where they provide reliable support for the required capabilities.

Custom adapters must implement the Kairo provider interface.

Ollama receives its own adapter using its supported API. Its configured endpoint must be reachable from the component responsible for making the model request.

### 6.3 Provider Independence

The harness must never depend directly on provider-specific SDK objects or response formats.

Provider adapters must normalize requests, responses, tool calls, streaming events, usage, and errors.

A provider can be replaced or added without changing the agent execution engine.

No mandatory LiteLLM, LangChain, or LangGraph dependency is introduced.

An optional model gateway can be added later without changing the harness-facing provider interface.

## 7. Worker

### 7.1 Language and Runtime

**TypeScript on Node.js**

The worker is a dedicated application responsible for executing assigned workloads.

It handles:

- Worker registration.
- Authenticated control-plane communication.
- Job reception and validation.
- Container lifecycle management.
- Harness startup and termination.
- Execution event reporting.
- Resource monitoring.
- Workspace materialization.
- Local cleanup and reconciliation.

### 7.2 Container Management

**Docker Engine API**

The worker communicates with a Docker-compatible container runtime through its API.

The implementation uses a maintained Node.js Docker client.

Container creation and execution must pass through a Kairo runtime abstraction so that alternative runtime backends can be supported later.

The worker, not the agent container, controls the container runtime.

## 8. Shared Contracts and Communication

### 8.1 API Communication

**REST + OpenAPI**

REST is the primary interface between the frontend and control plane.

OpenAPI provides a documented, language-independent API contract.

API schemas must be explicit, versioned where necessary, and validated at runtime.

### 8.2 Worker Communication

**Authenticated WebSockets**

Workers establish outbound authenticated WebSocket connections to the control plane.

WebSockets support:

- Job dispatch notifications.
- Execution events.
- Worker health updates.
- Status reporting.
- Reconnection and state reconciliation.

Durable job records and leases remain in PostgreSQL. WebSocket delivery is not the source of truth.

### 8.3 Cross-Language Contracts

**OpenAPI + JSON Schema**

Shared message envelopes, execution events, task payloads, and internal communication structures must use versioned JSON Schema contracts.

TypeScript and Python implementations must validate against the same contract definitions and shared test fixtures.

This prevents the two backend languages from developing incompatible interpretations of the same messages.

Message identifiers, correlation identifiers, schema versions, sender identity, recipient identity, and timestamps must be part of the appropriate structured envelopes.

## 9. Database and Storage

### 9.1 Primary Database

**PostgreSQL**

PostgreSQL is the authoritative store for structured platform state.

It stores:

- Users and organizations.
- Agents and configurations.
- Tasks and workflows.
- Messages and coordination state.
- Memory metadata and structured records.
- Worker registrations and leases.
- Execution records.
- Checkpoint metadata.
- Workspace metadata.
- Structured events and audit records.

PostgreSQL-backed durable records also provide job coordination and lease management.

No mandatory Redis, Elasticsearch, or separate message broker is required.

### 9.2 Object Storage

**S3-compatible object storage**

Object storage holds larger or binary data that should not be stored directly in PostgreSQL.

This includes:

- Execution artifacts.
- Large documents.
- Workspace snapshots.
- Checkpoint payloads.
- Archived logs and event data.

The application must use a storage interface compatible with S3 APIs.

### 9.3 Worker-Local Storage

Workers use local storage for:

- Temporary execution workspaces.
- Materialized repository copies.
- Container layers.
- Build caches.
- Temporary artifacts.

Worker-local storage is not authoritative durable storage.

### 9.4 Database Migrations

**Drizzle Kit**

Schema changes must be represented by versioned migrations.

Migrations must be applied through a controlled deployment process.

The control plane owns database schema evolution.

## 10. Observability and Logging

### 10.1 Instrumentation

**OpenTelemetry**

OpenTelemetry provides the common instrumentation layer for:

- Metrics.
- Distributed traces.
- Service instrumentation.
- Execution correlation.
- Worker and control-plane visibility.

The same trace context must be propagated across the control plane, workers, harnesses, and relevant integrations.

### 10.2 Logging

| Component | Logging library |
|---|---|
| Control plane | Pino |
| Worker | Pino |
| Python harness | Structlog |

Logs must be structured and include relevant identifiers.

### 10.3 Event Tracking

Kairo's event system is built around structured, persisted execution events.

Events must cover agent lifecycle transitions, model requests, tool calls, delegation, memory operations, checkpoints, recovery, and completion.

OpenTelemetry provides instrumentation and correlation. It does not replace Kairo's durable execution history.

A separate mandatory Prometheus, Grafana, Loki, or Tempo deployment is not required initially.

## 11. Testing and Code Quality

### 11.1 TypeScript Testing

**Vitest**

Vitest is used for unit and integration tests across the control plane, worker, shared contracts, and frontend utilities.

### 11.2 Python Testing

**pytest**

pytest is used for harness unit tests, provider adapter tests, execution lifecycle tests, and recovery behavior.

### 11.3 End-to-End Testing

**Playwright**

Playwright is used for browser-based tests covering critical user workflows and frontend-to-control-plane integration.

### 11.4 Code Quality

| Language | Tool |
|---|---|
| TypeScript | Biome |
| Python | Ruff |
| Shared contracts | Schema validation and compatibility tests |

Strict TypeScript settings and explicit Python type annotations must be used throughout the project.

Tests must cover critical authorization boundaries, execution lifecycle transitions, worker failures, provider behavior, and recovery paths.

## 12. Container Images and Execution Runtime

### 12.1 Image Build

**Dockerfiles + BuildKit**

Kairo maintains its own lightweight container images.

The image architecture separates:

- Base harness image.
- Specialized workload images.
- User-defined compatible images.

Images must use minimal dependencies, non-root execution, pinned versions, and reusable build layers.

### 12.2 Runtime

**Docker-compatible container runtime**

Docker is the initial execution backend.

The runtime interface must abstract container creation, execution, termination, resource configuration, and cleanup.

Kubernetes is not a requirement for the initial implementation.

### 12.3 Deployment

**Docker Compose**

Docker Compose provides the initial deployment experience for self-hosted installations and local development.

The deployment must support:

- Control plane.
- Worker.
- PostgreSQL.
- S3-compatible object storage.
- Required networking and configuration.

Additional workers must be attachable without requiring changes to the control-plane architecture.

## 13. CI/CD and Development Tooling

### 13.1 CI/CD

**GitHub Actions**

GitHub Actions handles:

- Automated tests.
- Linting and type checks.
- Build validation.
- Container image builds.
- Dependency and security checks.
- Release workflows.

### 13.2 Container Registry

**GitHub Container Registry (GHCR)**

Kairo-maintained container images are published through GHCR.

Images must be versioned and identifiable by immutable digests for reproducible deployments.

### 13.3 Dependency Management

- TypeScript dependencies use a consistent package manager and committed lockfile.
- Python dependencies use a lockfile-based workflow.
- Container base images and critical dependencies must be pinned.
- Automated dependency updates must pass the normal test pipeline.

## 14. Explicitly Excluded from the Initial Stack

The following technologies are not mandatory dependencies of the initial implementation:

| Technology | Reason |
|---|---|
| LangChain | Kairo owns its native harness |
| LangGraph | Kairo owns execution and orchestration |
| LiteLLM | Kairo uses its own provider interface and adapters |
| Redis | PostgreSQL handles initial coordination requirements |
| Kafka / RabbitMQ | PostgreSQL-backed durable jobs are sufficient initially |
| Elasticsearch | PostgreSQL handles initial search requirements |
| Dedicated vector database | Not required for initial memory architecture |
| Kubernetes | Docker Compose and distributed workers meet initial deployment needs |
| Separate microservices for every module | Unnecessary operational complexity |
| Mandatory model gateway | Direct provider adapters are sufficient initially |
| Mandatory Prometheus/Grafana stack | OpenTelemetry instrumentation is sufficient initially |

These exclusions do not prevent future integration when measurable requirements justify them.

## 15. Repository and Project Organization

The implementation should preserve clear boundaries between the platform components.

The initial repository organization follows this structure:

```text
kairo/
├── apps/
│   ├── web/                 # React frontend
│   ├── control-plane/       # Fastify application
│   └── worker/              # Execution worker
│
├── packages/
│   ├── contracts/           # Shared API and message contracts
│   ├── config/              # Shared TypeScript configuration
│   └── sdk/                 # Public TypeScript client
│
├── harness/
│   └── kairo_harness/       # Native Python harness
│
├── runtime/
│   ├── base/                # Base harness image
│   └── environments/        # Specialized workload images
│
├── deploy/
│   ├── compose/             # Docker Compose deployment
│   └── config/              # Deployment configuration
│
├── docs/
│
├── tests/
│   ├── integration/
│   └── e2e/
│
├── docker-compose.yml
├── README.md
├── LICENSE
└── AGENTS.md
```

The structure separates deployable applications, shared contracts, execution images, and deployment configuration without splitting every internal module into its own service.

## 16. Technology Selection Principles

Technology choices must continue to follow these rules:

1. Prefer mature, maintained libraries over custom implementations for standard infrastructure problems.
2. Keep Kairo's core agent execution and coordination logic native.
3. Avoid mandatory dependencies that duplicate existing platform responsibilities.
4. Prefer libraries that work without dedicated infrastructure services.
5. Keep provider, runtime, and storage implementations replaceable.
6. Avoid unnecessary abstraction layers.
7. Measure actual resource and operational costs before introducing new infrastructure.
8. Keep the self-hosted deployment straightforward.
9. Preserve compatibility between TypeScript and Python through explicit contracts.
10. Pin dependencies and validate upgrades through automated tests.

## 17. Final Stack

Kairo is built around a TypeScript control plane and worker, a Python native agent harness, a React frontend, PostgreSQL-backed platform state, and isolated Docker-compatible execution environments.

The harness uses a native ReAct-style execution loop and Kairo-owned interfaces for tools, models, memory, and orchestration.

Established libraries handle the standard infrastructure work. Kairo retains ownership of the behavior that defines the platform.

The result is a modular, extensible agent platform without requiring a large collection of infrastructure services to operate.
