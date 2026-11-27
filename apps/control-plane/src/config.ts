import { type Static, Type } from "@sinclair/typebox";
import { Value } from "@sinclair/typebox/value";

const ServerEnvironmentSchema = Type.Object({
  HOST: Type.Optional(Type.String({ minLength: 1 })),
  PORT: Type.Optional(Type.String({ pattern: "^[0-9]+$" })),
  SESSION_TTL_SECONDS: Type.Optional(Type.String({ pattern: "^[0-9]+$" })),
  LOG_LEVEL: Type.Optional(
    Type.Union([
      Type.Literal("fatal"),
      Type.Literal("error"),
      Type.Literal("warn"),
      Type.Literal("info"),
      Type.Literal("debug"),
      Type.Literal("trace"),
      Type.Literal("silent"),
    ]),
  ),
});

type ServerEnvironment = Static<typeof ServerEnvironmentSchema>;

export interface ServerConfig {
  host: string;
  port: number;
  sessionTtlSeconds: number;
  logLevel: ServerEnvironment["LOG_LEVEL"];
}

function invalid(message: string): never {
  throw new Error(`Invalid server configuration: ${message}`);
}

function boundedInteger(
  raw: string | undefined,
  name: string,
  min: number,
  max: number,
  defaultValue: number,
): number {
  if (raw === undefined) {
    return defaultValue;
  }
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    invalid(`${name} must be an integer between ${min} and ${max}`);
  }
  return value;
}

export function loadServerConfig(env: NodeJS.ProcessEnv = process.env): ServerConfig {
  if (!Value.Check(ServerEnvironmentSchema, env)) {
    const first = [...Value.Errors(ServerEnvironmentSchema, env)][0];
    invalid(`${first?.path || "configuration"}: ${first?.message ?? "invalid value"}`);
  }

  const environment = env as ServerEnvironment;
  return {
    host: environment.HOST ?? "127.0.0.1",
    port: boundedInteger(environment.PORT, "PORT", 1, 65535, 3000),
    sessionTtlSeconds: boundedInteger(
      environment.SESSION_TTL_SECONDS,
      "SESSION_TTL_SECONDS",
      60,
      2592000,
      604800,
    ),
    logLevel: environment.LOG_LEVEL ?? "info",
  };
}
