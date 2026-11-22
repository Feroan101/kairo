import { type Static, Type } from "@sinclair/typebox";
import { Value } from "@sinclair/typebox/value";

const DatabaseEnvironmentSchema = Type.Object({
  DATABASE_URL: Type.String({ minLength: 1 }),
  DATABASE_SCHEMA: Type.Optional(Type.String({ pattern: "^[a-zA-Z_][a-zA-Z0-9_]*$" })),
});

type DatabaseEnvironment = Static<typeof DatabaseEnvironmentSchema>;

export interface DatabaseConfig {
  url: string;
  schema?: string;
  target: string;
}

function configurationError(env: NodeJS.ProcessEnv): string {
  const first = [...Value.Errors(DatabaseEnvironmentSchema, env)][0];
  if (!first) {
    return "DATABASE_URL is required";
  }
  return `${first.path || "configuration"}: ${first.message}`;
}

export function loadDatabaseConfig(env: NodeJS.ProcessEnv = process.env): DatabaseConfig {
  if (!Value.Check(DatabaseEnvironmentSchema, env)) {
    throw new Error(`Invalid database configuration: ${configurationError(env)}`);
  }

  const environment = env as DatabaseEnvironment;
  const rawUrl = environment.DATABASE_URL;
  if (!rawUrl) {
    throw new Error("Invalid database configuration: DATABASE_URL is required");
  }

  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new Error("Invalid database configuration: DATABASE_URL must be a valid URL");
  }

  if (parsed.protocol !== "postgres:" && parsed.protocol !== "postgresql:") {
    throw new Error("Invalid database configuration: DATABASE_URL must use postgres or postgresql");
  }

  const database = decodeURIComponent(parsed.pathname.slice(1));
  if (!parsed.hostname || !database) {
    throw new Error(
      "Invalid database configuration: DATABASE_URL must include a host and database",
    );
  }

  const user = parsed.username ? decodeURIComponent(parsed.username) : "unknown";
  const port = parsed.port || "5432";

  return {
    url: rawUrl,
    schema: environment.DATABASE_SCHEMA,
    target: `${parsed.hostname}:${port}/${database} (user: ${user})`,
  };
}
