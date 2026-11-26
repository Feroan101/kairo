import type { FastifyPluginAsyncTypebox } from "@fastify/type-provider-typebox";
import { Type } from "@sinclair/typebox";
import type { Database } from "../db/client.ts";
import { notFound } from "../errors.ts";
import { createOrganizationRoleHook, getAuthenticationContext } from "./authorization.ts";
import {
  AddMemberBodySchema,
  CreateOrganizationBodySchema,
  ErrorResponseSchema,
  MemberListResponseSchema,
  MemberParamsSchema,
  OrganizationIdParamsSchema,
  OrganizationListResponseSchema,
  OrganizationMemberSchema,
  OrganizationSchema,
  UpdateMemberRoleBodySchema,
} from "./schemas.ts";
import {
  addOrganizationMember,
  changeMemberRole,
  createOrganization,
  getOrganizationForUser,
  listOrganizationMembers,
  listUserOrganizations,
  recordAuditEvent,
  removeMember,
} from "./service.ts";

export interface OrganizationRouteOptions {
  database: Database;
}

export const organizationRoutes: FastifyPluginAsyncTypebox<OrganizationRouteOptions> = async (
  app,
  options,
) => {
  const { database } = options;

  app.post(
    "/v1/organizations",
    {
      schema: {
        body: CreateOrganizationBodySchema,
        response: {
          201: OrganizationSchema,
          400: ErrorResponseSchema,
          401: ErrorResponseSchema,
        },
      },
    },
    async (request, reply) => {
      const context = getAuthenticationContext(request);
      const organization = await createOrganization(database, context.userId, request.body.name);
      return reply
        .code(201)
        .send({ ...organization, createdAt: organization.createdAt.toISOString() });
    },
  );

  app.get(
    "/v1/organizations",
    {
      schema: { response: { 200: OrganizationListResponseSchema, 401: ErrorResponseSchema } },
    },
    async (request) => {
      const context = getAuthenticationContext(request);
      const organizations = await listUserOrganizations(database, context.userId);
      return {
        organizations: organizations.map((organization) => ({
          ...organization,
          createdAt: organization.createdAt.toISOString(),
        })),
      };
    },
  );

  app.get(
    "/v1/organizations/:organizationId",
    {
      preHandler: createOrganizationRoleHook(database, "member"),
      schema: {
        params: OrganizationIdParamsSchema,
        response: {
          200: OrganizationSchema,
          401: ErrorResponseSchema,
          403: ErrorResponseSchema,
          404: ErrorResponseSchema,
        },
      },
    },
    async (request) => {
      const context = getAuthenticationContext(request);
      const organization = await getOrganizationForUser(
        database,
        context.userId,
        request.params.organizationId,
      );
      if (!organization) {
        throw notFound("Organization not found");
      }
      return { ...organization, createdAt: organization.createdAt.toISOString() };
    },
  );

  app.get(
    "/v1/organizations/:organizationId/members",
    {
      preHandler: createOrganizationRoleHook(database, "member"),
      schema: {
        params: OrganizationIdParamsSchema,
        response: {
          200: MemberListResponseSchema,
          401: ErrorResponseSchema,
          403: ErrorResponseSchema,
          404: ErrorResponseSchema,
        },
      },
    },
    async (request) => {
      const members = await listOrganizationMembers(database, request.params.organizationId);
      return {
        members: members.map((member) => ({
          ...member,
          joinedAt: member.joinedAt.toISOString(),
        })),
      };
    },
  );

  app.post(
    "/v1/organizations/:organizationId/members",
    {
      preHandler: createOrganizationRoleHook(database, "admin"),
      schema: {
        params: OrganizationIdParamsSchema,
        body: AddMemberBodySchema,
        response: {
          201: OrganizationMemberSchema,
          400: ErrorResponseSchema,
          401: ErrorResponseSchema,
          403: ErrorResponseSchema,
          404: ErrorResponseSchema,
          409: ErrorResponseSchema,
        },
      },
    },
    async (request, reply) => {
      const context = getAuthenticationContext(request);
      const member = await addOrganizationMember(
        database,
        request.params.organizationId,
        request.body.email,
        request.body.role,
      );
      if (!member) {
        throw notFound("User not found");
      }
      await recordAuditEvent(database, {
        action: "organization.member_added",
        actorUserId: context.userId,
        organizationId: request.params.organizationId,
        targetType: "user",
        targetId: member.userId,
      });
      return reply.code(201).send({ ...member, joinedAt: member.joinedAt.toISOString() });
    },
  );

  app.patch(
    "/v1/organizations/:organizationId/members/:userId",
    {
      preHandler: createOrganizationRoleHook(database, "admin"),
      schema: {
        params: MemberParamsSchema,
        body: UpdateMemberRoleBodySchema,
        response: {
          200: OrganizationMemberSchema,
          400: ErrorResponseSchema,
          401: ErrorResponseSchema,
          403: ErrorResponseSchema,
          404: ErrorResponseSchema,
          409: ErrorResponseSchema,
        },
      },
    },
    async (request) => {
      const context = getAuthenticationContext(request);
      const member = await changeMemberRole(
        database,
        request.params.organizationId,
        request.params.userId,
        request.body.role,
      );
      if (!member) {
        throw notFound("Organization member not found");
      }
      await recordAuditEvent(database, {
        action: "organization.member_role_changed",
        actorUserId: context.userId,
        organizationId: request.params.organizationId,
        targetType: "user",
        targetId: request.params.userId,
      });
      return { ...member, joinedAt: member.joinedAt.toISOString() };
    },
  );

  app.delete(
    "/v1/organizations/:organizationId/members/:userId",
    {
      preHandler: createOrganizationRoleHook(database, "admin"),
      schema: {
        params: MemberParamsSchema,
        response: {
          204: Type.Null(),
          401: ErrorResponseSchema,
          403: ErrorResponseSchema,
          404: ErrorResponseSchema,
          409: ErrorResponseSchema,
        },
      },
    },
    async (request, reply) => {
      const context = getAuthenticationContext(request);
      const removed = await removeMember(
        database,
        request.params.organizationId,
        request.params.userId,
      );
      if (!removed) {
        throw notFound("Organization member not found");
      }
      await recordAuditEvent(database, {
        action: "organization.member_removed",
        actorUserId: context.userId,
        organizationId: request.params.organizationId,
        targetType: "user",
        targetId: request.params.userId,
      });
      return reply.code(204).send(null);
    },
  );
};
