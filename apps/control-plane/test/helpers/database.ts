import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { migrate } from "drizzle-orm/postgres-js/migrator";
import postgres from "postgres";
import { createDatabase, type Database } from "../../src/db/client.ts";
import { loadDatabaseConfig } from "../../src/db/config.ts";

export interface TestDatabase {
  readonly database: Database;
  readonly databaseName: string;
  dispose(): Promise<void>;
}

function testDatabaseUrl(): string {
  const url = process.env.TEST_DATABASE_URL;
  if (!url) {
    throw new Error(
      "TEST_DATABASE_URL must point to a PostgreSQL database with CREATEDB privileges",
    );
  }
  return url;
}

function quotedIdentifier(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

export async function createTestDatabase(): Promise<TestDatabase> {
  const testUrl = testDatabaseUrl();
  const databaseName = `kairo_test_${randomUUID().replaceAll("-", "")}`;
  const admin = postgres(testUrl, { max: 1 });
  const databaseUrl = new URL(testUrl);
  databaseUrl.pathname = `/${databaseName}`;

  let database: Database | undefined;

  try {
    await admin.unsafe(`create database ${quotedIdentifier(databaseName)}`);
    database = createDatabase(loadDatabaseConfig({ DATABASE_URL: databaseUrl.toString() }));
    await migrate(database.db, {
      migrationsFolder: fileURLToPath(new URL("../../drizzle", import.meta.url)),
    });

    return {
      database,
      databaseName,
      dispose: async () => {
        await database?.close();
        await admin.unsafe(`drop database ${quotedIdentifier(databaseName)} with (force)`);
        await admin.end();
      },
    };
  } catch (error) {
    await database?.close();
    await admin
      .unsafe(`drop database ${quotedIdentifier(databaseName)} with (force)`)
      .catch(() => undefined);
    await admin.end();
    throw error;
  }
}
