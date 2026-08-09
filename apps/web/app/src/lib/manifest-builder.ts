import {
  type ArtifactKind,
  type ManifestArtifact,
  type ManifestDocument,
  type ManifestIssue,
  ManifestValidator,
  serializeManifest,
} from "@molcrafts/molhub/core";

export interface ArtifactDraft {
  readonly id: string;
  readonly role: string;
  readonly filename: string;
  readonly format: string;
  readonly mediaType: string;
  readonly locators: readonly string[];
  readonly digest: string;
  readonly size: string;
}

export interface ManifestDraft {
  readonly kind: ArtifactKind;
  readonly namespace: string;
  readonly name: string;
  readonly version: string;
  readonly title: string;
  readonly description: string;
  readonly license: string;
  readonly doi: string;
  readonly artifacts: readonly ArtifactDraft[];
  readonly graphTargets: string;
  readonly atomTargets: string;
}

export const DEFAULT_MANIFEST_DRAFT: ManifestDraft = {
  kind: "dataset",
  namespace: "your-lab",
  name: "molecular-benchmark",
  version: "v1",
  title: "Molecular benchmark",
  description: "A versioned molecular artifact published by your lab.",
  license: "CC-BY-4.0",
  doi: "10.0000/example",
  artifacts: [createArtifactDraft("artifact-1")],
  graphTargets: "energy",
  atomTargets: "forces",
};

export function createArtifactDraft(id: string = crypto.randomUUID()): ArtifactDraft {
  return {
    id,
    role: "main",
    filename: "structures.xyz",
    format: "extxyz",
    mediaType: "chemical/x-xyz",
    locators: ["https://zenodo.org/records/000000/files/structures.xyz"],
    digest: "",
    size: "1",
  };
}

export function manifestCoordinate(draft: ManifestDraft): string {
  return `${draft.kind}:${draft.namespace.trim()}/${draft.name.trim()}@${draft.version.trim()}`;
}

export function validateManifestDraft(draft: ManifestDraft): readonly ManifestIssue[] {
  const result = new ManifestValidator().validate(buildManifestDocument(draft));
  return result.ok ? [] : result.issues;
}

export function buildManifestYaml(draft: ManifestDraft): string {
  return serializeManifest(buildManifestDocument(draft));
}

export function buildManifestDocument(draft: ManifestDraft): ManifestDocument {
  return {
    schema_version: 1,
    kind: draft.kind,
    namespace: draft.namespace.trim(),
    name: draft.name.trim(),
    version: draft.version.trim(),
    title: draft.title.trim(),
    ...(draft.description.trim() ? { description: draft.description.trim() } : {}),
    ...(draft.license.trim() ? { license: draft.license.trim() } : {}),
    ...(draft.doi.trim() ? { doi: draft.doi.trim() } : {}),
    artifacts: draft.artifacts.map(buildArtifact),
    targets: {
      graph_level: splitTargets(draft.graphTargets),
      atom_level: splitTargets(draft.atomTargets),
    },
  };
}

function buildArtifact(draft: ArtifactDraft): ManifestArtifact {
  return {
    role: draft.role.trim(),
    filename: draft.filename.trim(),
    ...(draft.format.trim() ? { format: draft.format.trim() } : {}),
    ...(draft.mediaType.trim() ? { media_type: draft.mediaType.trim() } : {}),
    locators: draft.locators.map((locator) => locator.trim()),
    ...(draft.digest.trim() ? { digest: draft.digest.trim() } : {}),
    ...(draft.size.trim() && /^\d+$/.test(draft.size.trim())
      ? { size: Number(draft.size.trim()) }
      : {}),
  };
}

function splitTargets(value: string): string[] {
  return value
    .split(",")
    .map((target) => target.trim())
    .filter(Boolean);
}
