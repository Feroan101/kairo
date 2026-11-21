# Kairo Development Roadmap

## 1. Purpose

This roadmap defines the implementation sequence for Kairo, from the initial development foundation to a production-ready agent platform.

Development follows a milestone-based approach. Each phase establishes working capabilities that subsequent phases build upon.

The roadmap prioritizes:

1. A functioning native agent execution system.
2. Reliable and isolated execution infrastructure.
3. Durable state, coordination, and recovery.
4. A usable interface with meaningful observability.
5. Multi-agent capabilities and extensibility.
6. Production deployment and operational reliability.

Kairo must remain usable throughout development. Features should be integrated into working end-to-end flows rather than implemented as disconnected subsystems.

## 2. Development Principles

### 2.1 Build vertically

Prioritize complete user workflows over isolated infrastructure components.

For example, an agent should be creatable, configurable, executable, observable, and capable of returning a result before advanced orchestration is introduced.

### 2.2 Establish contracts early

The control plane, worker, and Python harness must agree on their communication contracts before their implementations become tightly coupled.

Shared schemas and compatibility tests are established early.

### 2.3 Keep the initial deployment simple

The first deployment target is a single-node Docker Compose environment.

Distributed workers, managed deployment, and larger-scale operation build on the same architecture.

### 2.4 Validate security continuously

Security is part of implementation, not a final development phase.

Authentication, authorization, execution isolation, credential handling, and resource limits must be included as their corresponding capabilities are built.

### 2.5 Avoid premature infrastructure

Do not introduce additional databases, brokers, vector stores, or orchestration systems without a demonstrated requirement.

## 3. Phase 0: Project Foundation

**Objective:** Establish the repository, development environment, shared conventions, and foundational contracts.

### Deliverables

- Initialize the repository structure.
- Configure the TypeScript workspace and Python project.
- Configure linting, formatting, and type checking.
- Establish environment-based configuration.
- Add Docker Compose development infrastructure.
- Configure PostgreSQL and migrations.
- Establish shared API and message contracts.
- Set up CI using GitHub Actions.
- Establish testing conventions.
- Add initial development and contribution documentation.

### Core implementation

- React + Vite frontend scaffold.
- Fastify control-plane scaffold.
- TypeScript worker scaffold.
- Python harness package scaffold.
- Shared contracts package.
- PostgreSQL connection and migration setup.
- Initial Docker Compose configuration.

### Exit criteria

- All applications build and run independently.
- The frontend can communicate with the control plane.
- The control plane can connect to PostgreSQL.
- Database migrations execute successfully.
- TypeScript and Python can validate shared contract fixtures.
- CI validates formatting, types, builds, and tests.

## 4. Phase 1: Native Harness

**Objective:** Build the native agent execution engine independently of the broader platform.

This phase establishes the core capability that defines Kairo.

### Deliverables

#### 4.1 Agent execution

- Implement the ReAct execution loop.
- Define agent configuration and execution state.
- Implement model request and response handling.
- Support streaming model responses.
- Support native tool calls.
- Handle execution completion, cancellation, and errors.
- Establish execution limits and iteration limits.

#### 4.2 Model providers

- Implement the Kairo model provider interface.
- Implement the first cloud provider adapter.
- Implement Ollama integration.
- Normalize model responses, tool calls, usage, and errors.
- Support model selection and provider configuration.

Additional provider adapters follow the same interface.

#### 4.3 Tool system

- Implement a tool registry.
- Define tool schemas and validation.
- Implement tool execution and result handling.
- Add permission checks before tool invocation.
- Record structured tool events.
- Handle tool timeouts and failures.

#### 4.4 Harness state

- Implement context construction.
- Separate execution state from model conversation context.
- Define memory interfaces.
- Establish safe execution boundaries for checkpointing.
- Support cancellation and graceful shutdown.

#### 4.5 Standalone execution

- Package the harness as a container image.
- Support execution through a local development interface.
- Make execution results and structured events accessible to the caller.

### Exit criteria

- A user can run an agent using a configured model.
- The agent can reason, call tools, observe results, and continue.
- Multiple tool calls can occur within one execution.
- Provider adapters can be changed without modifying the execution loop.
- Execution failures and cancellation are handled predictably.
- The harness runs independently of the control plane.

## 5. Phase 2: Control Plane and Agent Management

**Objective:** Build the platform services required to manage users, agents, and executions.

### Deliverables

#### 5.1 Identity and access

- User registration and authentication.
- Session management.
- Organization and membership foundations.
- Role-based authorization.
- Resource ownership and access checks.

#### 5.2 Agent management

- Agent creation and configuration.
- Agent identity and lifecycle.
- Model and provider configuration.
- Tool permissions.
- Agent execution policies.
- Agent configuration persistence.

#### 5.3 Execution management

- Create execution requests.
- Track execution lifecycle states.
- Store execution metadata.
- Support cancellation.
- Retrieve execution history.
- Associate executions with agents and users.

#### 5.4 Provider management

- Configure cloud providers.
- Securely store provider credentials.
- Configure Ollama endpoints.
- Discover available models where supported.
- Validate provider connectivity.
- Allow users to select models.

#### 5.5 API foundation

- Implement REST endpoints.
- Generate OpenAPI documentation.
- Add request validation.
- Implement consistent error responses.
- Add authorization to protected operations.

### Exit criteria

- Users can authenticate.
- Users can create and configure agents.
- Provider credentials can be stored securely.
- Agents can be assigned a model and permitted tools.
- Execution requests can be created and tracked.
- Resource access is enforced by the control plane.

## 6. Phase 3: Execution Infrastructure

**Objective:** Connect the control plane to distributed workers and execute agents in isolated containers.

### Deliverables

#### 6.1 Worker registration

- Worker identity and registration.
- Authenticated outbound WebSocket connections.
- Worker heartbeats.
- Worker capabilities and status.
- Worker authentication and authorization.

#### 6.2 Job coordination

- Durable job records in PostgreSQL.
- Job claiming and leases.
- Dispatch notifications.
- Assignment and acknowledgement.
- Retry classification.
- Lease expiration and reconciliation.

#### 6.3 Container runtime

- Implement the runtime abstraction.
- Integrate the Docker Engine API.
- Create and configure execution containers.
- Start and stop harness instances.
- Apply resource limits.
- Capture container output and exit status.
- Clean up terminated executions.

#### 6.4 Harness integration

- Define the worker-to-harness communication protocol.
- Launch harness instances inside execution containers.
- Stream execution events to the worker.
- Forward events to the control plane.
- Handle process termination and container failures.

#### 6.5 Execution environments

- Build the lightweight base harness image.
- Add initial coding workload environments.
- Support configurable environment variables.
- Support workspace mounts.
- Support custom compatible images with appropriate restrictions.

### Exit criteria

- The control plane can register and monitor workers.
- Jobs are dispatched through durable records and worker connections.
- Workers can claim jobs and launch isolated containers.
- Harness executions run inside those containers.
- Execution status and events reach the control plane.
- Worker disconnection does not silently lose durable job state.
- Resource limits and container security controls are enforced.

## 7. Phase 4: Frontend and Core User Experience

**Objective:** Deliver a complete interface for managing and running agents.

The frontend can be developed alongside earlier phases, but its end-to-end integration is completed here.

### Deliverables

#### 7.1 Application foundation

- Authentication screens.
- Application layout and navigation.
- Reusable UI components.
- API client and query management.
- Global error handling.
- Responsive layouts.

#### 7.2 Agent management

- Agent listing.
- Agent creation and configuration.
- Model selection.
- Provider configuration.
- Tool permissions.
- Agent details and status.

#### 7.3 Execution interface

- Start an execution.
- View execution status.
- Stream execution updates.
- Display tool calls and results.
- Display final output.
- Cancel active executions.
- Browse execution history.

#### 7.4 Worker management

- Worker status.
- Worker availability.
- Active execution assignments.
- Basic resource information.
- Worker connection health.

### Exit criteria

A user can:

1. Sign in.
2. Configure a model provider.
3. Create an agent.
4. Select its model and tools.
5. Start an execution.
6. Observe its progress.
7. Inspect tool calls and results.
8. Retrieve the completed execution.

The core user journey must work through the interface without requiring manual database operations or direct API calls.

## 8. Phase 5: Workspaces and GitHub Integration

**Objective:** Make Kairo useful for real coding tasks by providing repository access and durable workspace management.

### Deliverables

#### 8.1 Workspace management

- Workspace creation and registration.
- Persistent and temporary workspaces.
- Workspace materialization on workers.
- Workspace version references.
- Workspace leases.
- Cleanup and retention policies.
- Isolated working copies for concurrent executions.

#### 8.2 GitHub integration

- GitHub account connection.
- OAuth-based authorization.
- Repository selection.
- Repository permission checks.
- Repository cloning.
- Branch creation and management.
- Commit creation.
- Push changes.
- Pull request creation.

All operations must use the permissions granted through the connected GitHub identity.

Credentials must not be exposed to arbitrary repository scripts or unrestricted execution environments.

#### 8.3 Coding workflows

- Repository inspection.
- Code modification.
- Test execution.
- Change summaries.
- Commit and pull request workflows.
- Artifact publication.

### Exit criteria

- Users can connect GitHub.
- Users can select authorized repositories.
- Agents can work in isolated repository workspaces.
- Changes can be committed and pushed through authorized operations.
- Agents can open pull requests.
- Concurrent work does not silently overwrite another execution's changes.

## 9. Phase 6: Observability and Reliability

**Objective:** Make executions understandable, debuggable, and recoverable.

Basic observability must already exist in earlier phases. This phase completes the platform-wide experience.

### Deliverables

#### 9.1 Execution observability

- Structured event persistence.
- Execution timelines.
- Model request and response metadata.
- Tool call history.
- Agent delegation events.
- Error and failure information.
- Usage tracking.
- Resource utilization.

#### 9.2 Distributed tracing

- OpenTelemetry instrumentation.
- Trace propagation across services.
- Execution-level correlation.
- Worker and harness instrumentation.

#### 9.3 Checkpointing

- Safe-boundary checkpoint creation.
- Harness state serialization.
- Workspace version references.
- Incremental checkpoint updates.
- Checkpoint storage.
- Retention and cleanup.

#### 9.4 Recovery

- Worker heartbeat and lease reconciliation.
- Recoverable failure classification.
- Retry policies.
- Checkpoint-based resumption where safe.
- Handling of uncertain external side effects.
- User intervention for unrecoverable executions.

#### 9.5 Operational visibility

- Worker health.
- Execution resource limits and usage.
- Failure rates.
- Provider errors.
- Execution latency.
- Storage and database health.

#### 9.6 Data protection

- Secret redaction.
- Sensitive-data filtering.
- Audit event coverage.
- Access controls for logs and execution history.

### Exit criteria

- Users can inspect an execution from start to finish.
- Events can be correlated across the control plane, worker, and harness.
- Recoverable failures can resume safely.
- Non-idempotent operations are not blindly replayed.
- Workers can reconnect and reconcile their state.
- Sensitive credentials are not exposed through logs or ordinary execution events.

## 10. Phase 7: Multi-Agent Coordination

**Objective:** Introduce coordinated agent teams without compromising execution isolation or control.

### Deliverables

#### 10.1 Agent communication

- Structured message envelopes.
- Persistent message records.
- Message routing through the coordination layer.
- Message identifiers and correlation.
- Delivery acknowledgement.
- Idempotent message handling.

#### 10.2 Delegation

- Agent-to-agent task assignment.
- Task handoff.
- Delegation permissions.
- Result delivery.
- Failure and timeout handling.

#### 10.3 Agent teams

- Team creation and configuration.
- Hierarchical agent relationships.
- Shared team memory.
- Team-level task tracking.
- Independent and delegated agent execution.

#### 10.4 Coordination visibility

- Communication timelines.
- Delegation history.
- Team execution status.
- Agent-level execution details.
- Failure propagation and recovery.

### Exit criteria

- Agents can be organized into teams.
- Agents can delegate work to other authorized agents.
- All communication passes through Kairo's coordination layer.
- Messages and task state are persisted.
- Users can inspect communication and delegation history.
- Team execution failures are handled without losing task state.

## 11. Phase 8: Memory and Extensibility

**Objective:** Expand agent capabilities while maintaining clear platform boundaries.

### Deliverables

#### 11.1 Memory

- Private agent memory.
- Shared team memory.
- Structured memory records.
- Artifact-backed memory.
- Memory access controls.
- Memory lifecycle and retention.
- Memory inspection and management.

#### 11.2 Retrieval

- Initial database-backed retrieval.
- Full-text search.
- Optional embedding generation.
- Optional semantic retrieval.
- Replaceable retrieval interfaces.

A dedicated vector database is not required until actual workload requirements justify one.

#### 11.3 Extensibility

- Public API documentation.
- TypeScript SDK.
- Defined integration interfaces.
- Custom tool registration.
- Custom model provider adapters.
- Custom execution environments.
- External harness integration boundaries.

External frameworks and harnesses must integrate through explicit interfaces rather than becoming implicit dependencies of Kairo's native execution engine.

### Exit criteria

- Agent memory is scoped and permission-controlled.
- Shared memory is available to authorized team members.
- Large artifacts are stored outside PostgreSQL.
- Retrieval implementations can evolve without changing agent identity or execution contracts.
- External integrations use documented interfaces.

## 12. Phase 9: Production Readiness

**Objective:** Prepare Kairo for reliable self-hosted and managed deployments.

### Deliverables

#### 12.1 Deployment

- Production Docker Compose configuration.
- Environment and secret management.
- Database backup and restore.
- Object storage configuration.
- Container image versioning.
- Upgrade and migration procedures.

#### 12.2 Security

- Security testing.
- Authorization boundary testing.
- Container isolation testing.
- Credential handling review.
- Dependency scanning.
- API hardening.
- Audit coverage.

#### 12.3 Reliability

- Worker reconnection and reconciliation testing.
- Database failure testing.
- Object storage failure handling.
- Execution recovery testing.
- Graceful shutdown.
- Operational health checks.

#### 12.4 Documentation

- Installation guide.
- Configuration reference.
- Deployment guide.
- API documentation.
- Provider integration guide.
- Tool development guide.
- Worker setup guide.
- Troubleshooting guide.
- Contribution guide.

#### 12.5 Release

- Versioned releases.
- Published container images.
- Release notes.
- Upgrade instructions.
- Initial stable self-hosted release.

### Exit criteria

- A clean installation can be deployed using documented instructions.
- Database and object storage persistence work correctly.
- Upgrades and migrations are repeatable.
- Security and recovery tests pass.
- Workers can be added and removed safely.
- The platform can operate without development-only tooling.
- The release is documented and reproducible.

## 13. Milestone Summary

| Milestone | Result |
|---|---|
| M0 | Development foundation and shared contracts |
| M1 | Standalone native ReAct harness |
| M2 | Control plane and agent management |
| M3 | Distributed worker and isolated execution |
| M4 | Complete frontend user journey |
| M5 | Workspaces and GitHub coding workflows |
| M6 | Full observability and recovery |
| M7 | Multi-agent coordination |
| M8 | Memory and extensibility |
| M9 | Production-ready release |

## 14. Initial MVP Boundary

The first usable Kairo release should not wait for every capability in this roadmap.

The initial MVP consists of:

- User authentication.
- Agent creation and configuration.
- Cloud model provider integration.
- Ollama integration.
- Native ReAct harness.
- Tool registry and execution.
- Control plane.
- Worker registration and dispatch.
- Isolated Docker execution.
- Basic execution workspaces.
- Core frontend interface.
- Live execution updates.
- Execution history and structured event inspection.
- Basic resource limits and security controls.
- Docker Compose deployment.

GitHub integration, durable workspaces, advanced checkpoint recovery, multi-agent teams, and richer memory capabilities follow as subsequent milestones.

The MVP must still have real execution isolation, durable job coordination, and basic observability. These are foundational requirements, not optional polish.

## 15. Implementation Priority

The implementation order is dependency-driven:

1. Repository foundation and contracts.
2. Native harness and model provider interface.
3. Control plane and persistence.
4. Worker and container execution.
5. Frontend integration.
6. GitHub and workspace capabilities.
7. Observability and recovery.
8. Multi-agent coordination.
9. Memory and extensibility.
10. Production hardening and release.

Frontend work, tests, documentation, and security validation should proceed alongside the relevant backend milestones rather than being postponed until the end.

## 16. Roadmap Governance

This roadmap defines the intended development sequence and milestone boundaries.

Implementation details may be refined when technical validation reveals a concrete need, but changes must preserve the product requirements and architectural decisions.

A milestone is complete only when its exit criteria are met and its capabilities are integrated into the working platform.

Features must not be considered complete merely because their code exists. They must be tested in the context of the system they are intended to serve.
