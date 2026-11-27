import { createApp } from "./app.ts";
import { loadServerConfig } from "./config.ts";
import { checkDatabaseConnection, createDatabase, type Database } from "./db/client.ts";

async function main(): Promise<void> {
  const config = loadServerConfig();
  const database: Database = createDatabase();
  let started = false;

  try {
    await checkDatabaseConnection(database);
    const app = await createApp(database, { serverConfig: config });
    await app.listen({ host: config.host, port: config.port });
    started = true;

    let shuttingDown: Promise<void> | undefined;
    const shutdown = (signal: string) => {
      if (shuttingDown) {
        return;
      }
      shuttingDown = (async () => {
        app.log.info({ signal }, "Shutting down control plane");
        await app.close();
        await database.close();
      })().finally(() => {
        process.exitCode = 0;
      });
    };

    process.on("SIGINT", () => shutdown("SIGINT"));
    process.on("SIGTERM", () => shutdown("SIGTERM"));
  } finally {
    if (!started) {
      await database.close();
    }
  }
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
