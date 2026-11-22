# Kairo Contracts

Versioned, language-independent contracts shared by Kairo's TypeScript applications and Python native harness.

## Why contracts exist

The control plane, worker, and harness exchange structured messages and events. JSON Schema is the single source of truth for those structures so that TypeScript and Python agree at runtime without either language redefining the contract. Payload shapes remain open until a specific contract is introduced.

## Layout

```text
packages/contracts/
├── schemas/v1/                     JSON Schema Draft 2020-12 definitions
├── fixtures/v1/                    Shared valid and invalid test cases
├── src/                            Public TypeScript API
├── src/generated/                  Type-level schema constants generated from JSON
├── scripts/                        Type generation script
├── test/                           Vitest contract tests
└── README.md
```

The Python harness reads the same files from `harness/kairo_harness/src/kairo_harness/contracts.py`. It does not keep a copy of the schemas.

## Versioning

Schemas are stored under `schemas/vN/`. The initial version is `v1` with envelope `schemaVersion` value `1.0.0`. Each envelope schema pins that value with `const`, so an unsupported version is rejected by validation rather than silently accepted. A breaking change requires a new version directory and a new `schemaVersion` value; additive payload-specific contracts can be introduced without changing the envelope version.

Envelope fields are closed with `additionalProperties: false`; payloads are plain objects that accept any payload-specific properties.

## TypeScript usage

`@kairo/contracts` exports the schemas, inferred types, and validators:

```ts
import {
  validateMessageEnvelope,
  validateEventEnvelope,
  type MessageEnvelope,
} from "@kairo/contracts";

const result = validateMessageEnvelope(value);
if (result.valid) {
  const message: MessageEnvelope = result.value;
}
```

Validation uses Ajv with Draft 2020-12. Failures return `ValidationIssue[]` containing the keyword, instance path, schema path, message, and params.

Static types are inferred from the JSON schemas with `json-schema-to-ts`. Because TypeScript widens imported JSON literal types, `pnpm --filter @kairo/contracts generate:types` writes `src/generated/schemas.ts` from the JSON files. The generated file is used only at type level; runtime validation reads the original JSON. A test asserts that the generated constants still match the schemas.

## Python usage

The harness uses `jsonschema` to validate against the same schema files and Pydantic v2 models for typed internal access:

```python
from kairo_harness.contracts import to_message_envelope, validate_event_envelope

message = to_message_envelope(value)
result = validate_event_envelope(value)
```

Validation failures raise `ContractValidationError` with a tuple of `ValidationIssue` values. Pydantic models provide typed views after JSON Schema validation; validation rules are not duplicated in Pydantic.

## Adding a contract

1. Add a Draft 2020-12 schema under `schemas/vN/`.
2. Add shared valid and invalid cases to the matching file under `fixtures/vN/`.
3. Register the schema in `src/index.ts` and, for a new envelope shape, regenerate TypeScript types and add Python loading/validation.
4. Extend both test suites so TypeScript and Python consume the new fixtures.
5. Run `pnpm run verify` from the repository root.

## Running the shared validation tests

From the repository root:

```sh
pnpm --filter @kairo/contracts test
pnpm run test:python
```

`pnpm run test` runs both suites. The fixture files are read directly by both languages, so any disagreement in validation behavior fails one of the suites.
