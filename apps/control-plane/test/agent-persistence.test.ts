import { eq } from "drizzle-orm";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { AgentConfiguration } from "../src/db/agent-configuration.ts";
import { agents } from "../src/db/schema.ts";
import { createOrganization, registerUser } from "../src/identity/service.ts";
import { validAgentConfiguration } from "./helpers/agent-configuration.ts";
import { createTestDatabase, type TestDatabase } from "./helpers/database.ts";

let testDatabase: TestDatabase | undefined;

beforeAll(async () => {
  testDatabase = await createTestDatabase();
});

afterAll(async () => {
  await testDatabase?.dispose();
});

function database(): TestDatabase {
  if (!testDatabase) throw new Error("Test database has not been created");
  return testDatabase;
}

describe("agent persistence", () => {
  it("round-trips validated configuration and lifecycle status", async () => {
    const db = database().database;
    const user = await registerUser(db, {
      email: "persist-owner@example.com",
      password: "password1234",
    });
    const organization = await createOrganization(db, user.id, "Persistence Org");
    const configuration = validAgentConfiguration();

    const [agent] = await db.db
      .insert(agents)
      .values({
        organizationId: organization.id,
        createdByUserId: user.id,
        name: "Persistent Agent",
        status: "active",
        configuration,
      })
      .returning();

    expect(agent?.configuration).toEqual(configuration);
    expect(agent?.status).toBe("active");
    if (!agent) throw new Error("Agent was not inserted");

    const [updated] = await db.db
      .update(agents)
      .set({ status: "paused", configuration: { ...configuration, memoryScope: "organization" } })
      .where(eq(agents.id, agent.id))
      .returning();
    expect(updated?.status).toBe("paused");
    expect(updated?.configuration.memoryScope).toBe("organization");
  });

  it("rejects secret-bearing configuration and invalid lifecycle status in PostgreSQL", async () => {
    const db = database().database;
    const user = await registerUser(db, {
      email: "persist-constraints@example.com",
      password: "password1234",
    });
    const organization = await createOrganization(db, user.id, "Constraints Org");
    const configuration = validAgentConfiguration();

    await expect(
      db.db.insert(agents).values({
        organizationId: organization.id,
        createdByUserId: user.id,
        name: "Secret Agent",
        configuration: { ...configuration, apiKey: "secret" } as AgentConfiguration,
      }),
    ).rejects.toMatchObject({ cause: { code: "23514" } });

    await expect(
      db.db.insert(agents).values({
        organizationId: organization.id,
        createdByUserId: user.id,
        name: "Invalid Status Agent",
        status: "deleted" as "active",
        configuration,
      }),
    ).rejects.toMatchObject({ cause: { code: "22P02" } });
  });
});
