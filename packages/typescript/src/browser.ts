import { BoundedJsonReader } from "./json-response.js";
import { Registry, type SearchQuery } from "./registry.js";
import type { MolhubRegistry, RegistryEntry } from "./types.js";

export interface BrowserMolhubOptions {
  readonly registry: MolhubRegistry | string;
  readonly fetch?: typeof globalThis.fetch;
}

export class Molhub {
  readonly #registry: Promise<Registry>;

  constructor(options: BrowserMolhubOptions) {
    this.#registry = loadRegistry(options.registry, options.fetch ?? globalThis.fetch);
  }

  async resolve(coordinate: string): Promise<RegistryEntry> {
    return (await this.#registry).resolve(coordinate);
  }

  async search(filters: SearchQuery = {}): Promise<RegistryEntry[]> {
    return (await this.#registry).search(filters);
  }
}

async function loadRegistry(
  input: MolhubRegistry | string,
  fetcher: typeof globalThis.fetch,
): Promise<Registry> {
  if (typeof input !== "string") return new Registry(input);
  const response = await fetcher(input, { headers: { accept: "application/json" } });
  if (!response.ok) throw new Error(`Registry ${input} returned HTTP ${response.status}.`);
  return new Registry(
    (await new BoundedJsonReader(32 * 1024 * 1024).read(response)) as MolhubRegistry,
  );
}

export { Coordinate, type ArtifactKind } from "./coordinate.js";
export { ManifestValidator, serializeManifest } from "./manifest.js";
export { Registry, type SearchQuery } from "./registry.js";
export type * from "./types.js";
