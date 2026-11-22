import { describe, expect, expectTypeOf, it } from "vitest";
import eventFixtures from "../fixtures/v1/event-envelope.json" with { type: "json" };
import messageFixtures from "../fixtures/v1/message-envelope.json" with { type: "json" };
import { eventEnvelopeSchema, messageEnvelopeSchema } from "../src/generated/schemas.js";
import {
  CONTRACT_SCHEMA_VERSION,
  type EventEnvelope,
  JSON_SCHEMA_DIALECT,
  type MessageEnvelope,
  schemas,
  type ValidationResult,
  validateEventEnvelope,
  validateMessageEnvelope,
} from "../src/index.js";

interface FixtureCase {
  name: string;
  value: unknown;
}

interface FixtureFile {
  kind: string;
  schemaVersion: string;
  valid: FixtureCase[];
  invalid: Array<FixtureCase & { reason: string }>;
}

function checkFixtures(
  fixtures: FixtureFile,
  validate: (value: unknown) => ValidationResult<unknown>,
): void {
  it("accepts every valid fixture", () => {
    for (const testCase of fixtures.valid) {
      const result = validate(testCase.value);
      expect(result.valid, testCase.name).toBe(true);
    }
  });

  it("rejects every invalid fixture with structured issues", () => {
    for (const testCase of fixtures.invalid) {
      const result = validate(testCase.value);
      expect(result.valid, `${testCase.name}: ${testCase.reason}`).toBe(false);
      if (!result.valid) {
        expect(result.issues.length, testCase.name).toBeGreaterThan(0);
        expect(result.issues[0]?.keyword, testCase.name).toBeTruthy();
      }
    }
  });
}

describe("contract schemas", () => {
  it("use the documented dialect and current schema version", () => {
    for (const schema of Object.values(schemas)) {
      expect(schema.$schema).toBe(JSON_SCHEMA_DIALECT);
    }
    expect(messageFixtures.schemaVersion).toBe(CONTRACT_SCHEMA_VERSION);
    expect(eventFixtures.schemaVersion).toBe(CONTRACT_SCHEMA_VERSION);
  });

  it("generate TypeScript types from the same schemas used at runtime", () => {
    expect(messageEnvelopeSchema).toEqual(schemas.messageEnvelope);
    expect(eventEnvelopeSchema).toEqual(schemas.eventEnvelope);
  });

  it("keep common envelope definitions consistent between schema files", () => {
    for (const key of ["uuid", "utcTimestamp", "namespacedType"] as const) {
      expect(messageEnvelopeSchema.$defs[key]).toEqual(eventEnvelopeSchema.$defs[key]);
    }
  });

  it("infer envelope types from the schemas", () => {
    expectTypeOf<MessageEnvelope>().toHaveProperty("messageId");
    expectTypeOf<MessageEnvelope>().toHaveProperty("payload");
    expectTypeOf<EventEnvelope>().toHaveProperty("occurredAt");
    expectTypeOf<MessageEnvelope["schemaVersion"]>().toEqualTypeOf<"1.0.0">();
    expectTypeOf<EventEnvelope["schemaVersion"]>().toEqualTypeOf<"1.0.0">();
  });
});

describe("message envelope fixtures", () => {
  checkFixtures(messageFixtures as FixtureFile, validateMessageEnvelope);
});

describe("event envelope fixtures", () => {
  checkFixtures(eventFixtures as FixtureFile, validateEventEnvelope);
});
