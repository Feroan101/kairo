import { type Static, Type } from "@sinclair/typebox";

export const AgentConfigurationSchema = Type.Object(
  {
    modelProvider: Type.Optional(Type.String({ minLength: 1 })),
    model: Type.Optional(Type.String({ minLength: 1 })),
    harnessVersion: Type.Optional(Type.String({ minLength: 1 })),
    tools: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
  },
  { additionalProperties: false },
);

export type AgentConfiguration = Static<typeof AgentConfigurationSchema>;
