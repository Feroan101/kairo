import { and, eq } from "drizzle-orm";
import type { Database } from "../db/client.ts";
import { agents } from "../db/schema.ts";
import { forbidden, notFound } from "../errors.ts";
import { hasRequiredRole, type OrganizationRole } from "../identity/roles.ts";
import { getOrganizationForUser } from "../identity/service.ts";

export interface AgentAccess {
  agent: typeof agents.$inferSelect;
  role: OrganizationRole;
  canManage: boolean;
}

export async function getAgentAccess(
  database: Database,
  userId: string,
  organizationId: string,
  agentId: string,
): Promise<AgentAccess | undefined> {
  const membership = await getOrganizationForUser(database, userId, organizationId);
  if (!membership) {
    return undefined;
  }

  const [agent] = await database.db
    .select()
    .from(agents)
    .where(and(eq(agents.id, agentId), eq(agents.organizationId, organizationId)))
    .limit(1);
  if (!agent) {
    return undefined;
  }

  return {
    agent,
    role: membership.role,
    canManage: hasRequiredRole(membership.role, "admin") || agent.createdByUserId === userId,
  };
}

export async function assertAgentManagementAccess(
  database: Database,
  userId: string,
  organizationId: string,
  agentId: string,
): Promise<AgentAccess> {
  const access = await getAgentAccess(database, userId, organizationId, agentId);
  if (!access) {
    throw notFound("Agent not found");
  }
  if (!access.canManage) {
    throw forbidden("Only the creator or an organization administrator can modify this agent");
  }
  return access;
}
