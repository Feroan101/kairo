import { drizzle, type PostgresJsDatabase } from "drizzle-orm/postgres-js";
import postgres, { type Sql } from "postgres";
import { type DatabaseConfig, loadDatabaseConfig } from "./config.ts";
import * as schema from "./schema.ts";

export interface Database {
  readonly config: DatabaseConfig;
  readonly db: PostgresJsDatabase<typeof schema>;
  readonly sql: Sql;
  close(): Promise<void>;
}

function connectionOptions(config: DatabaseConfig) {
  return config.schema ? { options: `-c search_path=${config.schema},public` } : {};
}

export function createDatabase(config: DatabaseConfig = loadDatabaseConfig()): Database {
  const client = postgres(config.url, {
    max: 10,
    idle_timeout: 20,
    connect_timeout: 10,
    ...connectionOptions(config),
  });

  return {
    config,
    db: drizzle(client, { schema }),
    sql: client,
    close: () => client.end({ timeout: 5 }),
  };
}

function describeError(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export async function checkDatabaseConnection(database: Database): Promise<void> {
  try {
    await database.sql`select 1`;
  } catch (cause) {
    throw new Error(
      `Failed to connect to PostgreSQL at ${database.config.target}: ${describeError(cause)}`,
      { cause },
    );
  }
}
