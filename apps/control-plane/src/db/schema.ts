import { sql } from "drizzle-orm";
import {
  check,
  index,
  jsonb,
  pgEnum,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";
import type { AgentConfiguration } from "./agent-configuration.ts";

export const organizationRole = pgEnum("organization_role", ["owner", "admin", "member"]);
export const agentStatus = pgEnum("agent_status", ["active", "paused", "archived"]);

export const users = pgTable(
  "users",
  {
    id: uuid("id").primaryKey().default(sql`gen_random_uuid()`),
    email: text("email").notNull(),
    displayName: text("display_name"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow()
      .$onUpdate(() => new Date()),
  },
  (table) => [
    uniqueIndex("users_email_unique").on(table.email),
    check("users_email_not_empty", sql`length(btrim(${table.email})) > 0`),
  ],
);

export const organizations = pgTable(
  "organizations",
  {
    id: uuid("id").primaryKey().default(sql`gen_random_uuid()`),
    name: text("name").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow()
      .$onUpdate(() => new Date()),
  },
  (table) => [
    index("organizations_name_idx").on(table.name),
    check("organizations_name_not_empty", sql`length(btrim(${table.name})) > 0`),
  ],
);

export const organizationMemberships = pgTable(
  "organization_memberships",
  {
    id: uuid("id").primaryKey().default(sql`gen_random_uuid()`),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    organizationId: uuid("organization_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "restrict" }),
    role: organizationRole("role").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => [
    uniqueIndex("organization_memberships_user_org_unique").on(table.userId, table.organizationId),
    index("organization_memberships_org_idx").on(table.organizationId),
  ],
);

export const agents = pgTable(
  "agents",
  {
    id: uuid("id").primaryKey().default(sql`gen_random_uuid()`),
    organizationId: uuid("organization_id")
      .notNull()
      .references(() => organizations.id, { onDelete: "restrict" }),
    name: text("name").notNull(),
    description: text("description"),
    status: agentStatus("status").notNull().default("active"),
    configuration: jsonb("configuration").$type<AgentConfiguration>().notNull().default({}),
    createdByUserId: uuid("created_by_user_id").references(() => users.id, {
      onDelete: "set null",
    }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow()
      .$onUpdate(() => new Date()),
  },
  (table) => [
    index("agents_organization_status_idx").on(table.organizationId, table.status),
    index("agents_creator_idx").on(table.createdByUserId),
    check("agents_name_not_empty", sql`length(btrim(${table.name})) > 0`),
    check(
      "agents_configuration_no_secrets",
      sql`not (${table.configuration} ?| array['apiKey', 'api_key', 'credentials', 'credential', 'secret', 'password', 'accessToken', 'access_token', 'refreshToken', 'refresh_token'])`,
    ),
  ],
);
