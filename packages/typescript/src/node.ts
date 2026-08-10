import { readFile } from "node:fs/promises";

import { type ArtifactKind, Coordinate } from "./coordinate.js";
import { Fetcher, type FetcherOptions } from "./fetcher.js";
import { BoundedJsonReader } from "./json-response.js";
import { Registry, type SearchQuery } from "./registry.js";
import type { MolhubRegistry, RegistryEntry } from "./types.js";

export interface NodeMolhubOptions extends FetcherOptions {
  readonly registry?: MolhubRegistry | string;
}

export class Molhub {
  readonly #registry: Promise<Registry>;
  readonly #fetcher: Fetcher;

  constructor(options: NodeMolhubOptions = {}) {
    const input =
      options.registry ?? process.env.MOLHUB_REGISTRY_JSON ?? process.env.MOLHUB_REGISTRY_URL;
    if (!input) {
      throw new Error("Pass registry, set MOLHUB_REGISTRY_JSON, or set MOLHUB_REGISTRY_URL.");
    }
    this.#registry = loadRegistry(input, options.fetch ?? globalThis.fetch);
    this.#fetcher = new Fetcher(options);
  }

  async resolve(coordinate: string): Promise<RegistryEntry> {
    return (await this.#registry).resolve(coordinate);
  }

  async search(filters: SearchQuery = {}): Promise<RegistryEntry[]> {
    return (await this.#registry).search(filters);
  }

  async fetch(
    coordinateText: string,
    options: { readonly roles?: readonly string[] } = {},
  ): Promise<Record<string, string>> {
    const coordinate = Coordinate.parse(coordinateText);
    const entry = (await this.#registry).resolve(coordinate);
    const roles = options.roles ?? entry.artifacts.map((artifact) => artifact.role);
    const files: Record<string, string> = {};
    for (const role of roles) {
      const artifact = entry.artifacts.find((candidate) => candidate.role === role);
      if (!artifact)
        throw new Error(`${entry.coordinate} does not declare role ${JSON.stringify(role)}.`);
      files[role] = await this.#fetcher.fetch(
        artifact.locators,
        `${coordinate.cachePath}/${role}`,
        artifact.digest,
      );
    }
    return files;
  }
}

async function loadRegistry(
  input: MolhubRegistry | string,
  fetcher: typeof globalThis.fetch,
): Promise<Registry> {
  if (typeof input !== "string") return new Registry(input);
  if (/^https?:\/\//.test(input)) {
    const response = await fetcher(input, { headers: { accept: "application/json" } });
    if (!response.ok) throw new Error(`Registry ${input} returned HTTP ${response.status}.`);
    return new Registry(
      (await new BoundedJsonReader(32 * 1024 * 1024).read(response)) as MolhubRegistry,
    );
  }
  return new Registry(JSON.parse(await readFile(input, "utf8")) as MolhubRegistry);
}

export { Coordinate, type ArtifactKind } from "./coordinate.js";
export { Digest, digestBytes } from "./digest.js";
export * from "./errors.js";
export { Fetcher, type FetcherOptions } from "./fetcher.js";
export { FileStore } from "./file-store.js";
export { ManifestValidator, serializeManifest } from "./manifest.js";
export { Registry, type SearchQuery } from "./registry.js";
export {
  DirectSource,
  FigshareSource,
  HuggingFaceSource,
  MolhubSource,
  Sources,
  ZenodoSource,
  type RemoteFile,
  type Source,
} from "./source.js";
export type * from "./types.js";
