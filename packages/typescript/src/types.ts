import type { ArtifactKind } from "./coordinate.js";

export interface ManifestArtifact {
  readonly role: string;
  readonly filename: string;
  readonly format?: string;
  readonly media_type?: string;
  readonly locators: string[];
  readonly digest?: string;
  readonly size?: number;
}

export interface ManifestDocument {
  readonly schema_version: 1;
  readonly kind: ArtifactKind;
  readonly namespace: string;
  readonly name: string;
  readonly version: string;
  readonly title: string;
  readonly description?: string;
  readonly license?: string;
  readonly doi?: string;
  readonly artifacts: ManifestArtifact[];
  readonly targets?: {
    readonly graph_level?: string[];
    readonly atom_level?: string[];
  };
}

export interface RegistryArtifact {
  readonly role: string;
  readonly filename: string;
  readonly format: string | null;
  readonly media_type: string | null;
  readonly locators: string[];
  readonly digest: string | null;
  readonly size: number | null;
}

export interface RegistryEntry {
  readonly coordinate: string;
  readonly kind: ArtifactKind;
  readonly namespace: string;
  readonly name: string;
  readonly version: string;
  readonly title: string;
  readonly description: string | null;
  readonly license: string | null;
  readonly doi: string | null;
  readonly targets: {
    readonly graph_level: string[];
    readonly atom_level: string[];
  };
  readonly artifacts: RegistryArtifact[];
}

export interface MolhubRegistry {
  readonly schema_version: 1;
  readonly entries: RegistryEntry[];
}
