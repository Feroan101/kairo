import { Type } from "@sinclair/typebox";
import {
  AgentConfigurationSchema,
  ExecutionPolicySchema,
  HARNESS_VERSION_PATTERN,
  MemoryScopeSchema,
  MODEL_PATTERN,
  ModelSettingsSchema,
  PERMISSION_NAME_PATTERN,
  PROVIDER_PATTERN,
  ToolPermissionSchema,
} from "../db/agent-configuration.ts";
import { ErrorResponseSchema } from "../identity/schemas.ts";

const UUID_PATTERN =
  "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$";

const UuidSchema = Type.String({ pattern: UUID_PATTERN });

export const AgentStatusSchema = Type.Union([
  Type.Literal("active"),
  Type.Literal("paused"),
  Type.Literal("archived"),
]);

export const AgentConfigurationInputSchema = Type.Object(
  {
    modelProvider: Type.String({ minLength: 1, maxLength: 64, pattern: PROVIDER_PATTERN }),
    model: Type.String({ minLength: 1, maxLength: 200, pattern: MODEL_PATTERN }),
    harnessVersion: Type.String({
      minLength: 1,
      maxLength: 64,
      pattern: HARNESS_VERSION_PATTERN,
    }),
    systemInstructions: Type.Optional(Type.String({ maxLength: 8000 })),
    modelSettings: Type.Optional(ModelSettingsSchema),
    tools: Type.Optional(Type.Array(ToolPermissionSchema, { maxItems: 64 })),
    grantedPermissions: Type.Optional(
      Type.Array(Type.String({ minLength: 1, maxLength: 128, pattern: PERMISSION_NAME_PATTERN }), {
        maxItems: 128,
      }),
    ),
    executionPolicy: ExecutionPolicySchema,
    memoryScope: MemoryScopeSchema,
  },
  { additionalProperties: false },
);

export const AgentParamsSchema = Type.Object(
  { organizationId: UuidSchema, agentId: UuidSchema },
  { additionalProperties: false },
);

export const CreateAgentBodySchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 200 }),
    description: Type.Optional(Type.Union([Type.String({ maxLength: 2000 }), Type.Null()])),
    configuration: AgentConfigurationInputSchema,
  },
  { additionalProperties: false },
);

export const UpdateAgentBodySchema = Type.Object(
  {
    name: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
    description: Type.Optional(Type.Union([Type.String({ maxLength: 2000 }), Type.Null()])),
    configuration: Type.Optional(AgentConfigurationInputSchema),
  },
  { additionalProperties: false },
);

export const UpdateAgentStatusBodySchema = Type.Object(
  { status: AgentStatusSchema },
  { additionalProperties: false },
);

export const AgentSchema = Type.Object(
  {
    id: UuidSchema,
    organizationId: UuidSchema,
    name: Type.String(),
    description: Type.Union([Type.String(), Type.Null()]),
    status: AgentStatusSchema,
    configuration: AgentConfigurationSchema,
    createdByUserId: Type.Union([UuidSchema, Type.Null()]),
    createdAt: Type.String(),
    updatedAt: Type.String(),
  },
  { additionalProperties: false },
);

export const AgentListResponseSchema = Type.Object(
  { agents: Type.Array(AgentSchema) },
  { additionalProperties: false },
);

export const AgentErrorResponseSchema = ErrorResponseSchema;
