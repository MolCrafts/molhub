import type { ErrorObject, ValidateFunction } from "ajv";
import yaml from "js-yaml";

import { Coordinate } from "./coordinate.js";
import validateManifestDocument from "./generated-manifest-validator.js";
import { Locator } from "./locator.js";
import type { ManifestDocument, RegistryArtifact, RegistryEntry } from "./types.js";

export type ManifestIssueCode =
  | "schema"
  | "missing_doi"
  | "duplicate_role"
  | "unpinned_locator"
  | "unknown_scheme";

export interface ManifestIssue {
  readonly code: ManifestIssueCode;
  readonly path: string;
  readonly message: string;
}

export type ManifestValidation =
  | { readonly ok: true; readonly value: ManifestDocument; readonly issues: readonly [] }
  | { readonly ok: false; readonly issues: readonly ManifestIssue[] };

const SUPPORTED_SCHEMES = new Set(["https", "http", "figshare", "zenodo", "hf", "molhub"]);
const COMMIT = /^[0-9a-f]{7,64}$/i;

export class ManifestValidator {
  private readonly validateSchema: ValidateFunction;

  constructor() {
    this.validateSchema = validateManifestDocument as ValidateFunction;
  }

  validate(input: unknown): ManifestValidation {
    if (!this.validateSchema(input)) {
      return {
        ok: false,
        issues: ManifestValidator.schemaIssues(this.validateSchema.errors ?? []),
      };
    }

    const document = input as ManifestDocument;
    const issues: ManifestIssue[] = [];
    if (!document.doi) {
      issues.push({
        code: "missing_doi",
        path: "/doi",
        message: "Add the DOI for this exact published version.",
      });
    }

    const roles = new Set<string>();
    for (const [artifactIndex, artifact] of document.artifacts.entries()) {
      if (roles.has(artifact.role)) {
        issues.push({
          code: "duplicate_role",
          path: `/artifacts/${artifactIndex}/role`,
          message: `Role ${JSON.stringify(artifact.role)} is declared more than once.`,
        });
      }
      roles.add(artifact.role);
      for (const [locatorIndex, text] of artifact.locators.entries()) {
        issues.push(
          ...this.locatorIssues(text, `/artifacts/${artifactIndex}/locators/${locatorIndex}`),
        );
      }
    }
    return issues.length === 0 ? { ok: true, value: document, issues: [] } : { ok: false, issues };
  }

  private locatorIssues(text: string, path: string): ManifestIssue[] {
    const locator = Locator.parse(text);
    if (!SUPPORTED_SCHEMES.has(locator.scheme)) {
      return [
        { code: "unknown_scheme", path, message: `No MolHub source handles ${locator.scheme}://.` },
      ];
    }
    if (locator.scheme === "figshare") {
      const parts = locator.path.split("/");
      if (!/^v\d+$/.test(parts[1] ?? "")) {
        return [
          { code: "unpinned_locator", path, message: "Pin a Figshare article version as /vN/." },
        ];
      }
    }
    if (locator.scheme === "hf") {
      const repo = locator.path.split("/")[1] ?? "";
      const revision = repo.split("@", 2)[1];
      if (!revision || !COMMIT.test(revision)) {
        return [
          { code: "unpinned_locator", path, message: "Pin Hugging Face to a commit revision." },
        ];
      }
    }
    if (
      (locator.scheme === "http" || locator.scheme === "https") &&
      /github\.com|githubusercontent\.com|raw\.githubusercontent\.com/i.test(locator.path)
    ) {
      const url = new URL(locator.toString());
      const segments = url.pathname.split("/").filter(Boolean);
      const marker = segments.findIndex((segment) => segment === "blob" || segment === "raw");
      const revision = marker !== -1 ? segments[marker + 1] : segments[2];
      if (!COMMIT.test(revision ?? "")) {
        return [
          { code: "unpinned_locator", path, message: "Pin GitHub URLs to a commit, not a branch." },
        ];
      }
    }
    return [];
  }

  private static schemaIssue(error: ErrorObject): ManifestIssue {
    const detail =
      error.keyword === "additionalProperties"
        ? ` Remove ${JSON.stringify(error.params.additionalProperty)}.`
        : "";
    return {
      code: "schema",
      path: error.instancePath || "/",
      message: `${error.message ?? "Invalid value"}.${detail}`,
    };
  }

  private static schemaIssues(errors: readonly ErrorObject[]): ManifestIssue[] {
    const digestOrSize = errors.some((error) => error.schemaPath.includes("/anyOf"));
    const issues = errors
      .filter((error) => !error.schemaPath.includes("/anyOf"))
      .map(ManifestValidator.schemaIssue);
    if (digestOrSize) {
      issues.push({
        code: "schema",
        path:
          errors.find((error) => error.schemaPath.includes("/anyOf"))?.instancePath || "/artifacts",
        message: "Each artifact needs a published digest or a positive byte size.",
      });
    }
    return issues;
  }
}

export function manifestCoordinate(document: ManifestDocument): Coordinate {
  return new Coordinate(document.kind, document.namespace, document.name, document.version);
}

export function serializeManifest(document: ManifestDocument): string {
  return yaml.dump(document, { noRefs: true, sortKeys: false, lineWidth: 100 });
}

export function toRegistryEntry(document: ManifestDocument): RegistryEntry {
  const coordinate = manifestCoordinate(document);
  return {
    coordinate: coordinate.canonical,
    kind: document.kind,
    namespace: document.namespace,
    name: document.name,
    version: document.version,
    title: document.title,
    description: document.description ?? null,
    license: document.license ?? null,
    doi: document.doi ?? null,
    targets: {
      graph_level: document.targets?.graph_level ?? [],
      atom_level: document.targets?.atom_level ?? [],
    },
    artifacts: document.artifacts
      .map(
        (artifact): RegistryArtifact => ({
          role: artifact.role,
          filename: artifact.filename,
          format: artifact.format ?? null,
          media_type: artifact.media_type ?? null,
          locators: [...artifact.locators],
          digest: artifact.digest ?? null,
          size: artifact.size ?? null,
        }),
      )
      .sort((left, right) => compareCodePoints(left.role, right.role)),
  };
}

export function compareCodePoints(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}
