import { Value } from "@sinclair/typebox/value";
import {
  type AgentConfiguration,
  AgentConfigurationSchema,
  type ExecutionPolicy,
} from "../db/agent-configuration.ts";
import { HttpError } from "../errors.ts";

const SUPPORTED_PROVIDERS = new Set(["anthropic", "gemini", "ollama", "openai"]);

export const DEFAULT_EXECUTION_POLICY: ExecutionPolicy = {
  maxIterations: 8,
  maxModelRequests: 8,
  maxToolCalls: 4,
  timeoutSeconds: 120,
};

function validationError(message: string): HttpError {
  return new HttpError(400, "VALIDATION_ERROR", message);
}

export function validateAgentConfiguration(input: unknown): AgentConfiguration {
  if (!Value.Check(AgentConfigurationSchema, input)) {
    throw validationError("Invalid agent configuration");
  }

  const configuration = Value.Clone(input) as AgentConfiguration;
  if (!configuration.modelProvider || !configuration.model || !configuration.harnessVersion) {
    throw validationError("Agent configuration requires a provider, model, and harness version");
  }

  if (!SUPPORTED_PROVIDERS.has(configuration.modelProvider)) {
    throw validationError(`Unsupported model provider: ${configuration.modelProvider}`);
  }

  const grantedPermissions = configuration.grantedPermissions ?? [];
  if (new Set(grantedPermissions).size !== grantedPermissions.length) {
    throw validationError("Granted permissions must not contain duplicates");
  }
  const granted = new Set(grantedPermissions);

  const tools = configuration.tools ?? [];
  const toolNames = new Set<string>();
  for (const tool of tools) {
    if (toolNames.has(tool.name)) {
      throw validationError(`Duplicate tool name: ${tool.name}`);
    }
    toolNames.add(tool.name);

    if (tool.allowed && tool.permissions.some((permission) => !granted.has(permission))) {
      throw validationError(`Tool ${tool.name} requires permissions that have not been granted`);
    }
  }

  return {
    ...configuration,
    tools,
    grantedPermissions,
    memoryScope: configuration.memoryScope ?? "private",
    executionPolicy: configuration.executionPolicy ?? DEFAULT_EXECUTION_POLICY,
  };
}
