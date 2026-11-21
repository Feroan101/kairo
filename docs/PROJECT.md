# Kairo

## Overview

Kairo is an open-source, cloud-native platform for building, running, and managing AI agents.

At its core, Kairo provides its own agent harness and cloud-based execution infrastructure. It aims to give agents the tools, context, environments, and capabilities they need to perform tasks while providing a platform to manage their execution and lifecycle.

Kairo will initially focus on coding agents, with the goal of eventually supporting a broader range of autonomous AI workloads.

## Core Direction

Kairo is built around three primary ideas:

### 1. Native Agent Infrastructure

Kairo will have its own agent harness, providing the execution loop, tool access, context management, permissions, and other capabilities required for agents to operate.

### 2. Agent Execution

Agents should execute in managed, isolated environments with access to the resources they need. Kairo will handle provisioning, execution, workspace management, and lifecycle operations.

### 3. Model Flexibility

Kairo should not be tied to a single AI provider or model. Its native agents should be able to use supported cloud AI providers through a flexible integration layer.

External agent harnesses and frameworks can be explored as the platform matures.

## Initial Scope

The initial development focus is:

- A native Kairo agent harness.
- Cloud-based agent execution.
- Isolated execution environments.
- Workspace and filesystem management.
- Tool integrations and permissions.
- Cloud AI provider integrations.
- Agent lifecycle management.
- Execution logs and observability.

## Long-Term Direction

Kairo should evolve into a general-purpose platform for autonomous AI workloads.

While coding agents are the initial focus, the underlying architecture should allow other types of agents and workloads to be supported without requiring a fundamental redesign.

## Design Principles

- **Open:** Core functionality should remain open source.
- **Extensible:** Components should support additional providers, tools, and agent implementations.
- **Isolated:** Agent executions should have clearly defined security boundaries.
- **Portable:** Avoid unnecessary dependence on a single cloud provider.
- **Composable:** Keep the harness, model integrations, and execution infrastructure appropriately separated.
- **Observable:** Agent execution should be inspectable and debuggable.

## Non-Goals

At the initial stage, Kairo is not intended to be:

- A foundation model or model-training platform.
- Another general-purpose chatbot.
- A replacement for every existing agent framework.
- A platform limited to a single AI provider.
- A generic cloud infrastructure management tool.
