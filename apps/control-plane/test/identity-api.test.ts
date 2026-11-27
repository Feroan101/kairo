import { randomUUID } from "node:crypto";
import { and, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createApp } from "../src/app.ts";
import { auditEvents } from "../src/db/schema.ts";
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

async function register(email: string, displayName?: string): Promise<UserResponse> {
  const response = await server().inject({
    method: "POST",
    url: "/v1/auth/register",
    payload: { email, password: "correct horse battery staple", displayName },
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
) {
  const response = await server().inject({
    method: "POST",
    url: `/v1/organizations/${organizationId}/members`,
    headers: auth(token),
    payload: { email, role },
  });
  expect(response.statusCode).toBe(201);
}

describe("identity API", () => {
  it("exposes public health and OpenAPI endpoints", async () => {
    const health = await server().inject({ method: "GET", url: "/health" });
    expect(health.statusCode).toBe(200);

    const openapi = await server().inject({ method: "GET", url: "/openapi.json" });
    expect(openapi.statusCode).toBe(200);
    const document = openapi.json() as { paths: Record<string, unknown> };
    expect(document.paths).toHaveProperty("/v1/auth/register");
    expect(document.paths).toHaveProperty("/v1/organizations");
  });

  it("registers users and rejects duplicate or invalid registrations", async () => {
    const email = `alice-${randomUUID()}@example.test`;
    const user = await register(email, "Alice");
    expect(user.email).toBe(email);
    expect(user.displayName).toBe("Alice");

    const duplicate = await server().inject({
      method: "POST",
      url: "/v1/auth/register",
      payload: { email: email.toUpperCase(), password: "correct horse battery staple" },
    });
    expect(duplicate.statusCode).toBe(409);

    const invalid = await server().inject({
      method: "POST",
      url: "/v1/auth/register",
      payload: { email: "not-an-email", password: "short" },
    });
    expect(invalid.statusCode).toBe(400);
  });

  it("authenticates with a session token and rejects bad credentials", async () => {
    const email = `bob-${randomUUID()}@example.test`;
    await register(email);
    const session = await login(email);

    expect(session.token).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(session.user.email).toBe(email);

    const me = await server().inject({
      method: "GET",
      url: "/v1/auth/me",
      headers: auth(session.token),
    });
    expect(me.statusCode).toBe(200);
    expect((me.json() as UserResponse).id).toBe(session.user.id);

    const wrongPassword = await server().inject({
      method: "POST",
      url: "/v1/auth/login",
      payload: { email, password: "incorrect password" },
    });
    expect(wrongPassword.statusCode).toBe(401);

    const anonymous = await server().inject({ method: "GET", url: "/v1/auth/me" });
    expect(anonymous.statusCode).toBe(401);

    const forged = await server().inject({
      method: "GET",
      url: "/v1/auth/me",
      headers: auth("not-a-valid-session-token"),
    });
    expect(forged.statusCode).toBe(401);
  });

  it("lists and revokes sessions independently", async () => {
    const email = `sessions-${randomUUID()}@example.test`;
    await register(email);
    const first = await login(email);
    const second = await login(email);

    const sessions = await server().inject({
      method: "GET",
      url: "/v1/auth/sessions",
      headers: auth(first.token),
    });
    expect(sessions.statusCode).toBe(200);
    const list = sessions.json() as { sessions: { id: string }[] };
    expect(list.sessions).toHaveLength(2);

    const sessionId = list.sessions[0]?.id;
    expect(sessionId).toBeDefined();
    if (!sessionId) return;

    const revoke = await server().inject({
      method: "DELETE",
      url: `/v1/auth/sessions/${sessionId}`,
      headers: auth(first.token),
    });
    expect(revoke.statusCode).toBe(204);

    const revoked = await server().inject({
      method: "GET",
      url: "/v1/auth/me",
      headers: auth(first.token),
    });
    expect(revoked.statusCode).toBe(401);
    const remaining = await server().inject({
      method: "GET",
      url: "/v1/auth/me",
      headers: auth(second.token),
    });
    expect(remaining.statusCode).toBe(200);

    const logout = await server().inject({
      method: "POST",
      url: "/v1/auth/logout",
      headers: auth(second.token),
    });
    expect(logout.statusCode).toBe(204);
    const afterLogout = await server().inject({
      method: "GET",
      url: "/v1/auth/me",
      headers: auth(second.token),
    });
    expect(afterLogout.statusCode).toBe(401);
  });
});

describe("organization access", () => {
  it("scopes organizations to their members", async () => {
    const ownerEmail = `owner-${randomUUID()}@example.test`;
    const outsiderEmail = `outsider-${randomUUID()}@example.test`;
    const owner = await register(ownerEmail);
    await register(outsiderEmail);
    const ownerToken = (await login(ownerEmail)).token;
    const outsiderToken = (await login(outsiderEmail)).token;
    const organization = await createOrganization(ownerToken, "Scoped Org");

    const owned = await server().inject({
      method: "GET",
      url: `/v1/organizations/${organization.id}`,
      headers: auth(ownerToken),
    });
    expect(owned.statusCode).toBe(200);

    const outsiderView = await server().inject({
      method: "GET",
      url: `/v1/organizations/${organization.id}`,
      headers: auth(outsiderToken),
    });
    expect(outsiderView.statusCode).toBe(404);

    const outsiderList = await server().inject({
      method: "GET",
      url: "/v1/organizations",
      headers: auth(outsiderToken),
    });
    expect(outsiderList.statusCode).toBe(200);
    expect((outsiderList.json() as { organizations: unknown[] }).organizations).toEqual([]);

    const members = await server().inject({
      method: "GET",
      url: `/v1/organizations/${organization.id}/members`,
      headers: auth(ownerToken),
    });
    expect(members.statusCode).toBe(200);
    const memberList = members.json() as {
      members: { userId: string; email: string; role: string }[];
    };
    expect(memberList.members).toHaveLength(1);
    expect(memberList.members[0]).toMatchObject({
      userId: owner.id,
      email: ownerEmail,
      role: "owner",
    });
  });

  it("enforces owner and admin role requirements", async () => {
    const ownerEmail = `role-owner-${randomUUID()}@example.test`;
    const memberEmail = `role-member-${randomUUID()}@example.test`;
    const owner = await register(ownerEmail);
    const member = await register(memberEmail);
    const ownerToken = (await login(ownerEmail)).token;
    const memberToken = (await login(memberEmail)).token;
    const organization = await createOrganization(ownerToken, "Role Org");
    await addMember(ownerToken, organization.id, memberEmail, "member");

    const memberAttempt = await server().inject({
      method: "PATCH",
      url: `/v1/organizations/${organization.id}/members/${member.id}`,
      headers: auth(memberToken),
      payload: { role: "admin" },
    });
    expect(memberAttempt.statusCode).toBe(403);

    const lastOwnerAttempt = await server().inject({
      method: "PATCH",
      url: `/v1/organizations/${organization.id}/members/${owner.id}`,
      headers: auth(ownerToken),
      payload: { role: "member" },
    });
    expect(lastOwnerAttempt.statusCode).toBe(409);

    const promote = await server().inject({
      method: "PATCH",
      url: `/v1/organizations/${organization.id}/members/${member.id}`,
      headers: auth(ownerToken),
      payload: { role: "admin" },
    });
    expect(promote.statusCode).toBe(200);

    const adminAttempt = await server().inject({
      method: "PATCH",
      url: `/v1/organizations/${organization.id}/members/${owner.id}`,
      headers: auth(memberToken),
      payload: { role: "member" },
    });
    expect(adminAttempt.statusCode).toBe(409);

    const removal = await server().inject({
      method: "DELETE",
      url: `/v1/organizations/${organization.id}/members/${member.id}`,
      headers: auth(ownerToken),
    });
    expect(removal.statusCode).toBe(204);

    const removedView = await server().inject({
      method: "GET",
      url: `/v1/organizations/${organization.id}`,
      headers: auth(memberToken),
    });
    expect(removedView.statusCode).toBe(404);
  });

  it("records authorization denials in append-only audit events", async () => {
    const ownerEmail = `audit-owner-${randomUUID()}@example.test`;
    const outsiderEmail = `audit-outsider-${randomUUID()}@example.test`;
    await register(ownerEmail);
    const ownerToken = (await login(ownerEmail)).token;
    await register(outsiderEmail);
    const outsiderToken = (await login(outsiderEmail)).token;
    const organization = await createOrganization(ownerToken, "Audit Org");

    const denied = await server().inject({
      method: "GET",
      url: `/v1/organizations/${organization.id}`,
      headers: auth(outsiderToken),
    });
    expect(denied.statusCode).toBe(404);

    const events = await database()
      .database.db.select()
      .from(auditEvents)
      .where(
        and(
          eq(auditEvents.action, "authorization.denied"),
          eq(auditEvents.organizationId, organization.id),
        ),
      );
    expect(events.length).toBeGreaterThan(0);
  });
});
