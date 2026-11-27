import type { AgentConfiguration } from "../../src/db/agent-configuration.ts";

export function validAgentConfiguration(): AgentConfiguration {
  return {
    modelProvider: "openai",
    model: "gpt-5",
    harnessVersion: "0.1.0",
    systemInstructions: "You are a helpful coding agent.",
    modelSettings: {
      temperature: 0.2,
      maxTokens: 4096,
      timeoutSeconds: 30,
      streamResponses: true,
    },
    tools: [{ name: "filesystem.read", allowed: true, permissions: ["filesystem.read"] }],
    grantedPermissions: ["filesystem.read"],
    executionPolicy: {
      maxIterations: 8,
      maxModelRequests: 8,
      maxToolCalls: 4,
      timeoutSeconds: 120,
    },
    memoryScope: "private",
  };
}
