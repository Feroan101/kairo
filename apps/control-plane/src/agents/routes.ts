import type { FastifyPluginAsyncTypebox } from "@fastify/type-provider-typebox";
import { Type } from "@sinclair/typebox";
import type { Database } from "../db/client.ts";
import { notFound } from "../errors.ts";
import { createOrganizationRoleHook, getAuthenticationContext } from "../identity/authorization.ts";
import { OrganizationIdParamsSchema } from "../identity/schemas.ts";
import {
  AgentListResponseSchema,
  AgentParamsSchema,
  AgentSchema,
  CreateAgentBodySchema,
  AgentErrorResponseSchema as ErrorResponseSchema,
  UpdateAgentBodySchema,
  UpdateAgentStatusBodySchema,
} from "./schemas.ts";
import {
  type AgentSummary,
  archiveAgent,
  createAgent,
  getAgent,
  listAgents,
  setAgentStatus,
  updateAgent,
} from "./service.ts";

export interface AgentRouteOptions {
  database: Database;
}

function agentResponse(agent: AgentSummary) {
  return {
    ...agent,
    createdAt: agent.createdAt.toISOString(),
    updatedAt: agent.updatedAt.toISOString(),
  };
}

export const agentRoutes: FastifyPluginAsyncTypebox<AgentRouteOptions> = async (app, options) => {
  const { database } = options;

  app.post(
    "/v1/organizations/:organizationId/agents",
    {
      preHandler: createOrganizationRoleHook(database, "member"),
      schema: {
        params: OrganizationIdParamsSchema,
        body: CreateAgentBodySchema,
        response: {
          201: AgentSchema,
          400: ErrorResponseSchema,
          401: ErrorResponseSchema,
          403: ErrorResponseSchema,
          404: ErrorResponseSchema,
        },
      },
    },
    async (request, reply) => {
      const context = getAuthenticationContext(request);
      const agent = await createAgent(database, {
        organizationId: request.params.organizationId,
        createdByUserId: context.userId,
        name: request.body.name,
        description: request.body.description,
        configuration: request.body.configuration,
      });
      return reply.code(201).send(agentResponse(agent));
    },
  );

  app.get(
    "/v1/organizations/:organizationId/agents",
    {
      preHandler: createOrganizationRoleHook(database, "member"),
      schema: {
        params: OrganizationIdParamsSchema,
        response: {
          200: AgentListResponseSchema,
          401: ErrorResponseSchema,
          403: ErrorResponseSchema,
          404: ErrorResponseSchema,
        },
      },
    },
    async (request) => {
      const agents = await listAgents(database, request.params.organizationId);
      return { agents: agents.map(agentResponse) };
    },
  );

  app.get(
    "/v1/organizations/:organizationId/agents/:agentId",
    {
      preHandler: createOrganizationRoleHook(database, "member"),
      schema: {
        params: AgentParamsSchema,
        response: {
          200: AgentSchema,
          401: ErrorResponseSchema,
          403: ErrorResponseSchema,
          404: ErrorResponseSchema,
        },
      },
    },
    async (request) => {
      const agent = await getAgent(database, request.params.organizationId, request.params.agentId);
      if (!agent) {
        throw notFound("Agent not found");
      }
      return agentResponse(agent);
    },
  );

  app.patch(
    "/v1/organizations/:organizationId/agents/:agentId",
    {
      preHandler: createOrganizationRoleHook(database, "member"),
      schema: {
        params: AgentParamsSchema,
        body: UpdateAgentBodySchema,
        response: {
          200: AgentSchema,
          400: ErrorResponseSchema,
          401: ErrorResponseSchema,
          403: ErrorResponseSchema,
          404: ErrorResponseSchema,
        },
      },
    },
    async (request) => {
      const context = getAuthenticationContext(request);
      const agent = await updateAgent(database, {
        organizationId: request.params.organizationId,
        agentId: request.params.agentId,
        actorUserId: context.userId,
        name: request.body.name,
        description: request.body.description,
        configuration: request.body.configuration,
      });
      if (!agent) {
        throw notFound("Agent not found");
      }
      return agentResponse(agent);
    },
  );

  app.patch(
    "/v1/organizations/:organizationId/agents/:agentId/status",
    {
      preHandler: createOrganizationRoleHook(database, "member"),
      schema: {
        params: AgentParamsSchema,
        body: UpdateAgentStatusBodySchema,
        response: {
          200: AgentSchema,
          400: ErrorResponseSchema,
          401: ErrorResponseSchema,
          403: ErrorResponseSchema,
          404: ErrorResponseSchema,
        },
      },
    },
    async (request) => {
      const context = getAuthenticationContext(request);
      const agent = await setAgentStatus(database, {
        organizationId: request.params.organizationId,
        agentId: request.params.agentId,
        actorUserId: context.userId,
        status: request.body.status,
      });
      if (!agent) {
        throw notFound("Agent not found");
      }
      return agentResponse(agent);
    },
  );

  app.delete(
    "/v1/organizations/:organizationId/agents/:agentId",
    {
      preHandler: createOrganizationRoleHook(database, "member"),
      schema: {
        params: AgentParamsSchema,
        response: {
          204: Type.Null(),
          401: ErrorResponseSchema,
          403: ErrorResponseSchema,
          404: ErrorResponseSchema,
        },
      },
    },
    async (request, reply) => {
      const context = getAuthenticationContext(request);
      const archived = await archiveAgent(database, {
        organizationId: request.params.organizationId,
        agentId: request.params.agentId,
        actorUserId: context.userId,
      });
      if (!archived) {
        throw notFound("Agent not found");
      }
      return reply.code(204).send(null);
    },
  );
};
