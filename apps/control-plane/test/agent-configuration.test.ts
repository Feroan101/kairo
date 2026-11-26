import { describe, expect, it } from "vitest";
import {
  DEFAULT_EXECUTION_POLICY,
  validateAgentConfiguration,
} from "../src/agents/configuration.ts";
import { validAgentConfiguration } from "./helpers/agent-configuration.ts";

describe("agent configuration validation", () => {
  it("normalizes a complete configuration and applies defaults", () => {
    const configuration = validateAgentConfiguration({
      modelProvider: "ollama",
      model: "qwen3-coder",
      harnessVersion: "0.1.0",
    });

    expect(configuration.modelProvider).toBe("ollama");
    expect(configuration.memoryScope).toBe("private");
    expect(configuration.tools).toEqual([]);
    expect(configuration.grantedPermissions).toEqual([]);
    expect(configuration.executionPolicy).toEqual(DEFAULT_EXECUTION_POLICY);
  });

  it("accepts a permitted tool configuration", () => {
    expect(() => validateAgentConfiguration(validAgentConfiguration())).not.toThrow();
  });

  it("rejects unsupported providers", () => {
    expect(() =>
      validateAgentConfiguration({ ...validAgentConfiguration(), modelProvider: "unknown" }),
    ).toThrowError(/Unsupported model provider/);
  });

  it("rejects secret-bearing configuration keys", () => {
    expect(() =>
      validateAgentConfiguration({ ...validAgentConfiguration(), apiKey: "secret" }),
    ).toThrowError(/Invalid agent configuration/);
    expect(() =>
      validateAgentConfiguration({
        ...validAgentConfiguration(),
        modelSettings: { apiKey: "secret" },
      }),
    ).toThrowError(/Invalid agent configuration/);
  });

  it("rejects duplicate tool names and granted permissions", () => {
    const configuration = validAgentConfiguration();
    expect(() =>
      validateAgentConfiguration({
        ...configuration,
        tools: [...(configuration.tools ?? []), configuration.tools?.[0]],
      }),
    ).toThrowError(/Duplicate tool name/);
    expect(() =>
      validateAgentConfiguration({
        ...configuration,
        grantedPermissions: ["filesystem.read", "filesystem.read"],
      }),
    ).toThrowError(/duplicates/);
  });

  it("rejects permissions that have not been granted to an allowed tool", () => {
    const configuration = validAgentConfiguration();
    expect(() =>
      validateAgentConfiguration({ ...configuration, grantedPermissions: [] }),
    ).toThrowError(/have not been granted/);
  });

  it("rejects invalid provider, model, and permission identifiers", () => {
    const configuration = validAgentConfiguration();
    expect(() =>
      validateAgentConfiguration({ ...configuration, modelProvider: "OpenAI" }),
    ).toThrowError(/Invalid agent configuration/);
    expect(() =>
      validateAgentConfiguration({ ...configuration, model: "model name!" }),
    ).toThrowError(/Invalid agent configuration/);
    expect(() =>
      validateAgentConfiguration({ ...configuration, grantedPermissions: ["Read"] }),
    ).toThrowError(/Invalid agent configuration/);
  });
});
