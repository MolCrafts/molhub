/**
 * The registry, baked into the bundle at build time.
 *
 * `.generated/registry.json` is *imported*, not fetched. Registry discovery
 * ships as static files, so a runtime `fetch("registry.json")` would buy nothing
 * and cost three things:
 *
 *   - a second round trip before the first row can render;
 *   - a loading state and an error state for a file that is guaranteed to be
 *     sitting next to the bundle;
 *   - the site not working at all over `file://`, where a relative fetch is
 *     blocked as a cross-origin request.
 *
 * It also changes *when* a missing registry is discovered. An import that cannot
 * be resolved stops the bundler with the path it looked for; a fetch that 404s
 * renders an empty registry that looks merely disappointing. `registry:sync`
 * materializes the explicit snapshot input before Rsbuild starts. The Web app
 * never walks `molhub-registry/artifacts` or owns registry compilation.
 */

import {
  type MolhubRegistry,
  Registry as MolhubRegistryReader,
  type RegistryEntry,
  UnknownArtifact,
} from "@molcrafts/molhub/core";

import registryData from "../../../.generated/registry.json";

/**
 * Every entry in the registry, addressable by coordinate.
 *
 * Construction is a one-shot projection: an array to iterate in the order the
 * generator chose, and a map to answer a URL with. Nothing here re-sorts or
 * re-groups — `build-registry.ts` already emits entries ordered by coordinate, and
 * a second opinion about ordering in the client is how two views of the same
 * registry start disagreeing.
 */
export class Registry {
  /**
   * Ordered by coordinate, as generated.
   *
   * Typed mutable rather than `readonly` because the page components take
   * `RegistryEntry[]`; treat it as frozen. Nothing in this app writes to it.
   */
  readonly entries: RegistryEntry[];

  readonly #registry: MolhubRegistryReader;

  constructor(registry: MolhubRegistry) {
    this.#registry = new MolhubRegistryReader(registry);
    this.entries = [...this.#registry.entries];
  }

  /** The entry a coordinate names, or `undefined` when the registry has no such entry. */
  entry(coordinate: string): RegistryEntry | undefined {
    try {
      return this.#registry.resolve(coordinate);
    } catch (error) {
      if (error instanceof UnknownArtifact) return undefined;
      throw error;
    }
  }
}

/**
 * The one registry this bundle was built around.
 *
 * A module constant rather than a provider: the data is static, identical for
 * every viewer, and already in memory before React starts. Threading it through
 * context would add a seam with nothing on the other side of it.
 */
export const REGISTRY = new Registry(registryData as MolhubRegistry);
