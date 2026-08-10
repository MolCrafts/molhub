import { ManifestValidator } from "@molcrafts/molhub/core";

import { RegistryBuilder } from "./lib/builder.js";
import { JsonSchema } from "./lib/json-schema.js";
import { ARTIFACTS_DIR, DIST_DIR, REGISTRY_SCHEMA, commandPath } from "./lib/repo.js";

const source = commandPath(process.argv[2], ARTIFACTS_DIR);
const output = commandPath(process.argv[3], DIST_DIR);

try {
  const result = new RegistryBuilder(
    new ManifestValidator(),
    new JsonSchema(REGISTRY_SCHEMA),
  ).build(source, output);
  process.stdout.write(
    `${result.jsonPath} and ${result.yamlPath}: ${result.entries} entries, ${result.artifacts} artifacts.\n`,
  );
} catch (error) {
  const detail = error instanceof Error ? error.message : String(error);
  process.stderr.write(`\nbuild-registry failed.\n\n${detail}\n`);
  process.exitCode = 1;
}
