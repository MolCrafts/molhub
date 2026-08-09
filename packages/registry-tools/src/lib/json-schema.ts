/**
 * A compiled JSON Schema, and readable errors from it.
 *
 * The schemas are authored in YAML for the comments; JSON Schema is a data
 * model rather than a syntax, so loading them with `js-yaml` and handing the
 * result to Ajv is the whole story. The Python client validates the same files
 * with `jsonschema`, which is what makes them a language-neutral contract
 * rather than a TypeScript detail.
 */

import { readFileSync } from "node:fs";
import type { ErrorObject, ValidateFunction } from "ajv";
import { Ajv2020 } from "ajv/dist/2020.js";
import yaml from "js-yaml";

/**
 * Ajv's own opinions, tuned so that they police the schema without rejecting a
 * legal one:
 *
 * - `allErrors` — a contributor should see everything wrong with their file in
 *   one run, not peel it one error at a time.
 * - `allowUnionTypes` — `type: [string, "null"]` is how `registry.schema.yaml`
 *   spells a nullable field. Ajv distrusts union types by default; here they
 *   are the point.
 * - `strictRequired: false` — Ajv otherwise rejects `anyOf: [{required: [digest]},
 *   {required: [size]}]` because neither branch redeclares `properties`. That
 *   construct is the digest-or-size rule, it is valid JSON Schema, and the
 *   Python validator accepts it. Ajv's preference does not get to change a
 *   cross-language contract.
 *
 * Everything else stays at Ajv's default strictness, which catches misspelled
 * keywords in the schemas themselves.
 */
const AJV_OPTIONS = { allErrors: true, allowUnionTypes: true, strictRequired: false } as const;

/**
 * One way a document fails a schema.
 *
 * `schemaPath` is a JSON Pointer into the schema itself — a JSON Schema concept,
 * not an Ajv detail — and it is what lets a caller recognise a specific rule and
 * restate it in better words. See `RegistryValidator`'s treatment of the
 * digest-or-size `anyOf`.
 */
export interface SchemaError {
  readonly schemaPath: string;
  /** Already rendered for a human: where in the document, and what is wrong. */
  readonly text: string;
}

/** A schema file, compiled once, ready to judge documents. */
export class JsonSchema {
  private readonly validator: ValidateFunction;

  /**
   * Load and compile the schema at `path`.
   *
   * @throws If the file is unreadable, is not YAML, or is not a valid schema.
   *   All three mean this repository is broken, not a contributor's manifest,
   *   so they escape rather than becoming a violation someone must interpret.
   */
  constructor(readonly path: string) {
    const document = yaml.load(readFileSync(path, "utf8"));
    if (typeof document !== "object" || document === null) {
      throw new Error(`${path} does not contain a JSON Schema object.`);
    }
    this.validator = new Ajv2020(AJV_OPTIONS).compile(document);
  }

  /**
   * Every way `data` fails this schema, already rendered for a human.
   *
   * An empty array means it validates.
   */
  errorsFor(data: unknown): SchemaError[] {
    if (this.validator(data)) return [];
    return (this.validator.errors ?? []).map((error) => JsonSchema.render(error));
  }

  private static render(error: ErrorObject): SchemaError {
    const where = error.instancePath === "" ? "(document root)" : error.instancePath;
    return {
      schemaPath: error.schemaPath,
      text: `${where}: ${error.message ?? "is invalid"}${JsonSchema.detail(error)}`,
    };
  }

  /** The one or two params worth showing; Ajv's bare message is often too terse. */
  private static detail(error: ErrorObject): string {
    const params: Record<string, unknown> = error.params;
    if (error.keyword === "additionalProperties") {
      return ` — remove '${String(params.additionalProperty)}'`;
    }
    if (error.keyword === "enum" && Array.isArray(params.allowedValues)) {
      return ` — one of: ${params.allowedValues.map(String).join(", ")}`;
    }
    if (error.keyword === "const") {
      return ` — must be ${JSON.stringify(params.allowedValue)}`;
    }
    return "";
  }
}
