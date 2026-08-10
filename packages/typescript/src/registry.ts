import type { ValidateFunction } from "ajv";

import { Coordinate } from "./coordinate.js";
import type { ArtifactKind } from "./coordinate.js";
import { InvalidManifest, UnknownArtifact } from "./errors.js";
import validateRegistryDocument from "./generated-registry-validator.js";
import type { MolhubRegistry, RegistryEntry } from "./types.js";

export interface SearchQuery {
  readonly kind?: ArtifactKind;
  readonly query?: string;
}

const VALIDATE_REGISTRY = validateRegistryDocument as ValidateFunction;

export class Registry {
  readonly entries: readonly RegistryEntry[];
  readonly #byCoordinate: ReadonlyMap<string, RegistryEntry>;

  constructor(document: MolhubRegistry) {
    if (!VALIDATE_REGISTRY(document))
      throw new InvalidManifest("Registry does not match spec/registry.schema.yaml.");
    Registry.checkCoordinates(document.entries);
    this.entries = document.entries;
    this.#byCoordinate = new Map(document.entries.map((entry) => [entry.coordinate, entry]));
  }

  private static checkCoordinates(entries: readonly RegistryEntry[]): void {
    const seen = new Set<string>();
    let previous: string | undefined;
    for (const entry of entries) {
      const parsed = Coordinate.parse(entry.coordinate);
      if (
        parsed.kind !== entry.kind ||
        parsed.namespace !== entry.namespace ||
        parsed.name !== entry.name ||
        parsed.version !== entry.version
      ) {
        throw new InvalidManifest(`Registry entry fields disagree with ${entry.coordinate}.`);
      }
      if (seen.has(entry.coordinate))
        throw new InvalidManifest(`Registry contains ${entry.coordinate} twice.`);
      if (previous !== undefined && compare(previous, entry.coordinate) > 0) {
        throw new InvalidManifest("Registry entries are not ordered by coordinate.");
      }
      seen.add(entry.coordinate);
      previous = entry.coordinate;
    }
  }

  resolve(value: string | Coordinate): RegistryEntry {
    const coordinate = typeof value === "string" ? Coordinate.parse(value) : value;
    const entry = this.#byCoordinate.get(coordinate.canonical);
    if (entry) return entry;
    const versions = this.entries
      .filter(
        (candidate) =>
          Coordinate.parse(candidate.coordinate).unversioned === coordinate.unversioned,
      )
      .map((candidate) => candidate.version)
      .sort(compare);
    throw new UnknownArtifact(
      versions.length > 0
        ? `${coordinate.canonical} is not registered. Available versions: ${versions.join(", ")}.`
        : `${coordinate.canonical} is not registered.`,
    );
  }

  search(filters: SearchQuery = {}): RegistryEntry[] {
    const query = filters.query?.trim().toLocaleLowerCase();
    return this.entries
      .filter((entry) => filters.kind === undefined || entry.kind === filters.kind)
      .filter((entry) => !query || searchable(entry).includes(query))
      .slice()
      .sort((left, right) => compare(left.coordinate, right.coordinate));
  }
}

function searchable(entry: RegistryEntry): string {
  return [
    entry.coordinate,
    entry.title,
    entry.description ?? "",
    entry.license ?? "",
    ...entry.targets.graph_level,
    ...entry.targets.atom_level,
  ]
    .join("\n")
    .toLocaleLowerCase();
}

function compare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}
