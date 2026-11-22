import { fileURLToPath } from "node:url";
import { migrate } from "drizzle-orm/postgres-js/migrator";
import { checkDatabaseConnection, createDatabase, type Database } from "../src/db/client.ts";

const migrationsFolder = fileURLToPath(new URL("../drizzle", import.meta.url));
let database: Database | undefined;

try {
  database = createDatabase();
  await checkDatabaseConnection(database);
  await migrate(database.db, { migrationsFolder });
  console.log("Database migrations applied successfully.");
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
} finally {
  await database?.close();
}
