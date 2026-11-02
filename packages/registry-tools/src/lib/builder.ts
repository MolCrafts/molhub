import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  type ManifestDocument,
  ManifestValidator,
  type MolhubRegistry,
  type RegistryEntry,
  compareCodePoints,
  toRegistryEntry,
} from "@molcrafts/molhub/core";
import yaml from "js-yaml";

import { JsonSchema } from "./json-schema.js";
import { RegistrySource } from "./registry-source.js";
import { REGISTRY_SCHEMA } from "./repo.js";
import { RegistryValidator } from "./validator.js";

export interface RegistryBuildResult {
  readonly entries: number;
  readonly artifacts: number;
  readonly jsonPath: string;
  readonly yamlPath: string;
}

export class RegistryBuilder {
  constructor(
    private readonly manifestValidator = new ManifestValidator(),
    private readonly registrySchema = new JsonSchema(REGISTRY_SCHEMA),
  ) {}

  build(sourceDirectory: string, outputDirectory: string): RegistryBuildResult {
    const entries = this.collect(new RegistrySource(sourceDirectory));
    const registry: MolhubRegistry = { entries };
    const aggregateErrors = this.registrySchema.errorsFor(registry);
    if (aggregateErrors.length > 0) {
      throw new Error(
        `Generated registry violates spec/registry.schema.yaml:\n${aggregateErrors.map((error) => error.text).join("\n")}`,
      );
    }

    mkdirSync(outputDirectory, { recursive: true });
    const jsonPath = join(outputDirectory, "registry.json");
    const yamlPath = join(outputDirectory, "registry.yaml");
    writeFileSync(jsonPath, `${JSON.stringify(registry, null, 2)}\n`, "utf8");
    writeFileSync(
      yamlPath,
      yaml.dump(registry, { noRefs: true, sortKeys: false, indent: 2 }),
      "utf8",
    );
    return {
      entries: entries.length,
      artifacts: entries.reduce((sum, entry) => sum + entry.artifacts.length, 0),
      jsonPath,
      yamlPath,
    };
  }

  private collect(source: RegistrySource): RegistryEntry[] {
    const loaded = source.load();
    const violations = new RegistryValidator(source, this.manifestValidator).run(loaded);
    if (violations.length > 0) {
      throw new Error(violations.map((issue) => `${issue.where}: ${issue.message}`).join("\n"));
    }
    // The complete admission check above validates this exact parsed snapshot.
    return loaded
      .map((manifest) => toRegistryEntry(manifest.data as ManifestDocument))
      .sort((left, right) => compareCodePoints(left.coordinate, right.coordinate));
  }
}
