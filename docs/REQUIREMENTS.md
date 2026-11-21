# Kairo Requirements

## 1. Purpose

This document defines the functional and non-functional requirements for Kairo.

It establishes the capabilities, constraints, and expected behavior that guide implementation. Requirements apply to both self-hosted and managed deployments unless explicitly stated otherwise.

The architecture defines how Kairo is structured. This document defines what that architecture must deliver.

## 2. Product Scope

Kairo provides an environment for:

- Creating, configuring, and managing AI agents.
- Running agents through Kairo's native agent harness.
- Connecting cloud-based model providers and locally served models.
- Executing agent workloads in isolated environments.
- Connecting agents to repositories and external tools.
- Coordinating independent agents and hierarchical agent teams.
- Managing agent memory, workspaces, and execution state.
- Observing and recovering agent executions.
- Deploying the platform independently or using a managed deployment.

The initial implementation prioritizes coding agents while preserving the foundations required for general-purpose agent workloads.

## 3. Functional Requirements

### 3.1 User and Organization Management

Kairo must support both individual users and organizations.

- Users must be able to create and manage their accounts.
- Users must be able to create and manage organizations.
- Organizations must support multiple members.
- Organization members must have assigned roles and permissions.
- Resources must be scoped to their owning user or organization.
- Access to agents, executions, credentials, and workspaces must respect those scopes.
- Users must be able to manage active sessions and connected integrations.

### 3.2 Agent Management

Kairo must provide a unified way to create and manage agents.

- Users must be able to create, configure, update, pause, resume, and delete agents.
- Each agent must have a persistent logical identity.
- Agent configuration must include its model, harness version, tools, permissions, memory scope, and execution settings.
- Agents must support both persistent and ephemeral lifecycles.
- Persistent agents must retain their identity and configured state across executions.
- Ephemeral agents must be removable after their assigned work is completed.
- Users must be able to inspect an agent's configuration, status, execution history, and resource usage.
- Agents must be able to run independently or participate in agent teams.
- Agent configuration changes must not silently alter an execution already in progress.

### 3.3 Native Agent Harness

Kairo must provide its own native agent harness.

- The harness must manage the agent execution loop.
- It must support model requests, streaming responses, tool calls, tool results, and continued execution.
- It must maintain the execution context required by an agent.
- It must enforce configured tool and permission boundaries.
- It must expose structured execution events.
- It must support cancellation and controlled termination.
- It must support checkpointing at safe execution boundaries.
- It must support multiple harness versions.
- Each agent must have its own logical harness configuration and runtime state.
- Harness implementations must be replaceable through a defined interface.
- The harness must be deployable independently of the full Kairo platform.

### 3.4 Model Providers

Kairo must provide a common interface for model integrations.

- Users must be able to configure supported cloud model providers.
- Provider credentials must be stored securely.
- Kairo must retrieve available models where the provider supports model discovery.
- Users must be able to select a model for an agent.
- Model selection must account for supported capabilities, including tool calling and streaming.
- Kairo must support locally served models through Ollama.
- Users must be able to configure an Ollama server endpoint and select models available through it.
- The system must report provider connection errors and unavailable models.
- Model requests must expose relevant usage, latency, and error information.
- Provider integrations must be implemented through adapters rather than provider-specific logic throughout the harness.
- Model communication must support direct provider connections and optional gateway-based routing.

### 3.5 Execution Management

Kairo must manage agent executions independently of agent identity.

- Users and workflows must be able to start agent executions.
- Every execution must have a unique identifier and traceable lifecycle.
- Executions must run in isolated containers.
- Execution environments must be provisioned from compatible runtime images.
- Each execution must receive only the configuration, credentials, tools, and workspace access it requires.
- Executions must support configurable resource limits.
- Users must be able to inspect execution status.
- Users must be able to cancel running executions.
- The system must distinguish queued, starting, running, completed, failed, cancelled, and recovery states.
- Execution results and artifacts must remain accessible according to their retention policy.
- Execution state must not depend exclusively on a worker's local filesystem.

### 3.6 Execution Environments

Kairo must provide lightweight, reproducible execution environments.

- Kairo must maintain its own base harness image.
- It must provide specialized workload images for supported environments.
- Initial workload environments must prioritize common coding workloads.
- Images must be versioned and compatible with supported harness versions.
- Images must run as non-root users.
- Images must avoid unnecessary packages and background services.
- Users must be able to configure supported custom execution images.
- The runtime layer must abstract the underlying container implementation.
- Container creation, execution, termination, and cleanup must be managed by the worker.
- Temporary execution data must be cleaned up after the execution lifecycle ends, subject to retention and recovery requirements.

### 3.7 Worker Management

Kairo must support distributed execution workers.

- Workers must register with the control plane.
- Workers must maintain authenticated outbound connections.
- Workers must report health, capabilities, and available capacity.
- The control plane must assign eligible executions to workers.
- Worker availability must be tracked through heartbeats and leases.
- Workers must be able to execute jobs independently of the control plane's request lifecycle.
- Workers must report execution events and results.
- Workers must reconcile their state after reconnecting.
- The system must detect lost workers and handle their active executions according to recovery policy.
- Workers must not require public inbound network access for normal job dispatch.

### 3.8 Workspaces and Repository Access

Kairo must provide isolated workspaces for agent execution.

- Agents must be able to access persistent or temporary workspaces.
- Workspace access must be scoped to authorized agents and executions.
- Persistent workspaces must retain their data across executions.
- Temporary workspaces must be cleaned up after their lifecycle ends.
- Workers must be able to materialize workspaces locally for execution.
- Workspace changes must be versioned or otherwise traceable.
- Concurrent access must not silently overwrite another execution's changes.
- The system must support Git-based repository workflows.

GitHub integration must allow users to:

- Connect their GitHub account.
- Select repositories they have authorized Kairo to access.
- Allow agents to inspect repository contents.
- Allow agents to create and modify files within their workspace.
- Create branches and commits.
- Push changes using the connected identity and granted permissions.
- Open pull requests.
- Inspect relevant repository and pull request information.

GitHub operations must respect the permissions granted by the user. Repository scripts and arbitrary agent workloads must not receive unrestricted access to GitHub credentials.

### 3.9 Multi-Agent Orchestration

Kairo must support independent agents and hierarchical agent teams.

- Users must be able to create and configure agent teams.
- Teams must support a coordinating agent and delegated agents.
- Agents must be assignable to tasks according to their capabilities and permissions.
- The coordination layer must manage task assignment, dependencies, scheduling, and lifecycle.
- Agents must be able to request delegation within their authorized scope.
- Task state must be persisted independently of message delivery.
- The system must track task ownership, progress, completion, and failure.
- Agents must be able to operate independently when they are not part of a team.
- Orchestration must support cancellation and failure propagation policies.

### 3.10 Agent Communication

Agent communication must be managed by Kairo's coordination layer.

- Agents must communicate through structured message envelopes.
- Messages must include identifiers, sender and recipient information, message type, timestamps, and correlation context.
- Message payloads must support flexible structured content.
- Messages must be persisted and traceable.
- The system must support task handoffs, delegation requests, results, status updates, and coordination messages.
- Message delivery must tolerate retries and duplicate delivery.
- Consumers must be able to identify and handle duplicate messages.
- Message delivery must respect organization, team, agent, and task permissions.
- Direct, uncontrolled agent-to-agent communication must not bypass the coordination layer.

### 3.11 Agent Memory

Kairo must provide private and shared memory.

- Each agent must have a private memory scope.
- Agent teams must be able to use shared memory.
- Memory access must respect ownership and permissions.
- Structured memory records and metadata must be queryable.
- Larger documents and artifacts must be stored separately from structured metadata.
- Memory must persist independently of an individual harness runtime.
- Agents must be able to retrieve relevant authorized memory during execution.
- Memory updates must be traceable.
- The system must support memory retention and deletion policies.
- Memory retrieval must not expose information outside the requesting agent's authorized scope.

### 3.12 Checkpointing and Recovery

Kairo must support recovery without relying on full container snapshots.

- The harness must create checkpoints at safe execution boundaries.
- Checkpoints must capture the state required to resume an execution safely.
- Workspace state must be referenced separately from harness state.
- Checkpoints must be incremental where practical.
- The system must enforce checkpoint size, count, and retention limits.
- Recovery must account for completed and pending tool operations.
- Non-idempotent operations must not be blindly replayed when their outcome is uncertain.
- The recovery system must distinguish recoverable failures from failures requiring user intervention.
- Recovery decisions must follow configurable policies.
- Users must be able to inspect recovery attempts and their outcomes.

### 3.13 Observability

Kairo must make agent execution observable.

Users must be able to inspect:

- Agent and execution status.
- Execution timelines and lifecycle transitions.
- Harness events and structured logs.
- Model requests, responses, usage, latency, and errors.
- Tool calls, inputs, outputs, and execution results, subject to redaction.
- Agent-to-agent messages and task handoffs.
- Memory operations.
- Worker health and capacity.
- CPU, memory, disk, and other relevant resource usage.
- Checkpoints, retries, recovery attempts, and failures.

The observability system must:

- Provide correlation across agents, tasks, executions, workers, and workflows.
- Support structured events and logs.
- Support metrics and distributed traces.
- Preserve useful execution history according to retention policies.
- Redact credentials and sensitive information.
- Avoid exposing secrets through logs, traces, or error messages.

### 3.14 External Integrations and Extensibility

Kairo must provide defined interfaces for extending the platform.

- Model providers must be extendable through provider adapters.
- Harness implementations must be extendable through the harness interface.
- Execution runtimes must be replaceable through the runtime interface.
- Tools and integrations must be registered with explicit permissions.
- External integrations must not bypass Kairo's authorization boundaries.
- The system must support future integration with external agent frameworks.
- Core platform functionality must not depend on a specific external agent framework.

### 3.15 Deployment and Administration

Kairo must support self-hosted and managed deployments.

- A self-hosted installation must be deployable through Docker Compose.
- The initial deployment must not require Kubernetes.
- The control plane and worker must be independently deployable.
- Additional workers must be attachable to an existing deployment.
- Configuration must be manageable through environment variables and documented configuration files.
- Secrets must not be committed to deployment configuration or source control.
- Database migrations must be versioned and repeatable.
- Health checks must be available for core services.
- Deployment documentation must cover installation, configuration, upgrades, backups, and recovery.
- The architecture must support a managed deployment without changing the core agent and execution model.

## 4. Non-Functional Requirements

### 4.1 Performance

- Control-plane operations must remain responsive while executions run independently on workers.
- Job dispatch must not depend on long-running synchronous API requests.
- Worker communication must support responsive dispatch and event reporting.
- Database operations must use appropriate indexing and bounded queries.
- Large artifacts must not be stored directly in database records.
- Execution and observability data must support pagination and retention policies.
- The platform must avoid unnecessary infrastructure and background services.

### 4.2 Scalability

- The control plane must support multiple connected workers.
- Workers must be independently scalable.
- Execution scheduling must account for worker capacity and capabilities.
- The system must support multiple concurrent agents and executions.
- Storage and coordination interfaces must allow future scaling without requiring changes to agent behavior.
- Multi-tenant resource access must remain isolated as deployment size increases.

### 4.3 Reliability

- Durable execution and task state must be stored in persistent infrastructure.
- Job dispatch must tolerate worker disconnections.
- Worker leases and heartbeats must prevent indefinite ownership of abandoned work.
- Duplicate events and messages must be handled safely.
- Recovery must not assume that a disconnected execution has necessarily failed.
- Database and artifact storage failures must be surfaced clearly.
- Critical state transitions must be persisted before being treated as complete.

### 4.4 Security

- Authentication and authorization must apply to every protected resource.
- Organization and user boundaries must be enforced at the API and data layers.
- Agent execution must be isolated from the host system.
- Containers must run with restricted privileges.
- Resource limits must prevent uncontrolled consumption.
- Network access must be restricted according to execution policy.
- Credentials must be scoped, protected, and injected only when required.
- Agent workloads must not receive unrestricted host filesystem access or the host Docker socket.
- Secrets must be redacted from observability data.
- Sensitive operations must produce auditable events.

Detailed security requirements and threat boundaries are defined in `SECURITY.md`.

### 4.5 Maintainability

- Core components must have explicit responsibilities and interfaces.
- The control plane must remain modular without unnecessary service fragmentation.
- Provider, harness, runtime, and storage integrations must use defined abstractions.
- Database migrations must be maintainable and reversible where practical.
- Components must expose health and diagnostic information.
- Tests must cover critical state transitions, authorization boundaries, execution behavior, and recovery paths.

### 4.6 Portability

- The platform must run in a Docker-compatible environment.
- Initial deployment must support common Linux server environments.
- Core functionality must not depend on a specific cloud provider.
- Object storage must use an S3-compatible interface.
- Model integration must support cloud providers and self-hosted Ollama endpoints.
- Runtime abstraction must preserve the option to support alternative execution backends.

## 5. Data and Persistence Requirements

The system must distinguish durable platform state from temporary execution state.

| Data | Required persistence |
|---|---|
| Users and organizations | Durable database |
| Agent identities and configurations | Durable database |
| Tasks and workflows | Durable database |
| Messages and coordination state | Durable database |
| Memory metadata and structured records | Durable database |
| Worker registrations and leases | Durable database |
| Execution records and lifecycle state | Durable database |
| Checkpoint metadata | Durable database |
| Checkpoint payloads | Durable artifact storage |
| Large documents and artifacts | Durable artifact storage |
| Persistent workspace data | Durable workspace storage |
| Temporary execution files | Worker-local storage |
| Container layers and caches | Worker-local storage |
| Structured events and execution history | Durable, policy-controlled storage |

PostgreSQL is the initial primary database. S3-compatible object storage provides durable storage for larger artifacts and workspace data.

Temporary worker-local data must never be treated as the sole copy of information that Kairo promises to preserve.

## 6. Operational Requirements

- Core services must expose health checks.
- Workers must report their availability and capacity.
- Logs must be structured and correlate with execution identifiers.
- Database migrations must run through a controlled process.
- Backups must cover the database and durable object storage.
- Restore procedures must account for consistency between database records and stored artifacts.
- Retention policies must apply to executions, events, artifacts, checkpoints, and temporary data.
- Resource consumption must be observable at the worker and execution levels.
- Configuration errors and unavailable dependencies must produce actionable diagnostics.

## 7. Acceptance Criteria

A Kairo implementation must satisfy the following end-to-end capabilities.

### Platform foundation

- A user can register, authenticate, and create an organization.
- An administrator can deploy Kairo using the documented Docker Compose setup.
- A worker can register with the control plane and report its health.

### Agent execution

- A user can create an agent and configure its model, harness, tools, and permissions.
- The user can start an execution and observe its lifecycle.
- The agent can make a model request, invoke a tool, receive its result, and continue execution.
- The execution runs inside an isolated container.
- The user can inspect its logs, events, model usage, and resource consumption.
- The user can cancel an active execution.

### Model integration

- A user can configure a supported cloud provider and select an available model.
- A user can configure an Ollama endpoint and select a served model.
- An agent can execute through either model source using the common provider interface.

### Repository workflow

- A user can authorize a GitHub repository.
- An agent can inspect the repository in an isolated workspace.
- The agent can make changes, create a branch, commit, and push changes using granted permissions.
- The agent can open a pull request.

### Multi-agent execution

- A user can create a team with multiple agents.
- A coordinating agent can delegate a task to another agent.
- Kairo can route and persist the handoff.
- The receiving agent can return a result.
- The team can track task progress independently of message delivery.

### Memory and recovery

- An agent can retain private memory across separate executions.
- Team members can access authorized shared memory.
- An execution can create a checkpoint at a safe boundary.
- A recoverable failure can resume from a valid checkpoint without blindly repeating uncertain side effects.

### Deployment and scaling

- A self-hosted deployment can run without Kubernetes, Redis, or a dedicated message broker.
- Additional workers can connect without changing the control-plane deployment.
- Persistent state survives worker restarts.
- Temporary execution data is cleaned up according to its lifecycle and retention policy.

## 8. Requirement Priorities

Requirements are implemented in dependency order, not by treating every capability as an independent feature.

The foundational implementation must establish:

1. Authentication, authorization, and organization boundaries.
2. PostgreSQL persistence and database migrations.
3. Control-plane APIs and worker registration.
4. Durable job dispatch and worker leases.
5. The native harness and isolated container execution.
6. Model provider interfaces and initial provider adapters.
7. Execution lifecycle tracking and observability.
8. Workspace and GitHub integration.
9. Agent memory and checkpointing.
10. Multi-agent coordination and orchestration.
11. Deployment hardening and extensibility.

This order establishes a working execution platform before adding higher-level agent coordination. It does not remove any capability from the product scope.

## 9. Requirement Governance

These requirements are the implementation reference for Kairo.

- Architecture decisions must remain consistent with `ARCHITECTURE.md`.
- Product capabilities must remain consistent with `PRODUCT.md`.
- Security controls must be consistent with `SECURITY.md`.
- Implementation details must not silently weaken a requirement.
- Any change to a requirement must be reflected in the relevant documentation and implementation tests.

A requirement is considered satisfied only when its expected behavior is implemented, tested, and observable.
