import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { assertAgentManagementAccess, getAgentAccess } from "../src/agents/authorization.ts";
import { createAgent } from "../src/agents/service.ts";
import {
  addOrganizationMember,
  createOrganization,
  registerUser,
} from "../src/identity/service.ts";
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

describe("agent authorization", () => {
  it("allows owners, admins, and the creator to manage an agent", async () => {
    const db = database().database;
    const owner = await registerUser(db, {
      email: "auth-owner@example.com",
      password: "password1234",
    });
    const member = await registerUser(db, {
      email: "auth-member@example.com",
      password: "password1234",
    });
    const admin = await registerUser(db, {
      email: "auth-admin@example.com",
      password: "password1234",
    });
    const organization = await createOrganization(db, owner.id, "Auth Org");
    await addOrganizationMember(db, organization.id, member.email, "member");
    await addOrganizationMember(db, organization.id, admin.email, "admin");

    const agent = await createAgent(db, {
      organizationId: organization.id,
      createdByUserId: member.id,
      name: "Owned Agent",
      configuration: validAgentConfiguration(),
    });

    expect((await getAgentAccess(db, owner.id, organization.id, agent.id))?.canManage).toBe(true);
    expect((await getAgentAccess(db, admin.id, organization.id, agent.id))?.canManage).toBe(true);
    expect((await getAgentAccess(db, member.id, organization.id, agent.id))?.canManage).toBe(true);
    await expect(
      assertAgentManagementAccess(db, owner.id, organization.id, agent.id),
    ).resolves.toMatchObject({ canManage: true });
  });

  it("denies non-creator members and cross-organization access", async () => {
    const db = database().database;
    const owner = await registerUser(db, {
      email: "boundary-owner@example.com",
      password: "password1234",
    });
    const creator = await registerUser(db, {
      email: "boundary-creator@example.com",
      password: "password1234",
    });
    const otherMember = await registerUser(db, {
      email: "boundary-member@example.com",
      password: "password1234",
    });
    const outsider = await registerUser(db, {
      email: "boundary-outsider@example.com",
      password: "password1234",
    });
    const organization = await createOrganization(db, owner.id, "Boundary Org");
    const otherOrganization = await createOrganization(db, outsider.id, "Other Org");
    await addOrganizationMember(db, organization.id, creator.email, "member");
    await addOrganizationMember(db, organization.id, otherMember.email, "member");

    const agent = await createAgent(db, {
      organizationId: organization.id,
      createdByUserId: creator.id,
      name: "Boundary Agent",
      configuration: validAgentConfiguration(),
    });

    expect((await getAgentAccess(db, otherMember.id, organization.id, agent.id))?.canManage).toBe(
      false,
    );
    await expect(
      assertAgentManagementAccess(db, otherMember.id, organization.id, agent.id),
    ).rejects.toMatchObject({ statusCode: 403 });
    expect(await getAgentAccess(db, outsider.id, organization.id, agent.id)).toBeUndefined();
    await expect(
      assertAgentManagementAccess(db, outsider.id, organization.id, agent.id),
    ).rejects.toMatchObject({ statusCode: 404 });
    expect(await getAgentAccess(db, owner.id, otherOrganization.id, agent.id)).toBeUndefined();
  });
});
