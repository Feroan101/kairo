import { Type } from "@sinclair/typebox";

const UUID_PATTERN =
  "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$";
const EMAIL_PATTERN = "^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$";

export const ErrorResponseSchema = Type.Object(
  {
    error: Type.Object({ code: Type.String(), message: Type.String() }),
  },
  { additionalProperties: false },
);

const UuidSchema = Type.String({ pattern: UUID_PATTERN });
const OrganizationRoleSchema = Type.Union([
  Type.Literal("owner"),
  Type.Literal("admin"),
  Type.Literal("member"),
]);

export const UserSchema = Type.Object(
  {
    id: UuidSchema,
    email: Type.String(),
    displayName: Type.Union([Type.String(), Type.Null()]),
    createdAt: Type.String(),
  },
  { additionalProperties: false },
);

export const RegisterBodySchema = Type.Object(
  {
    email: Type.String({ minLength: 3, maxLength: 254, pattern: EMAIL_PATTERN }),
    password: Type.String({ minLength: 12, maxLength: 256 }),
    displayName: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
  },
  { additionalProperties: false },
);

export const LoginBodySchema = Type.Object(
  {
    email: Type.String({ minLength: 3, maxLength: 254, pattern: EMAIL_PATTERN }),
    password: Type.String({ minLength: 1, maxLength: 256 }),
  },
  { additionalProperties: false },
);

export const LoginResponseSchema = Type.Object(
  {
    token: Type.String({ minLength: 43, maxLength: 43 }),
    expiresAt: Type.String(),
    user: UserSchema,
  },
  { additionalProperties: false },
);

export const SessionSchema = Type.Object(
  {
    id: UuidSchema,
    createdAt: Type.String(),
    expiresAt: Type.String(),
  },
  { additionalProperties: false },
);

export const SessionListResponseSchema = Type.Object(
  { sessions: Type.Array(SessionSchema) },
  { additionalProperties: false },
);

export const SessionIdParamsSchema = Type.Object(
  { sessionId: UuidSchema },
  { additionalProperties: false },
);

export const OrganizationIdParamsSchema = Type.Object(
  { organizationId: UuidSchema },
  { additionalProperties: false },
);

export const CreateOrganizationBodySchema = Type.Object(
  { name: Type.String({ minLength: 1, maxLength: 200 }) },
  { additionalProperties: false },
);

export const OrganizationSchema = Type.Object(
  {
    id: UuidSchema,
    name: Type.String(),
    role: OrganizationRoleSchema,
    createdAt: Type.String(),
  },
  { additionalProperties: false },
);

export const OrganizationListResponseSchema = Type.Object(
  { organizations: Type.Array(OrganizationSchema) },
  { additionalProperties: false },
);

export const OrganizationMemberSchema = Type.Object(
  {
    userId: UuidSchema,
    email: Type.String(),
    displayName: Type.Union([Type.String(), Type.Null()]),
    role: OrganizationRoleSchema,
    joinedAt: Type.String(),
  },
  { additionalProperties: false },
);

export const MemberListResponseSchema = Type.Object(
  { members: Type.Array(OrganizationMemberSchema) },
  { additionalProperties: false },
);

export const AddMemberBodySchema = Type.Object(
  {
    email: Type.String({ minLength: 3, maxLength: 254, pattern: EMAIL_PATTERN }),
    role: OrganizationRoleSchema,
  },
  { additionalProperties: false },
);

export const MemberParamsSchema = Type.Object(
  { organizationId: UuidSchema, userId: UuidSchema },
  { additionalProperties: false },
);

export const UpdateMemberRoleBodySchema = Type.Object(
  { role: OrganizationRoleSchema },
  { additionalProperties: false },
);

export const OkResponseSchema = Type.Object(
  { ok: Type.Literal(true) },
  { additionalProperties: false },
);

export const NoContentResponseSchema = Type.Object({}, { additionalProperties: false });
