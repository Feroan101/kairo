import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const schemaDirectory = join(packageRoot, "schemas", "v1");
const outputDirectory = join(packageRoot, "src", "generated");

const schemas = [
  ["messageEnvelopeSchema", "message-envelope.schema.json"],
  ["eventEnvelopeSchema", "event-envelope.schema.json"],
];

const lines = [];

for (const [name, file] of schemas) {
  const schema = JSON.parse(readFileSync(join(schemaDirectory, file), "utf8"));
  lines.push(`export const ${name} = ${JSON.stringify(schema, null, 2)} as const;`, "");
}

mkdirSync(outputDirectory, { recursive: true });
writeFileSync(join(outputDirectory, "schemas.ts"), lines.join("\n"));
