import type { FastifyRequest } from "fastify";
import type { Database } from "../db/client.ts";
import { unauthorized } from "../errors.ts";
import type { OrganizationRole } from "./roles.ts";
import { assertOrganizationRole, authenticateSession, recordAuditEvent } from "./service.ts";
import { isValidSessionToken } from "./session-token.ts";

export interface AuthenticationContext {
  sessionId: string;
  userId: string;
  email: string;
  displayName: string | null;
  createdAt: Date;
}

declare module "fastify" {
  interface FastifyRequest {
    auth?: AuthenticationContext;
  }
  interface FastifyContextConfig {
    public?: boolean;
  }
}

export function createAuthenticationHook(database: Database) {
  return async (request: FastifyRequest): Promise<void> => {
    if (request.routeOptions.config?.public) {
      return;
    }

    const header = request.headers.authorization;
    const match = header?.match(/^Bearer (\S+)$/);
    const token = match?.[1];
    if (!token || !isValidSessionToken(token)) {
      await recordAuditEvent(database, { action: "auth.denied", actorUserId: null });
      throw unauthorized("Invalid or expired session");
    }

    const authentication = await authenticateSession(database, token);
    if (!authentication) {
      await recordAuditEvent(database, { action: "auth.denied", actorUserId: null });
      throw unauthorized("Invalid or expired session");
    }

    request.auth = {
      sessionId: authentication.sessionId,
      userId: authentication.user.id,
      email: authentication.user.email,
      displayName: authentication.user.displayName,
      createdAt: authentication.user.createdAt,
    };
  };
}

export function getAuthenticationContext(request: FastifyRequest): AuthenticationContext {
  if (!request.auth) {
    throw unauthorized();
  }
  return request.auth;
}

export function createOrganizationRoleHook(database: Database, requiredRole: OrganizationRole) {
  return async (request: FastifyRequest): Promise<void> => {
    const context = getAuthenticationContext(request);
    const { organizationId } = request.params as { organizationId?: string };
    if (!organizationId) {
      throw unauthorized();
    }
    await assertOrganizationRole(database, context.userId, organizationId, requiredRole);
  };
}
