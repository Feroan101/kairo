import { Ajv2020, type ErrorObject, type ValidateFunction } from "ajv/dist/2020.js";
import type { FromSchema } from "json-schema-to-ts";
import eventEnvelopeSchema from "../schemas/v1/event-envelope.schema.json" with { type: "json" };
import messageEnvelopeSchema from "../schemas/v1/message-envelope.schema.json" with {
  type: "json",
};
import type {
  eventEnvelopeSchema as EventEnvelopeSchema,
  messageEnvelopeSchema as MessageEnvelopeSchema,
} from "./generated/schemas.js";

export const CONTRACT_SCHEMA_VERSION = "1.0.0";
export const JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema";

export const schemas = {
  messageEnvelope: messageEnvelopeSchema,
  eventEnvelope: eventEnvelopeSchema,
} as const;

export type MessageEnvelope = FromSchema<typeof MessageEnvelopeSchema>;
export type EventEnvelope = FromSchema<typeof EventEnvelopeSchema>;

export interface ValidationIssue {
  keyword: string;
  instancePath: string;
  schemaPath: string;
  message: string;
  params: Record<string, unknown>;
}

export type ValidationResult<T> =
  | { valid: true; value: T }
  | { valid: false; issues: ValidationIssue[] };

const ajv = new Ajv2020({ allErrors: true, strict: true });
const messageValidator = ajv.compile(messageEnvelopeSchema);
const eventValidator = ajv.compile(eventEnvelopeSchema);

function toIssue(error: ErrorObject): ValidationIssue {
  return {
    keyword: error.keyword,
    instancePath: error.instancePath,
    schemaPath: error.schemaPath,
    message: error.message ?? error.keyword,
    params: error.params as Record<string, unknown>,
  };
}

function validate<T>(validator: ValidateFunction, value: unknown): ValidationResult<T> {
  if (validator(value)) {
    return { valid: true, value: value as T };
  }

  return {
    valid: false,
    issues: (validator.errors ?? []).map(toIssue),
  };
}

export function validateMessageEnvelope(value: unknown): ValidationResult<MessageEnvelope> {
  return validate<MessageEnvelope>(messageValidator, value);
}

export function validateEventEnvelope(value: unknown): ValidationResult<EventEnvelope> {
  return validate<EventEnvelope>(eventValidator, value);
}
