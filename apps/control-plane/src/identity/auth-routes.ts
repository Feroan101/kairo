import type { FastifyPluginAsyncTypebox } from "@fastify/type-provider-typebox";
import { Type } from "@sinclair/typebox";
import type { ServerConfig } from "../config.ts";
import type { Database } from "../db/client.ts";
import { notFound } from "../errors.ts";
import { getAuthenticationContext } from "./authorization.ts";
import {
  ErrorResponseSchema,
  LoginBodySchema,
  LoginResponseSchema,
  RegisterBodySchema,
  SessionIdParamsSchema,
  SessionListResponseSchema,
  UserSchema,
} from "./schemas.ts";
import {
  authenticateUser,
  listActiveSessions,
  recordAuditEvent,
  registerUser,
  revokeSession,
} from "./service.ts";

export interface IdentityRouteOptions {
  database: Database;
  serverConfig: ServerConfig;
}

export const authRoutes: FastifyPluginAsyncTypebox<IdentityRouteOptions> = async (app, options) => {
  const { database, serverConfig } = options;

  app.post(
    "/v1/auth/register",
    {
      config: { public: true },
      schema: {
        body: RegisterBodySchema,
        response: {
          201: UserSchema,
          400: ErrorResponseSchema,
          409: ErrorResponseSchema,
        },
      },
    },
    async (request, reply) => {
      const user = await registerUser(database, request.body);
      return reply.code(201).send({ ...user, createdAt: user.createdAt.toISOString() });
    },
  );

  app.post(
    "/v1/auth/login",
    {
      config: { public: true },
      schema: {
        body: LoginBodySchema,
        response: {
          200: LoginResponseSchema,
          400: ErrorResponseSchema,
          401: ErrorResponseSchema,
        },
      },
    },
    async (request) => {
      const authentication = await authenticateUser(
        database,
        request.body,
        serverConfig.sessionTtlSeconds,
      );
      return {
        token: authentication.token,
        expiresAt: authentication.expiresAt.toISOString(),
        user: {
          ...authentication.user,
          createdAt: authentication.user.createdAt.toISOString(),
        },
      };
    },
  );

  app.get(
    "/v1/auth/me",
    {
      schema: { response: { 200: UserSchema, 401: ErrorResponseSchema } },
    },
    async (request) => {
      const context = getAuthenticationContext(request);
      return {
        id: context.userId,
        email: context.email,
        displayName: context.displayName,
        createdAt: context.createdAt.toISOString(),
      };
    },
  );

  app.get(
    "/v1/auth/sessions",
    {
      schema: { response: { 200: SessionListResponseSchema, 401: ErrorResponseSchema } },
    },
    async (request) => {
      const context = getAuthenticationContext(request);
      const sessions = await listActiveSessions(database, context.userId);
      return {
        sessions: sessions.map((session) => ({
          id: session.id,
          createdAt: session.createdAt.toISOString(),
          expiresAt: session.expiresAt.toISOString(),
        })),
      };
    },
  );

  app.delete(
    "/v1/auth/sessions/:sessionId",
    {
      schema: {
        params: SessionIdParamsSchema,
        response: { 204: Type.Null(), 401: ErrorResponseSchema, 404: ErrorResponseSchema },
      },
    },
    async (request, reply) => {
      const context = getAuthenticationContext(request);
      const revoked = await revokeSession(database, context.userId, request.params.sessionId);
      if (!revoked) {
        throw notFound("Session not found");
      }
      await recordAuditEvent(database, {
        action: "auth.session_revoked",
        actorUserId: context.userId,
        targetType: "session",
        targetId: request.params.sessionId,
      });
      return reply.code(204).send(null);
    },
  );

  app.post(
    "/v1/auth/logout",
    {
      schema: { response: { 204: Type.Null(), 401: ErrorResponseSchema } },
    },
    async (request, reply) => {
      const context = getAuthenticationContext(request);
      await revokeSession(database, context.userId, context.sessionId);
      await recordAuditEvent(database, {
        action: "auth.logged_out",
        actorUserId: context.userId,
        targetType: "session",
        targetId: context.sessionId,
      });
      return reply.code(204).send(null);
    },
  );
};
