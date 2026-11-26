import { randomUUID } from "node:crypto";
import { and, eq, sql } from "drizzle-orm";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { AgentConfiguration } from "../src/db/agent-configuration.ts";
import {
  agents,
  auditEvents,
  organizationMemberships,
  organizations,
  sessions,
  users,
} from "../src/db/schema.ts";
import { createTestDatabase, type TestDatabase } from "./helpers/database.ts";

let testDatabase: TestDatabase | undefined;

beforeAll(async () => {
  testDatabase = await createTestDatabase();
});

afterAll(async () => {
  await testDatabase?.dispose();
});

function state(): TestDatabase {
  if (!testDatabase) {
    throw new Error("Test database has not been created");
  }
  return testDatabase;
}

function postgresErrorCode(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null) {
    return undefined;
  }
  const direct = (error as { code?: unknown }).code;
  if (typeof direct === "string") {
    return direct;
  }
  const cause = (error as { cause?: unknown }).cause;
  if (typeof cause === "object" && cause !== null) {
    const causeCode = (cause as { code?: unknown }).code;
    if (typeof causeCode === "string") {
      return causeCode;
    }
  }
  return undefined;
}

async function expectPostgresError(promise: Promise<unknown>, code: string): Promise<void> {
  try {
    await promise;
  } catch (error) {
    expect(postgresErrorCode(error)).toBe(code);
    return;
  }
  throw new Error(`Expected PostgreSQL error ${code}`);
}

function database() {
  return state().database.db;
}

async function insertUser(displayName = "Test User") {
  const [user] = await database()
    .insert(users)
    .values({ email: `${randomUUID()}@example.test`, displayName })
    .returning();
  if (!user) throw new Error("Failed to create test user");
  return user;
}

async function insertOrganization(name = "Test Organization") {
  const [organization] = await database().insert(organizations).values({ name }).returning();
  if (!organization) throw new Error("Failed to create test organization");
  return organization;
}

async function insertMembership(
  userId: string,
  organizationId: string,
  role: "owner" | "admin" | "member" = "member",
) {
  const [membership] = await database()
    .insert(organizationMemberships)
    .values({ userId, organizationId, role })
    .returning();
  if (!membership) throw new Error("Failed to create test membership");
  return membership;
}

async function insertAgent(organizationId: string, createdByUserId?: string, name = "Test Agent") {
  const [agent] = await database()
    .insert(agents)
    .values({ organizationId, createdByUserId, name })
    .returning();
  if (!agent) throw new Error("Failed to create test agent");
  return agent;
}

describe("PostgreSQL database foundation", () => {
  it("connects to the test database", async () => {
    const result = await database().execute<{ ok: number }>(sql`select 1 as ok`);
    expect(result[0]?.ok).toBe(1);
  });

  it("applies migrations and creates the expected tables", async () => {
    const tables = await database().execute<{ table_name: string }>(sql`
      select table_name
      from information_schema.tables
      where table_schema = 'public' and table_type = 'BASE TABLE'
      order by table_name
    `);
    expect(tables.map((row) => row.table_name)).toEqual([
      "agents",
      "audit_events",
      "organization_memberships",
      "organizations",
      "sessions",
      "users",
    ]);

    const userColumns = await database().execute<{
      column_name: string;
      data_type: string;
      is_nullable: string;
    }>(sql`
      select column_name, data_type, is_nullable
      from information_schema.columns
      where table_schema = 'public' and table_name = 'users'
      order by column_name
    `);
    const columns = new Map(userColumns.map((row) => [row.column_name, row]));
    expect(columns.get("id")?.data_type).toBe("uuid");
    expect(columns.get("created_at")?.data_type).toBe("timestamp with time zone");
    expect(columns.get("updated_at")?.data_type).toBe("timestamp with time zone");
    expect(columns.get("created_at")?.is_nullable).toBe("NO");

    const configurationColumn = await database().execute<{ data_type: string }>(sql`
      select data_type
      from information_schema.columns
      where table_schema = 'public' and table_name = 'agents' and column_name = 'configuration'
    `);
    expect(configurationColumn[0]?.data_type).toBe("jsonb");
  });

  it("enforces foreign key constraints", async () => {
    const user = await insertUser();
    const organization = await insertOrganization();

    await expectPostgresError(
      database()
        .insert(organizationMemberships)
        .values({ userId: randomUUID(), organizationId: organization.id, role: "member" }),
      "23503",
    );

    await expectPostgresError(
      database()
        .insert(organizationMemberships)
        .values({ userId: user.id, organizationId: randomUUID(), role: "member" }),
      "23503",
    );

    await expectPostgresError(
      database().insert(agents).values({ organizationId: randomUUID(), name: "Orphan Agent" }),
      "23503",
    );

    await expectPostgresError(
      database().insert(agents).values({
        organizationId: organization.id,
        createdByUserId: randomUUID(),
        name: "Invalid Creator Agent",
      }),
      "23503",
    );
  });

  it("prevents duplicate memberships", async () => {
    const user = await insertUser();
    const organization = await insertOrganization();
    await insertMembership(user.id, organization.id, "owner");

    await expectPostgresError(
      database()
        .insert(organizationMemberships)
        .values({ userId: user.id, organizationId: organization.id, role: "member" }),
      "23505",
    );
  });

  it("rejects sensitive agent configuration keys", async () => {
    const organization = await insertOrganization();

    await expectPostgresError(
      database()
        .insert(agents)
        .values({
          organizationId: organization.id,
          name: "Secret Agent",
          configuration: { apiKey: "do-not-store" } as unknown as AgentConfiguration,
        }),
      "23514",
    );
  });

  it("stores sessions and append-oriented audit events", async () => {
    const user = await insertUser("Session User");
    const tokenHash = "a".repeat(64);
    const [session] = await database()
      .insert(sessions)
      .values({ userId: user.id, tokenHash, expiresAt: new Date(Date.now() + 60_000) })
      .returning();

    expect(session?.userId).toBe(user.id);
    await expectPostgresError(
      database()
        .insert(sessions)
        .values({ userId: user.id, tokenHash, expiresAt: new Date(Date.now() + 60_000) }),
      "23505",
    );
    await expectPostgresError(
      database()
        .insert(sessions)
        .values({
          userId: user.id,
          tokenHash: "invalid",
          expiresAt: new Date(Date.now() + 60_000),
        }),
      "23514",
    );

    const [event] = await database()
      .insert(auditEvents)
      .values({ action: "auth.logged_in", actorUserId: user.id })
      .returning();
    expect(event?.action).toBe("auth.logged_in");
  });

  it("relates agents to their organization and creator", async () => {
    const owner = await insertUser("Owner");
    const organization = await insertOrganization("Relationship Org");
    await insertMembership(owner.id, organization.id, "owner");
    const agent = await insertAgent(organization.id, owner.id, "Relationship Agent");

    const rows = await database()
      .select({
        agentName: agents.name,
        organizationName: organizations.name,
        ownerEmail: users.email,
      })
      .from(agents)
      .innerJoin(organizations, eq(agents.organizationId, organizations.id))
      .innerJoin(users, eq(agents.createdByUserId, users.id))
      .where(eq(agents.id, agent.id));

    expect(rows).toEqual([
      {
        agentName: "Relationship Agent",
        organizationName: "Relationship Org",
        ownerEmail: owner.email,
      },
    ]);
  });

  it("supports CRUD operations for all initial entities", async () => {
    const user = await insertUser("CRUD User");
    const organization = await insertOrganization("CRUD Org");
    const membership = await insertMembership(user.id, organization.id, "owner");
    const agent = await insertAgent(organization.id, user.id, "CRUD Agent");

    const fetched = await database().select().from(agents).where(eq(agents.id, agent.id));
    expect(fetched[0]).toMatchObject({
      name: "CRUD Agent",
      status: "active",
      configuration: {},
      organizationId: organization.id,
      createdByUserId: user.id,
    });

    const configuration: AgentConfiguration = {
      modelProvider: "openai",
      model: "gpt-5",
      harnessVersion: "0.1.0",
      tools: [{ name: "filesystem.read", allowed: true, permissions: ["filesystem.read"] }],
    };
    const [updatedAgent] = await database()
      .update(agents)
      .set({ name: "Updated Agent", description: "Updated", status: "paused", configuration })
      .where(eq(agents.id, agent.id))
      .returning();
    expect(updatedAgent).toMatchObject({
      name: "Updated Agent",
      description: "Updated",
      status: "paused",
      configuration,
    });
    expect(updatedAgent?.updatedAt.getTime()).toBeGreaterThanOrEqual(agent.updatedAt.getTime());

    const [updatedMembership] = await database()
      .update(organizationMemberships)
      .set({ role: "admin" })
      .where(eq(organizationMemberships.id, membership.id))
      .returning();
    expect(updatedMembership?.role).toBe("admin");

    const [updatedOrganization] = await database()
      .update(organizations)
      .set({ name: "Updated Org" })
      .where(eq(organizations.id, organization.id))
      .returning();
    expect(updatedOrganization?.name).toBe("Updated Org");

    const [updatedUser] = await database()
      .update(users)
      .set({ displayName: "Updated User" })
      .where(eq(users.id, user.id))
      .returning();
    expect(updatedUser?.displayName).toBe("Updated User");

    await database().delete(agents).where(eq(agents.id, agent.id));
    await database()
      .delete(organizationMemberships)
      .where(eq(organizationMemberships.id, membership.id));
    await database().delete(organizations).where(eq(organizations.id, organization.id));
    await database().delete(users).where(eq(users.id, user.id));

    const remaining = await database()
      .select({ id: agents.id })
      .from(agents)
      .where(and(eq(agents.id, agent.id)));
    expect(remaining).toEqual([]);
  });

  it("uses safe deletion behavior", async () => {
    const user = await insertUser("Deletion User");
    const organization = await insertOrganization("Deletion Org");
    const membership = await insertMembership(user.id, organization.id, "owner");
    const agent = await insertAgent(organization.id, user.id, "Deletion Agent");

    await expectPostgresError(
      database().delete(organizations).where(eq(organizations.id, organization.id)),
      "23503",
    );

    await database().delete(users).where(eq(users.id, user.id));

    const remainingMemberships = await database()
      .select()
      .from(organizationMemberships)
      .where(eq(organizationMemberships.id, membership.id));
    expect(remainingMemberships).toEqual([]);

    const [agentAfterUserDeletion] = await database()
      .select()
      .from(agents)
      .where(eq(agents.id, agent.id));
    expect(agentAfterUserDeletion?.createdByUserId).toBeNull();

    await database().delete(agents).where(eq(agents.id, agent.id));
    await database().delete(organizations).where(eq(organizations.id, organization.id));

    const remainingOrganizations = await database()
      .select()
      .from(organizations)
      .where(eq(organizations.id, organization.id));
    expect(remainingOrganizations).toEqual([]);
  });
});
