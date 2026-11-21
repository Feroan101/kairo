# Product

## Overview

Kairo is a platform for building, running, and managing AI agents. It provides a native agent harness, managed execution environments, model integrations, and tools for working with real projects.

Users can configure agents, connect their preferred AI models, give agents access to repositories and workspaces, and monitor their execution through Kairo.

Kairo initially focuses on coding agents while supporting a broader range of autonomous workloads.

## Core Capabilities

### 1. Agent Management

Users can create, configure, run, stop, and manage agents through Kairo.

Each agent has a configurable model, execution environment, workspace, and set of available tools and permissions.

### 2. Native Agent Harness

Kairo provides its own agent harness, responsible for:

- Managing the agent execution loop.
- Providing tool access and handling tool calls.
- Managing context and conversation state.
- Enforcing permissions and execution boundaries.
- Interacting with configured models.
- Reporting execution events and results.

Native Kairo agents use this harness to perform tasks within their assigned environments.

### 3. Model Providers

Kairo supports both cloud-hosted AI models and locally served models.

**Cloud providers**

Users can connect supported AI providers and select from the models available through each provider. Kairo presents the available model options so users can choose the model that best fits their workload.

Provider integrations handle authentication, model discovery, and communication with the selected model.

**Local models**

Users can connect an Ollama server and use models served through it. This allows agents to run with locally hosted models instead of relying on a cloud AI provider.

Model configuration belongs to the agent, allowing different agents to use different providers and models.

### 4. Execution Environments

Agents execute inside managed, isolated environments with access to the resources required for their tasks.

Kairo manages environment provisioning, execution, and cleanup while maintaining boundaries between agent workloads.

### 5. Workspaces and Repository Access

Agents work within dedicated workspaces containing the files and project context relevant to their tasks.

Kairo supports GitHub integration for repository access and source control workflows.

With the appropriate permissions, agents can:

- Access connected repositories.
- Inspect and modify source files.
- Create branches and commit changes.
- Push changes to GitHub.
- Open pull requests using the connected GitHub identity.

Users retain control over which repositories and permissions are granted to agents. Actions performed through GitHub follow the authorization of the connected account or integration.

### 6. Orchestration

Kairo manages agent execution and lifecycle operations across its execution infrastructure.

This includes starting and stopping agents, managing active executions, handling execution states, and coordinating the resources assigned to workloads.

### 7. Observability

Execution visibility is a core part of Kairo. Users should be able to understand what their agents are doing, what they have done, and what happened when something fails.

Kairo provides visibility into:

- Agent status and execution state.
- Live execution logs and events.
- Tool calls and their results.
- Model interactions and token usage, where available.
- Execution history and task outcomes.
- Errors, failures, and relevant diagnostics.
- Resource consumption and execution duration.

Observability should make agent behaviour inspectable and help users debug, evaluate, and understand their workloads.

### 8. Extensibility

Kairo is built to support additional model providers, tools, integrations, and agent implementations.

Its native harness is a first-class part of the platform. External agent harnesses and frameworks can also integrate with Kairo, allowing users to bring different agent implementations into its execution infrastructure.

## Intended Users

Kairo is intended for:

- Developers building and running AI coding agents.
- Individuals who want to run agents in managed or self-hosted environments.
- Teams that need to manage multiple agents and their executions.
- Developers experimenting with different models, providers, and agent implementations.
- Users who want visibility and control over autonomous AI workloads.

## Design Principles

- **Open:** Core platform functionality remains open source.
- **Self-hostable:** Users can operate Kairo on infrastructure they control.
- **Cloud-native:** Execution and orchestration are designed for cloud environments.
- **Model-agnostic:** Users choose between supported cloud providers and local models.
- **Extensible:** Providers, tools, and agent implementations can be integrated.
- **Isolated:** Agent workloads operate within defined security boundaries.
- **Observable:** Agent activity and execution outcomes are visible to users.
- **Composable:** The harness, model integrations, workspaces, and execution infrastructure remain distinct components.
