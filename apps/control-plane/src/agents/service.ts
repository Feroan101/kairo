import { and, eq } from "drizzle-orm";
import type { AgentConfiguration } from "../db/agent-configuration.ts";
import type { Database } from "../db/client.ts";
import { type agentStatus, agents } from "../db/schema.ts";
import { HttpError } from "../errors.ts";
import { recordAuditEvent } from "../identity/service.ts";
import { assertAgentManagementAccess } from "./authorization.ts";
import { validateAgentConfiguration } from "./configuration.ts";

export type AgentStatus = (typeof agentStatus.enumValues)[number];
type AgentRow = typeof agents.$inferSelect;

export interface AgentSummary {
  id: string;
  organizationId: string;
  name: string;
  description: string | null;
  status: AgentStatus;
  configuration: AgentConfiguration;
  createdByUserId: string | null;
  createdAt: Date;
  updatedAt: Date;
}

function summarize(row: AgentRow): AgentSummary {
  return {
    id: row.id,
    organizationId: row.organizationId,
    name: row.name,
    description: row.description,
    status: row.status,
    configuration: row.configuration,
    createdByUserId: row.createdByUserId,
    createdAt: row.createdAt,
    updatedAt: row.updatedAt,
  };
}

function validationError(message: string): HttpError {
  return new HttpError(400, "VALIDATION_ERROR", message);
}

export interface CreateAgentInput {
  organizationId: string;
  createdByUserId: string;
  name: string;
  description?: string | null;
  configuration: unknown;
}

export async function createAgent(
  database: Database,
  input: CreateAgentInput,
): Promise<AgentSummary> {
  const name = input.name.trim();
  if (!name) {
    throw validationError("Agent name is required");
  }

  const configuration = validateAgentConfiguration(input.configuration);
  const [agent] = await database.db
    .insert(agents)
    .values({
      organizationId: input.organizationId,
      createdByUserId: input.createdByUserId,
      name,
      description: input.description?.trim() || null,
      status: "active",
      configuration,
    })
    .returning();
  if (!agent) {
    throw new Error("Failed to create agent");
  }

  await recordAuditEvent(database, {
    action: "agent.created",
    actorUserId: input.createdByUserId,
    organizationId: input.organizationId,
    targetType: "agent",
    targetId: agent.id,
  });

  return summarize(agent);
}

export async function listAgents(
  database: Database,
  organizationId: string,
): Promise<AgentSummary[]> {
  const rows = await database.db
    .select()
    .from(agents)
    .where(eq(agents.organizationId, organizationId))
    .orderBy(agents.name);
  return rows.map(summarize);
}

export async function getAgent(
  database: Database,
  organizationId: string,
  agentId: string,
): Promise<AgentSummary | undefined> {
  const [row] = await database.db
    .select()
    .from(agents)
    .where(and(eq(agents.id, agentId), eq(agents.organizationId, organizationId)))
    .limit(1);
  return row ? summarize(row) : undefined;
}

export interface UpdateAgentInput {
  organizationId: string;
  agentId: string;
  actorUserId: string;
  name?: string;
  description?: string | null;
  configuration?: unknown;
}

export async function updateAgent(
  database: Database,
  input: UpdateAgentInput,
): Promise<AgentSummary | undefined> {
  await assertAgentManagementAccess(
    database,
    input.actorUserId,
    input.organizationId,
    input.agentId,
  );

  if (
    input.name === undefined &&
    input.description === undefined &&
    input.configuration === undefined
  ) {
    throw validationError("At least one agent field must be provided");
  }

  const values: Partial<Pick<AgentRow, "name" | "description" | "configuration">> = {};
  if (input.name !== undefined) {
    const name = input.name.trim();
    if (!name) {
      throw validationError("Agent name is required");
    }
    values.name = name;
  }
  if (input.description !== undefined) {
    values.description = input.description?.trim() || null;
  }
  if (input.configuration !== undefined) {
    values.configuration = validateAgentConfiguration(input.configuration);
  }

  const [row] = await database.db
    .update(agents)
    .set(values)
    .where(and(eq(agents.id, input.agentId), eq(agents.organizationId, input.organizationId)))
    .returning();
  if (!row) {
    return undefined;
  }

  await recordAuditEvent(database, {
    action: "agent.updated",
    actorUserId: input.actorUserId,
    organizationId: input.organizationId,
    targetType: "agent",
    targetId: input.agentId,
  });

  return summarize(row);
}

export async function setAgentStatus(
  database: Database,
  input: {
    organizationId: string;
    agentId: string;
    actorUserId: string;
    status: AgentStatus;
  },
): Promise<AgentSummary | undefined> {
  await assertAgentManagementAccess(
    database,
    input.actorUserId,
    input.organizationId,
    input.agentId,
  );

  const [row] = await database.db
    .update(agents)
    .set({ status: input.status })
    .where(and(eq(agents.id, input.agentId), eq(agents.organizationId, input.organizationId)))
    .returning();
  if (!row) {
    return undefined;
  }

  await recordAuditEvent(database, {
    action: "agent.status_changed",
    actorUserId: input.actorUserId,
    organizationId: input.organizationId,
    targetType: "agent",
    targetId: input.agentId,
  });

  return summarize(row);
}

export async function archiveAgent(
  database: Database,
  input: { organizationId: string; agentId: string; actorUserId: string },
): Promise<boolean> {
  const access = await assertAgentManagementAccess(
    database,
    input.actorUserId,
    input.organizationId,
    input.agentId,
  );
  if (access.agent.status === "archived") {
    return true;
  }

  const updated = await database.db
    .update(agents)
    .set({ status: "archived" })
    .where(and(eq(agents.id, input.agentId), eq(agents.organizationId, input.organizationId)))
    .returning({ id: agents.id });
  if (updated.length === 0) {
    return false;
  }

  await recordAuditEvent(database, {
    action: "agent.archived",
    actorUserId: input.actorUserId,
    organizationId: input.organizationId,
    targetType: "agent",
    targetId: input.agentId,
  });

  return true;
}
