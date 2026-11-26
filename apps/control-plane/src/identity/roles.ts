import type { organizationRole } from "../db/schema.ts";

export type OrganizationRole = (typeof organizationRole.enumValues)[number];

const RANK: Record<OrganizationRole, number> = {
  owner: 3,
  admin: 2,
  member: 1,
};

export function hasRequiredRole(current: OrganizationRole, required: OrganizationRole): boolean {
  return RANK[current] >= RANK[required];
}
