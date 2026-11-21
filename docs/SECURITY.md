# Kairo Security

## 1. Purpose

This document defines the security model, boundaries, and mandatory safeguards for Kairo.

Kairo executes autonomous workloads, manages external integrations, and operates across users, organizations, agents, workers, and execution environments. Security must therefore be enforced at every boundary rather than relying on the agent harness or individual integrations to behave safely.

Security is a platform responsibility. Agents, tools, model providers, repository contents, and execution workloads must be treated as potentially untrusted.

## 2. Security Principles

Kairo follows these principles:

### Least Privilege

Every user, agent, worker, integration, and execution receives only the permissions required to perform its assigned responsibilities.

### Isolation by Default

Agent executions must be isolated from the host, other executions, and unrelated workspaces. Access between agents and resources must be explicitly authorized.

### Explicit Trust Boundaries

The control plane, workers, harnesses, containers, external providers, and user-controlled workloads have distinct trust levels. Crossing a boundary requires authentication, authorization, and validation.

### Defense in Depth

Security must not depend on a single control. Authentication, authorization, isolation, resource limits, credential protection, and auditing must reinforce one another.

### Secure Defaults

New installations and newly created resources must begin with restrictive settings. Additional permissions must be explicitly granted.

### Observable Security

Sensitive operations, permission changes, authentication events, and execution failures must produce auditable records without exposing secrets.

## 3. Threat Model

Kairo must account for the following threat categories.

### 3.1 Untrusted Agent Workloads

Agent-generated code, repository scripts, dependencies, and shell commands may be malicious or compromised.

Potential threats include:

- Attempts to access host files or processes.
- Attempts to escape container isolation.
- Unauthorized network connections.
- Credential extraction from environment variables or mounted files.
- Resource exhaustion through CPU, memory, disk, or process creation.
- Attempts to interfere with other executions.
- Attempts to access Docker or container runtime control interfaces.

### 3.2 Prompt Injection and Malicious Content

Agents may process untrusted instructions from repositories, documents, web pages, tool outputs, and other agents.

Potential threats include:

- Malicious instructions embedded in repository files.
- Attempts to override agent policies.
- Attempts to extract credentials or private memory.
- Attempts to induce unauthorized tool calls.
- Attempts to manipulate delegated agents through shared content.

Kairo must treat external content as data, not as an authority capable of changing permissions or system policy.

### 3.3 Unauthorized Access

Potential threats include:

- Access to another user's agents or executions.
- Access to resources belonging to another organization.
- Unauthorized access to private or shared memory.
- Unauthorized repository operations.
- Access to worker management interfaces.
- Privilege escalation through API or integration weaknesses.

### 3.4 Compromised Integrations

External model providers, tools, dependencies, and connected services may return malicious or unexpected data.

Kairo must validate integration responses and restrict the permissions available to integrations.

### 3.5 Infrastructure Compromise

Workers have access to the container runtime and are trusted infrastructure.

A compromised worker may expose execution data, credentials available to that worker, and workloads running on it. Kairo must minimize the impact of such a compromise through isolation, credential scoping, and deployment boundaries.

### 3.6 Availability Attacks

Agent workloads and external requests may intentionally or accidentally exhaust platform resources.

Kairo must enforce resource limits, request limits, execution timeouts, and scheduling constraints.

## 4. Identity and Access Management

### 4.1 User Authentication

- Protected platform operations must require authenticated users or authorized service identities.
- Authentication credentials must be stored securely.
- Session management must support expiration and revocation.
- Authentication failures must not reveal sensitive account information.
- Administrative operations must require appropriate privileges.

### 4.2 Authorization

Kairo must enforce authorization at the control plane and resource-access layers.

Authorization must account for:

- User identity.
- Organization membership.
- Organization role.
- Resource ownership.
- Agent permissions.
- Execution permissions.
- Integration-specific permissions.

Access must be denied by default when authorization cannot be established.

Frontend visibility is not an authorization mechanism. Every protected operation must be validated server-side.

### 4.3 Organization Isolation

- Organization resources must be scoped to their organization.
- Users must not access resources outside their membership and granted permissions.
- Organization membership changes must take effect for subsequent authorization checks.
- Organization administrators must not automatically receive access to external accounts or credentials beyond their granted scope.
- Cross-organization resource access must never occur implicitly.

### 4.4 Service Identity

Internal components must authenticate their communication.

- Workers must authenticate when connecting to the control plane.
- Worker identities must be unique and revocable.
- Internal APIs must validate the identity and permissions of the calling component.
- Agent identities must be distinct from harness runtime instances.
- Runtime instances must be associated with the agent and execution that created them.

## 5. Agent Permission Model

Agents must operate under explicit permission policies.

Permissions must define access to:

- Tools and integrations.
- Model providers.
- Workspaces and repositories.
- Private and shared memory.
- Other agents and team resources.
- Network destinations.
- Execution capabilities.
- Sensitive operations.

Permissions must be enforced by Kairo-controlled interfaces, not solely by instructions provided to the model.

### 5.1 Tool Permissions

- Tools must be explicitly registered and authorized.
- Each tool must declare its required permissions.
- The harness must validate tool access before execution.
- Tool arguments must be validated against their expected schema.
- Tool results must be treated as untrusted input.
- Sensitive tools must support additional approval or policy checks where appropriate.
- Tool execution must produce auditable events.

### 5.2 Delegation Permissions

- Agents may delegate only within their authorized scope.
- Delegated tasks must carry explicit task context and permissions.
- A receiving agent must not automatically inherit unrestricted permissions from the delegating agent.
- Sensitive operations must remain subject to the applicable authorization policy.
- Delegation must be recorded and traceable.

## 6. Execution Isolation

Agent workloads are untrusted and must execute in isolated containers.

### 6.1 Container Security

Execution containers must:

- Run as non-root users.
- Drop unnecessary Linux capabilities.
- Avoid privileged mode.
- Use read-only root filesystems where practical.
- Have restricted process privileges.
- Use explicit CPU, memory, disk, and process limits.
- Use isolated workspace mounts.
- Avoid mounting sensitive host paths.
- Never receive unrestricted access to the host Docker socket.
- Be terminated and cleaned up according to their lifecycle and retention policies.

### 6.2 Filesystem Isolation

- Each execution must receive only its authorized workspace.
- Host filesystem access must be restricted.
- Sensitive platform configuration must remain outside execution workspaces.
- Workspace mounts must use explicit access modes.
- Temporary files must be isolated between executions.
- Persistent workspace changes must be committed to durable storage through controlled mechanisms.

### 6.3 Network Isolation

- Execution network access must follow an explicit policy.
- Network restrictions must prevent unauthorized access to host services and internal infrastructure.
- Cloud metadata endpoints and sensitive internal services must be protected from execution workloads.
- Access to external services must be restricted where deployment policy requires it.
- Internal control-plane and worker interfaces must not be exposed directly to arbitrary execution containers.
- DNS and outbound traffic controls must be applied at the execution boundary where supported.

### 6.4 Resource Limits

Every execution must have enforceable resource limits.

These include:

- CPU allocation.
- Memory consumption.
- Disk usage.
- Process count.
- Execution duration.
- Network usage where supported.

Limits must be configurable by deployment administrators and applied before workloads begin execution.

Exceeding a limit must produce a controlled execution failure rather than destabilizing the worker.

### 6.5 Runtime Boundary

Workers control container creation and execution and are therefore trusted infrastructure.

- Execution containers must not control the worker's container runtime.
- Container lifecycle operations must be performed by the worker.
- Runtime interfaces must validate execution configuration.
- Workers must isolate execution data and credentials between workloads.
- A worker must not accept arbitrary privileged runtime configuration from an agent.

## 7. Credential and Secret Management

Kairo manages credentials for model providers, GitHub, external integrations, and internal services.

Credentials are high-value assets and must never be treated as ordinary agent context.

### 7.1 Credential Storage

- Credentials must be encrypted at rest.
- Encryption keys must be managed separately from encrypted credential data.
- Plaintext credentials must not be stored in logs, database records, or source control.
- Access to credential material must be restricted to authorized platform components.
- Credential access must be auditable.
- Credentials must support revocation and replacement.

### 7.2 Credential Injection

- Credentials must be provided only to components that require them.
- The control plane must not expose raw provider credentials to arbitrary agent workloads.
- Credentials must not be injected into execution containers by default.
- Tool integrations must use controlled credential access mechanisms.
- Execution-specific credentials must be short-lived or narrowly scoped where supported.
- Credentials must be removed when their authorized operation or execution ends.

### 7.3 Model Provider Credentials

- Provider credentials must be associated with their authorized user or organization scope.
- Agents must access models through the configured provider interface.
- Model credentials must not be included in prompts or tool results.
- Provider errors must be sanitized before being exposed to users or recorded in logs.

### 7.4 GitHub Credentials

- GitHub authorization must use the minimum required permissions.
- Users must explicitly authorize repositories and operations.
- Repository scripts must never receive unrestricted access to the connected GitHub credential.
- Git operations requiring authentication must be mediated by a controlled mechanism.
- Credentials must not be embedded in Git remotes, committed files, or execution logs.
- Users must be able to revoke GitHub access.

## 8. Model and Prompt Security

Models are external or locally served inference systems. Their outputs must not be trusted as executable policy.

- Model responses must be validated before tool execution.
- Tool calls must pass through the harness permission system.
- Model output must not modify authorization rules.
- Model output must not grant additional permissions.
- Provider responses must be treated as untrusted data.
- Model context must include only information authorized for the requesting agent.
- Sensitive information must not be added to model context unless required and authorized.
- Prompt injection defenses must operate alongside tool-level authorization rather than relying on prompt instructions alone.

## 9. Memory and Data Isolation

Memory must preserve the same security boundaries as other platform resources.

### 9.1 Private Memory

- Private memory must be accessible only to its owning agent and authorized platform components.
- Other agents must not access private memory without explicit authorization.
- Private memory must remain isolated across organizations.

### 9.2 Shared Memory

- Shared memory must be scoped to an explicitly defined team or organization boundary.
- Agents must receive only the shared memory records they are authorized to access.
- Memory writes must be attributable to the agent and execution that produced them.
- Shared memory must not grant permission to access unrelated resources.

### 9.3 Data Lifecycle

- Memory and artifacts must follow defined retention policies.
- Deletion operations must cover associated metadata and stored content.
- Checkpoints and workspace references must not preserve access to deleted or unauthorized resources.
- Access to sensitive memory must be auditable.

## 10. Multi-Agent Security

Multi-agent communication introduces additional trust boundaries.

- All agent messages must pass through the coordination layer.
- The coordination layer must authenticate the sender and validate the recipient.
- Message routing must respect team and organization boundaries.
- Agents must not impersonate other agents.
- Message identifiers and correlation information must be validated.
- Duplicate messages must not cause unauthorized repeated operations.
- Message payloads must be treated as untrusted input.
- Delegation must not implicitly transfer credentials or unrestricted permissions.
- Shared memory access must be independently authorized.
- Agents must not be able to bypass Kairo's policy enforcement through communication.

## 11. Worker and Control Plane Security

### 11.1 Control Plane

The control plane is responsible for authentication, authorization, orchestration, and durable platform state.

It must:

- Expose protected APIs over secure transport.
- Validate all incoming requests.
- Enforce authorization before resource access or state changes.
- Protect database credentials and encryption keys.
- Validate worker identities and execution assignments.
- Apply rate limits to sensitive and resource-intensive operations.
- Record administrative and security-relevant events.

### 11.2 Workers

Workers execute workloads and control the container runtime.

They must:

- Authenticate to the control plane.
- Accept only authorized execution assignments.
- Validate execution configuration before starting containers.
- Apply container isolation and resource limits.
- Keep temporary execution data isolated.
- Protect credentials available to the worker.
- Report execution state and health.
- Clean up abandoned or completed execution resources.
- Reject requests that require unauthorized host-level privileges.

### 11.3 Worker Communication

- Worker connections must use encrypted transport.
- Workers must authenticate using unique identities.
- Messages must be validated and associated with authorized executions.
- Reconnection must trigger state reconciliation.
- Expired leases must not authorize indefinite execution ownership.
- Worker credentials must be revocable.

## 12. API and Integration Security

- All protected API routes must require authorization.
- Request payloads must be validated.
- Resource identifiers must not be treated as proof of ownership.
- Sensitive endpoints must be rate-limited.
- API errors must not expose internal secrets or stack traces.
- Cross-origin access must be explicitly configured.
- WebSocket connections must authenticate and authorize subscriptions and messages.
- External integrations must use scoped permissions.
- Webhook signatures must be verified where supported.
- Integration callbacks must validate their origin and expected payload.

## 13. Data Protection

- Sensitive data must be encrypted in transit.
- Durable sensitive data must be encrypted at rest.
- Secrets must be excluded from ordinary logs and telemetry.
- Sensitive fields must be redacted before events are persisted or exported.
- Backups must be protected with access controls and encryption.
- Database access must use restricted service credentials.
- Object storage must use scoped access policies.
- Temporary files containing sensitive data must be removed when no longer required.
- Data retention and deletion policies must be enforceable.

## 14. Observability and Audit Security

Observability must provide visibility without creating a secondary source of credential leakage.

The system must:

- Record authentication and authorization failures.
- Record permission and configuration changes.
- Record credential access and revocation events.
- Record agent tool calls and sensitive operations.
- Record worker registration and execution assignments.
- Record recovery and administrative actions.
- Correlate security events with users, organizations, agents, and executions.
- Redact tokens, passwords, private keys, and other sensitive values.
- Restrict access to logs, traces, and audit records.
- Prevent agents from modifying or deleting authoritative audit records.

Audit records must be append-oriented and protected against unauthorized modification.

## 15. Deployment Security

Self-hosted and managed deployments must follow secure defaults.

- Services must expose only required network interfaces.
- Internal services must not be publicly exposed without a specific need.
- Database and object storage access must be restricted.
- Deployment secrets must be supplied through protected configuration mechanisms.
- Container images must use pinned and maintained dependencies.
- Images must be built from minimal base images where practical.
- Host operating systems and container runtimes must receive security updates.
- Administrative access must be restricted.
- Backups must be protected and periodically tested.
- Deployment documentation must identify required network access and sensitive configuration.

Kairo's default deployment must not require privileged application containers or unrestricted host access.

## 16. Failure and Incident Handling

Security failures must fail closed when authorization or isolation cannot be established.

- Invalid authentication must prevent access.
- Failed authorization must prevent the requested operation.
- Invalid execution configuration must prevent container startup.
- Uncertain credential state must prevent credential release.
- Worker identity failures must prevent job dispatch.
- Isolation failures must terminate or quarantine the affected execution.
- Suspected credential exposure must support revocation and rotation.
- Security-relevant failures must produce sanitized audit events.
- Administrators must be able to disable affected agents, workers, integrations, or credentials.

Recovery must never bypass security policy merely to resume an execution.

## 17. Security Testing

Security must be tested as part of the development lifecycle.

Testing must cover:

- Authentication and session handling.
- Organization and resource isolation.
- API authorization.
- Agent permission enforcement.
- Tool invocation authorization.
- Container privilege restrictions.
- Filesystem and network isolation.
- Resource limit enforcement.
- Credential storage and injection.
- Log and telemetry redaction.
- Multi-agent message authorization.
- Checkpoint and recovery safety.
- Worker authentication and lease handling.
- Integration input validation.

Critical security boundaries must have automated regression tests.

Container isolation and host protection must also be validated in the actual supported deployment environment, not only through mocked tests.

## 18. Security Boundaries

Kairo defines the following trust boundaries:

| Component | Trust level | Security responsibility |
|---|---|---|
| User and organization clients | Untrusted input | Authenticate and authorize every request |
| Control plane | Trusted platform component | Enforce identity, permissions, and orchestration policy |
| Worker | Trusted infrastructure | Enforce execution isolation and runtime controls |
| Native harness | Controlled execution component | Enforce agent and tool policies |
| Execution container | Untrusted workload | Remain isolated and resource-limited |
| Model provider | External dependency | Validate responses and protect credentials |
| Ollama endpoint | Configured external or local dependency | Restrict endpoint access and validate responses |
| Repository contents | Untrusted data | Prevent content from changing platform permissions |
| External tools | Permission-scoped integrations | Validate inputs, outputs, and authorization |
| Agent messages | Untrusted inter-agent data | Validate identity, scope, and routing |
| Memory and artifacts | Protected data | Enforce ownership and access policies |

## 19. Security Baseline

A deployment must not be considered production-ready unless it satisfies these minimum conditions:

1. Authentication and server-side authorization are enforced.
2. User and organization resources are isolated.
3. Workers authenticate to the control plane.
4. Agent workloads run in restricted containers.
5. Resource limits are applied to executions.
6. Host filesystem and container runtime access are restricted.
7. Credentials are encrypted and never exposed indiscriminately to agents.
8. GitHub operations use scoped authorization.
9. Memory and shared artifacts enforce access boundaries.
10. Agent communication passes through the coordination layer.
11. Logs and telemetry redact sensitive information.
12. Durable state and backups are protected.
13. Critical security boundaries have automated tests.
14. Security failures cannot silently bypass policy or isolation.

## 20. Security Governance

This document defines the security baseline for Kairo.

- Security controls apply to the native harness, workers, control plane, integrations, and deployment environments.
- New capabilities must preserve existing trust boundaries.
- New integrations must declare their required permissions and credential handling.
- New execution capabilities must undergo isolation and resource-limit review.
- Security-sensitive changes must include appropriate tests and documentation.
- Security weaknesses must be addressed before affected functionality is considered production-ready.

Security is a platform-wide requirement, not an optional configuration layer.
