import { existsSync } from "node:fs";
import { defineConfig } from "drizzle-kit";

if (existsSync("../../.env")) {
  process.loadEnvFile("../../.env");
}

export default defineConfig({
  schema: "./src/db/schema.ts",
  out: "./drizzle",
  dialect: "postgresql",
  dbCredentials: {
    url: process.env.DATABASE_URL ?? "postgresql://kairo:kairo@localhost:5432/kairo",
  },
  strict: true,
  verbose: true,
});
