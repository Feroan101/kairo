import { describe, expect, it } from "vitest";
import { loadDatabaseConfig } from "../src/db/config.ts";

describe("database configuration", () => {
  it("requires DATABASE_URL", () => {
    expect(() => loadDatabaseConfig({})).toThrow("DATABASE_URL");
  });

  it("rejects non-PostgreSQL URLs", () => {
    expect(() => loadDatabaseConfig({ DATABASE_URL: "sqlite://localhost/kairo.db" })).toThrow(
      "must use postgres or postgresql",
    );
  });

  it("does not expose the password in the connection target", () => {
    const config = loadDatabaseConfig({
      DATABASE_URL: "postgresql://kairo:do-not-log@localhost:5432/kairo",
    });
    expect(config.target).toBe("localhost:5432/kairo (user: kairo)");
    expect(config.target).not.toContain("do-not-log");
  });
});
