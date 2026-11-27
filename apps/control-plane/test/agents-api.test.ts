import { and, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createApp } from "../src/app.ts";
import { auditEvents } from "../src/db/schema.ts";
import { validAgentConfiguration } from "./helpers/agent-configuration.ts";
import { createTestDatabase, type TestDatabase } from "./helpers/database.ts";

interface UserResponse {
  id: string;
  email: string;
  displayName: string | null;
  createdAt: string;
}

interface LoginResponse {
  token: string;
  expiresAt: string;
  user: UserResponse;
}

interface OrganizationResponse {
  id: string;
  name: string;
  role: "owner" | "admin" | "member";
  createdAt: string;
}

interface AgentResponse {
  id: string;
  organizationId: string;
  name: string;
  description: string | null;
  status: "active" | "paused" | "archived";
  configuration: Record<string, unknown>;
  createdByUserId: string | null;
  createdAt: string;
  updatedAt: string;
}

let testDatabase: TestDatabase | undefined;
let app: FastifyInstance | undefined;

beforeAll(async () => {
  testDatabase = await createTestDatabase();
  app = await createApp(testDatabase.database, {
    logger: false,
    serverConfig: {
      host: "127.0.0.1",
      port: 3000,
      sessionTtlSeconds: 3600,
      logLevel: "silent",
    },
  });
  await app.ready();
});

afterAll(async () => {
  await app?.close();
  await testDatabase?.dispose();
});

function server(): FastifyInstance {
  if (!app) throw new Error("Control-plane application has not been created");
  return app;
}

function database(): TestDatabase {
  if (!testDatabase) throw new Error("Test database has not been created");
  return testDatabase;
}

function auth(token: string) {
  return { authorization: `Bearer ${token}` };
}

function agentUrl(organizationId: string, agentId?: string): string {
  const base = `/v1/organizations/${organizationId}/agents`;
  return agentId ? `${base}/${agentId}` : base;
}

async function register(email: string): Promise<UserResponse> {
  const response = await server().inject({
    method: "POST",
    url: "/v1/auth/register",
    payload: { email, password: "correct horse battery staple" },
  });
  expect(response.statusCode).toBe(201);
  return response.json() as UserResponse;
}

async function login(email: string): Promise<LoginResponse> {
  const response = await server().inject({
    method: "POST",
    url: "/v1/auth/login",
    payload: { email, password: "correct horse battery staple" },
  });
  expect(response.statusCode).toBe(200);
  return response.json() as LoginResponse;
}

async function setupUser(email: string): Promise<{ user: UserResponse; token: string }> {
  const user = await register(email);
  const { token } = await login(email);
  return { user, token };
}

async function createOrganization(token: string, name: string): Promise<OrganizationResponse> {
  const response = await server().inject({
    method: "POST",
    url: "/v1/organizations",
    headers: auth(token),
    payload: { name },
  });
  expect(response.statusCode).toBe(201);
  return response.json() as OrganizationResponse;
}

async function addMember(
  token: string,
  organizationId: string,
  email: string,
  role: "admin" | "member",
): Promise<void> {
  const response = await server().inject({
    method: "POST",
    url: `/v1/organizations/${organizationId}/members`,
    headers: auth(token),
    payload: { email, role },
  });
  expect(response.statusCode).toBe(201);
}

async function createAgent(
  token: string,
  organizationId: string,
  overrides: Record<string, unknown> = {},
): Promise<AgentResponse> {
  const response = await server().inject({
    method: "POST",
    url: agentUrl(organizationId),
    headers: auth(token),
    payload: { name: "Test Agent", configuration: validAgentConfiguration(), ...overrides },
  });
  expect(response.statusCode).toBe(201);
  return response.json() as AgentResponse;
}

describe("agent API", () => {
  it("creates, reads, updates, transitions, and archives an agent", async () => {
    const { token } = await setupUser("agent-lifecycle@example.com");
    const organization = await createOrganization(token, "Lifecycle Org");
    const agent = await createAgent(token, organization.id, { name: "Lifecycle Agent" });

    expect(agent.status).toBe("active");
    expect(agent.createdByUserId).toBeTypeOf("string");
    expect(agent.configuration).toMatchObject({
      modelProvider: "openai",
      model: "gpt-5",
      harnessVersion: "0.1.0",
      memoryScope: "private",
      grantedPermissions: ["filesystem.read"],
    });

    const list = await server().inject({
      method: "GET",
      url: agentUrl(organization.id),
      headers: auth(token),
    });
    expect(list.statusCode).toBe(200);
    expect((list.json() as { agents: AgentResponse[] }).agents).toHaveLength(1);

    const fetched = await server().inject({
      method: "GET",
      url: agentUrl(organization.id, agent.id),
      headers: auth(token),
    });
    expect(fetched.statusCode).toBe(200);
    expect((fetched.json() as AgentResponse).id).toBe(agent.id);

    const updated = await server().inject({
      method: "PATCH",
      url: agentUrl(organization.id, agent.id),
      headers: auth(token),
      payload: {
        name: "Renamed Agent",
        description: "Updated description",
        configuration: validAgentConfiguration(),
      },
    });
    expect(updated.statusCode).toBe(200);
    expect(updated.json()).toMatchObject({
      name: "Renamed Agent",
      description: "Updated description",
    });

    const paused = await server().inject({
      method: "PATCH",
      url: `${agentUrl(organization.id, agent.id)}/status`,
      headers: auth(token),
      payload: { status: "paused" },
    });
    expect(paused.statusCode).toBe(200);
    expect((paused.json() as AgentResponse).status).toBe("paused");

    const resumed = await server().inject({
      method: "PATCH",
      url: `${agentUrl(organization.id, agent.id)}/status`,
      headers: auth(token),
      payload: { status: "active" },
    });
    expect(resumed.statusCode).toBe(200);
    expect((resumed.json() as AgentResponse).status).toBe("active");

    const archived = await server().inject({
      method: "DELETE",
      url: agentUrl(organization.id, agent.id),
      headers: auth(token),
    });
    expect(archived.statusCode).toBe(204);

    const afterArchive = await server().inject({
      method: "GET",
      url: agentUrl(organization.id, agent.id),
      headers: auth(token),
    });
    expect((afterArchive.json() as AgentResponse).status).toBe("archived");

    const archivedAgain = await server().inject({
      method: "DELETE",
      url: agentUrl(organization.id, agent.id),
      headers: auth(token),
    });
    expect(archivedAgain.statusCode).toBe(204);

    const events = await database()
      .database.db.select({ action: auditEvents.action })
      .from(auditEvents)
      .where(and(eq(auditEvents.targetId, agent.id), eq(auditEvents.targetType, "agent")));
    const actions = events.map((event) => event.action);
    expect(actions).toContain("agent.created");
    expect(actions).toContain("agent.updated");
    expect(actions).toContain("agent.status_changed");
    expect(actions.filter((action) => action === "agent.archived")).toHaveLength(1);
  });

  it("enforces organization boundaries and creator ownership", async () => {
    const owner = await setupUser("agent-owner@example.com");
    const creator = await setupUser("agent-creator@example.com");
    const otherMember = await setupUser("agent-other-member@example.com");
    const admin = await setupUser("agent-admin@example.com");
    const outsider = await setupUser("agent-outsider@example.com");
    const organization = await createOrganization(owner.token, "Ownership Org");
    const otherOrganization = await createOrganization(outsider.token, "Outsider Org");
    await addMember(owner.token, organization.id, creator.user.email, "member");
    await addMember(owner.token, organization.id, otherMember.user.email, "member");
    await addMember(owner.token, organization.id, admin.user.email, "admin");

    const agent = await createAgent(creator.token, organization.id, { name: "Owned Agent" });

    const denied = await server().inject({
      method: "PATCH",
      url: agentUrl(organization.id, agent.id),
      headers: auth(otherMember.token),
      payload: { name: "Unauthorized Rename" },
    });
    expect(denied.statusCode).toBe(403);
    expect(denied.json()).toMatchObject({ error: { code: "FORBIDDEN" } });

    const adminUpdate = await server().inject({
      method: "PATCH",
      url: agentUrl(organization.id, agent.id),
      headers: auth(admin.token),
      payload: { name: "Admin Rename" },
    });
    expect(adminUpdate.statusCode).toBe(200);
    expect((adminUpdate.json() as AgentResponse).name).toBe("Admin Rename");

    const outsiderList = await server().inject({
      method: "GET",
      url: agentUrl(organization.id),
      headers: auth(outsider.token),
    });
    expect(outsiderList.statusCode).toBe(404);

    const outsiderCreate = await server().inject({
      method: "POST",
      url: agentUrl(organization.id),
      headers: auth(outsider.token),
      payload: { name: "Unauthorized Agent", configuration: validAgentConfiguration() },
    });
    expect(outsiderCreate.statusCode).toBe(404);

    const crossOrganizationGet = await server().inject({
      method: "GET",
      url: agentUrl(otherOrganization.id, agent.id),
      headers: auth(outsider.token),
    });
    expect(crossOrganizationGet.statusCode).toBe(404);
  });

  it("rejects invalid configurations without exposing secrets", async () => {
    const { token } = await setupUser("agent-validation@example.com");
    const organization = await createOrganization(token, "Validation Org");
    const configuration = validAgentConfiguration();
    const invalidConfigurations: unknown[] = [
      { ...configuration, apiKey: "super-secret" },
      { ...configuration, modelSettings: { temperature: 0.2, apiKey: "super-secret" } },
      { ...configuration, modelProvider: "unsupported" },
      {
        ...configuration,
        grantedPermissions: [],
        tools: [{ name: "filesystem.read", allowed: true, permissions: ["filesystem.read"] }],
      },
    ];

    for (const invalidConfiguration of invalidConfigurations) {
      const response = await server().inject({
        method: "POST",
        url: agentUrl(organization.id),
        headers: auth(token),
        payload: { name: "Invalid Agent", configuration: invalidConfiguration },
      });
      expect(response.statusCode, JSON.stringify(invalidConfiguration)).toBe(400);
      expect(response.json()).toMatchObject({ error: { code: "VALIDATION_ERROR" } });
      expect(JSON.stringify(response.json())).not.toContain("super-secret");
    }

    const list = await server().inject({
      method: "GET",
      url: agentUrl(organization.id),
      headers: auth(token),
    });
    expect((list.json() as { agents: AgentResponse[] }).agents).toEqual([]);
  });
});
