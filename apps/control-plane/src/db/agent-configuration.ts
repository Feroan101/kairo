import { type Static, Type } from "@sinclair/typebox";

export const PROVIDER_PATTERN = "^[a-z][a-z0-9_.-]{0,63}$";
export const MODEL_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$";
export const HARNESS_VERSION_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$";
export const TOOL_NAME_PATTERN = "^[A-Za-z][A-Za-z0-9_.-]{0,63}$";
export const PERMISSION_NAME_PATTERN = "^[a-z][a-z0-9_.:-]{0,127}$";

export const ModelSettingsSchema = Type.Object(
  {
    temperature: Type.Optional(Type.Number({ minimum: 0, maximum: 2 })),
    maxTokens: Type.Optional(Type.Integer({ minimum: 1, maximum: 100000 })),
    timeoutSeconds: Type.Optional(Type.Number({ minimum: 1, maximum: 300 })),
    streamResponses: Type.Optional(Type.Boolean()),
  },
  { additionalProperties: false },
);

export const ToolPermissionSchema = Type.Object(
  {
    name: Type.String({ minLength: 1, maxLength: 64, pattern: TOOL_NAME_PATTERN }),
    allowed: Type.Boolean(),
    permissions: Type.Array(
      Type.String({ minLength: 1, maxLength: 128, pattern: PERMISSION_NAME_PATTERN }),
      { maxItems: 128 },
    ),
  },
  { additionalProperties: false },
);

export const ExecutionPolicySchema = Type.Object(
  {
    maxIterations: Type.Integer({ minimum: 1, maximum: 100 }),
    maxModelRequests: Type.Integer({ minimum: 1, maximum: 100 }),
    maxToolCalls: Type.Integer({ minimum: 0, maximum: 100 }),
    timeoutSeconds: Type.Number({ minimum: 1, maximum: 3600 }),
  },
  { additionalProperties: false },
);

export const MemoryScopeSchema = Type.Union([
  Type.Literal("private"),
  Type.Literal("organization"),
]);

export const AgentConfigurationSchema = Type.Object(
  {
    modelProvider: Type.Optional(
      Type.String({ minLength: 1, maxLength: 64, pattern: PROVIDER_PATTERN }),
    ),
    model: Type.Optional(Type.String({ minLength: 1, maxLength: 200, pattern: MODEL_PATTERN })),
    harnessVersion: Type.Optional(
      Type.String({ minLength: 1, maxLength: 64, pattern: HARNESS_VERSION_PATTERN }),
    ),
    systemInstructions: Type.Optional(Type.String({ maxLength: 8000 })),
    modelSettings: Type.Optional(ModelSettingsSchema),
    tools: Type.Optional(Type.Array(ToolPermissionSchema, { maxItems: 64 })),
    grantedPermissions: Type.Optional(
      Type.Array(Type.String({ minLength: 1, maxLength: 128, pattern: PERMISSION_NAME_PATTERN }), {
        maxItems: 128,
      }),
    ),
    executionPolicy: Type.Optional(ExecutionPolicySchema),
    memoryScope: Type.Optional(MemoryScopeSchema),
  },
  { additionalProperties: false },
);

export type AgentConfiguration = Static<typeof AgentConfigurationSchema>;
export type ExecutionPolicy = Static<typeof ExecutionPolicySchema>;
export type ToolPermission = Static<typeof ToolPermissionSchema>;
