import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
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
    const registry: MolhubRegistry = { schema_version: 1, entries };
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
    const problems: string[] = [];
    const entries: RegistryEntry[] = [];
    for (const loaded of source.load()) {
      if (loaded.error !== null) {
        problems.push(`${loaded.relativePath}: ${loaded.error}`);
        continue;
      }
      const validation = this.manifestValidator.validate(loaded.data);
      if (!validation.ok) {
        problems.push(
          `${loaded.relativePath}:\n${validation.issues.map((issue) => `  ${issue.path}: ${issue.message}`).join("\n")}`,
        );
        continue;
      }
      entries.push(toRegistryEntry(validation.value));
    }
    if (problems.length > 0) {
      throw new Error(
        `${problems.length} manifest(s) could not be indexed:\n\n${problems.join("\n\n")}`,
      );
    }
    return entries.sort((left, right) => compareCodePoints(left.coordinate, right.coordinate));
  }
}
