import { and, eq, gt, isNull } from "drizzle-orm";
import type { Database } from "../db/client.ts";
import {
  auditEvents,
  organizationMemberships,
  organizations,
  sessions,
  users,
} from "../db/schema.ts";
import { conflict, forbidden, HttpError, notFound, unauthorized } from "../errors.ts";
import { hashPassword, verifyPassword, verifyUnusablePassword } from "./credentials.ts";
import { hasRequiredRole, type OrganizationRole } from "./roles.ts";
import { createSessionToken, hashSessionToken } from "./session-token.ts";

export interface AuthenticatedUser {
  id: string;
  email: string;
  displayName: string | null;
  createdAt: Date;
}

export interface SessionAuthentication {
  sessionId: string;
  user: AuthenticatedUser;
}

export interface SessionSummary {
  id: string;
  createdAt: Date;
  expiresAt: Date;
}

export interface OrganizationSummary {
  id: string;
  name: string;
  role: OrganizationRole;
  createdAt: Date;
}

export interface OrganizationMember {
  userId: string;
  email: string;
  displayName: string | null;
  role: OrganizationRole;
  joinedAt: Date;
}

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

function publicUser(user: {
  id: string;
  email: string;
  displayName: string | null;
  createdAt: Date;
}): AuthenticatedUser {
  return {
    id: user.id,
    email: user.email,
    displayName: user.displayName,
    createdAt: user.createdAt,
  };
}

export async function registerUser(
  database: Database,
  input: { email: string; password: string; displayName?: string | undefined },
): Promise<AuthenticatedUser> {
  const passwordHash = await hashPassword(input.password);
  const [user] = await database.db
    .insert(users)
    .values({
      email: normalizeEmail(input.email),
      passwordHash,
      displayName: input.displayName?.trim() || null,
    })
    .onConflictDoNothing({ target: users.email })
    .returning();

  if (!user) {
    throw conflict("An account with that email already exists");
  }

  await recordAuditEvent(database, {
    action: "auth.registered",
    actorUserId: user.id,
    targetType: "user",
    targetId: user.id,
  });

  return publicUser(user);
}

export async function authenticateUser(
  database: Database,
  input: { email: string; password: string },
  ttlSeconds: number,
): Promise<{ token: string; expiresAt: Date; user: AuthenticatedUser }> {
  const [user] = await database.db
    .select()
    .from(users)
    .where(eq(users.email, normalizeEmail(input.email)));

  let validPassword = false;
  if (user) {
    validPassword = await verifyPassword(input.password, user.passwordHash);
  } else {
    await verifyUnusablePassword(input.password);
  }

  if (!user || !validPassword || !user.passwordHash) {
    await recordAuditEvent(database, {
      action: "auth.login_failed",
      actorUserId: user?.id ?? null,
      targetType: "user",
      targetId: user?.id ?? null,
    });
    throw unauthorized("Invalid email or password");
  }

  const { token, tokenHash } = createSessionToken();
  const expiresAt = new Date(Date.now() + ttlSeconds * 1000);
  await database.db.insert(sessions).values({ userId: user.id, tokenHash, expiresAt });

  await recordAuditEvent(database, {
    action: "auth.logged_in",
    actorUserId: user.id,
    targetType: "session",
    targetId: null,
  });

  return { token, expiresAt, user: publicUser(user) };
}

export async function authenticateSession(
  database: Database,
  token: string,
): Promise<SessionAuthentication | undefined> {
  const rows = await database.db
    .select({
      sessionId: sessions.id,
      user: users,
    })
    .from(sessions)
    .innerJoin(users, eq(sessions.userId, users.id))
    .where(
      and(
        eq(sessions.tokenHash, hashSessionToken(token)),
        isNull(sessions.revokedAt),
        gt(sessions.expiresAt, new Date()),
      ),
    )
    .limit(1);

  const row = rows[0];
  return row ? { sessionId: row.sessionId, user: publicUser(row.user) } : undefined;
}

export async function listActiveSessions(
  database: Database,
  userId: string,
): Promise<SessionSummary[]> {
  return database.db
    .select({
      id: sessions.id,
      createdAt: sessions.createdAt,
      expiresAt: sessions.expiresAt,
    })
    .from(sessions)
    .where(
      and(
        eq(sessions.userId, userId),
        isNull(sessions.revokedAt),
        gt(sessions.expiresAt, new Date()),
      ),
    )
    .orderBy(sessions.expiresAt);
}

export async function revokeSession(
  database: Database,
  userId: string,
  sessionId: string,
): Promise<boolean> {
  const revoked = await database.db
    .update(sessions)
    .set({ revokedAt: new Date() })
    .where(and(eq(sessions.id, sessionId), eq(sessions.userId, userId), isNull(sessions.revokedAt)))
    .returning({ id: sessions.id });

  return revoked.length > 0;
}

export async function createOrganization(
  database: Database,
  userId: string,
  name: string,
): Promise<OrganizationSummary> {
  const trimmedName = name.trim();
  if (!trimmedName) {
    throw new HttpError(400, "VALIDATION_ERROR", "Organization name is required");
  }

  const organization = await database.db.transaction(async (tx) => {
    const [created] = await tx.insert(organizations).values({ name: trimmedName }).returning();
    if (!created) {
      throw new Error("Failed to create organization");
    }
    await tx.insert(organizationMemberships).values({
      userId,
      organizationId: created.id,
      role: "owner",
    });
    return created;
  });

  await recordAuditEvent(database, {
    action: "organization.created",
    actorUserId: userId,
    organizationId: organization.id,
    targetType: "organization",
    targetId: organization.id,
  });

  return {
    id: organization.id,
    name: organization.name,
    role: "owner",
    createdAt: organization.createdAt,
  };
}

export async function listUserOrganizations(
  database: Database,
  userId: string,
): Promise<OrganizationSummary[]> {
  const rows = await database.db
    .select({
      id: organizations.id,
      name: organizations.name,
      role: organizationMemberships.role,
      createdAt: organizations.createdAt,
    })
    .from(organizationMemberships)
    .innerJoin(organizations, eq(organizationMemberships.organizationId, organizations.id))
    .where(eq(organizationMemberships.userId, userId))
    .orderBy(organizations.name);

  return rows.map((row) => ({
    id: row.id,
    name: row.name,
    role: row.role,
    createdAt: row.createdAt,
  }));
}

export async function getOrganizationForUser(
  database: Database,
  userId: string,
  organizationId: string,
): Promise<OrganizationSummary | undefined> {
  const [row] = await database.db
    .select({
      id: organizations.id,
      name: organizations.name,
      role: organizationMemberships.role,
      createdAt: organizations.createdAt,
    })
    .from(organizations)
    .innerJoin(
      organizationMemberships,
      eq(organizationMemberships.organizationId, organizations.id),
    )
    .where(and(eq(organizations.id, organizationId), eq(organizationMemberships.userId, userId)))
    .limit(1);

  return row ? { id: row.id, name: row.name, role: row.role, createdAt: row.createdAt } : undefined;
}

export async function listOrganizationMembers(
  database: Database,
  organizationId: string,
): Promise<OrganizationMember[]> {
  const rows = await database.db
    .select({
      userId: users.id,
      email: users.email,
      displayName: users.displayName,
      role: organizationMemberships.role,
      joinedAt: organizationMemberships.createdAt,
    })
    .from(organizationMemberships)
    .innerJoin(users, eq(organizationMemberships.userId, users.id))
    .where(eq(organizationMemberships.organizationId, organizationId))
    .orderBy(users.email);

  return rows.map((row) => ({
    userId: row.userId,
    email: row.email,
    displayName: row.displayName,
    role: row.role,
    joinedAt: row.joinedAt,
  }));
}

export async function addOrganizationMember(
  database: Database,
  organizationId: string,
  email: string,
  role: OrganizationRole,
): Promise<OrganizationMember | undefined> {
  const [user] = await database.db
    .select()
    .from(users)
    .where(eq(users.email, normalizeEmail(email)))
    .limit(1);
  if (!user) {
    return undefined;
  }

  const [membership] = await database.db
    .insert(organizationMemberships)
    .values({ organizationId, userId: user.id, role })
    .onConflictDoNothing()
    .returning();
  if (!membership) {
    throw conflict("User is already a member of this organization");
  }

  return {
    userId: user.id,
    email: user.email,
    displayName: user.displayName,
    role,
    joinedAt: membership.createdAt,
  };
}

export async function changeMemberRole(
  database: Database,
  organizationId: string,
  targetUserId: string,
  role: OrganizationRole,
): Promise<OrganizationMember | undefined> {
  return database.db.transaction(async (tx) => {
    const [target] = await tx
      .select({
        userId: users.id,
        email: users.email,
        displayName: users.displayName,
        role: organizationMemberships.role,
        joinedAt: organizationMemberships.createdAt,
      })
      .from(organizationMemberships)
      .innerJoin(users, eq(organizationMemberships.userId, users.id))
      .where(
        and(
          eq(organizationMemberships.organizationId, organizationId),
          eq(organizationMemberships.userId, targetUserId),
        ),
      )
      .limit(1);

    if (!target) {
      return undefined;
    }

    if (target.role === "owner" && role !== "owner") {
      const owners = await tx
        .select({ id: organizationMemberships.id })
        .from(organizationMemberships)
        .where(
          and(
            eq(organizationMemberships.organizationId, organizationId),
            eq(organizationMemberships.role, "owner"),
          ),
        );
      if (owners.length === 1) {
        throw conflict("Organization must retain at least one owner");
      }
    }

    await tx
      .update(organizationMemberships)
      .set({ role })
      .where(
        and(
          eq(organizationMemberships.organizationId, organizationId),
          eq(organizationMemberships.userId, targetUserId),
        ),
      );

    return { ...target, role };
  });
}

export async function removeMember(
  database: Database,
  organizationId: string,
  targetUserId: string,
): Promise<boolean> {
  return database.db.transaction(async (tx) => {
    const [target] = await tx
      .select({ role: organizationMemberships.role })
      .from(organizationMemberships)
      .where(
        and(
          eq(organizationMemberships.organizationId, organizationId),
          eq(organizationMemberships.userId, targetUserId),
        ),
      )
      .limit(1);

    if (!target) {
      return false;
    }

    if (target.role === "owner") {
      const owners = await tx
        .select({ id: organizationMemberships.id })
        .from(organizationMemberships)
        .where(
          and(
            eq(organizationMemberships.organizationId, organizationId),
            eq(organizationMemberships.role, "owner"),
          ),
        );
      if (owners.length === 1) {
        throw conflict("Organization must retain at least one owner");
      }
    }

    await tx
      .delete(organizationMemberships)
      .where(
        and(
          eq(organizationMemberships.organizationId, organizationId),
          eq(organizationMemberships.userId, targetUserId),
        ),
      );
    return true;
  });
}

export async function assertOrganizationRole(
  database: Database,
  userId: string,
  organizationId: string,
  requiredRole: OrganizationRole,
): Promise<void> {
  const membership = await getOrganizationForUser(database, userId, organizationId);
  if (!membership || !hasRequiredRole(membership.role, requiredRole)) {
    await recordAuditEvent(database, {
      action: "authorization.denied",
      actorUserId: userId,
      organizationId,
      targetType: "organization",
      targetId: organizationId,
    });
    if (!membership) {
      throw notFound("Organization not found");
    }
    throw forbidden();
  }
}

export interface AuditEventInput {
  action: string;
  actorUserId: string | null;
  organizationId?: string | null;
  targetType?: string | null;
  targetId?: string | null;
}

export async function recordAuditEvent(database: Database, input: AuditEventInput): Promise<void> {
  await database.db.insert(auditEvents).values({
    action: input.action,
    actorUserId: input.actorUserId,
    organizationId: input.organizationId ?? null,
    targetType: input.targetType ?? null,
    targetId: input.targetId ?? null,
  });
}
