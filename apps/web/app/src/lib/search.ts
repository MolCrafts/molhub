/**
 * Client-side search over the registry.
 *
 * The whole registry is in memory — four entries today, and a registry that
 * would still be a few hundred kilobytes at a thousand — so this is a
 * substring scan, not an inverted registry. Nothing here is async and nothing
 * hits the network.
 */

import type { RegistryEntry } from "@/types/registry";

interface Indexed {
  readonly entry: RegistryEntry;
  /** Every searchable field of one entry, lowercased and joined. */
  readonly haystack: string;
}

/**
 * Search prepared once over a fixed set of entries.
 *
 * The haystacks are built in the constructor rather than per keystroke: a
 * researcher types into this on every character, and re-lowercasing every
 * description each time is work with no result to show for it.
 */
export class RegistrySearch {
  readonly #indexed: Indexed[];

  constructor(entries: readonly RegistryEntry[]) {
    this.#indexed = entries.map((entry) => ({ entry, haystack: haystackOf(entry) }));
  }

  /**
   * Entries matching every whitespace-separated token in `query`.
   *
   * AND rather than OR, because narrowing is what a query is for: `qm9 energy`
   * should mean "qm9 *and* energy", and an OR would answer with every dataset
   * that declares an energy target. An empty query matches everything.
   *
   * Results keep the registry's own order (by coordinate). Relevance ranking is
   * deliberately absent — a scanner reading a table benefits more from rows
   * staying where they were than from a score they cannot see.
   */
  matches(query: string): RegistryEntry[] {
    const tokens = query
      .toLowerCase()
      .split(/\s+/)
      .filter((token) => token !== "");
    return this.#indexed
      .filter(({ haystack }) => tokens.every((token) => haystack.includes(token)))
      .map(({ entry }) => entry);
  }
}

/**
 * What is searchable, stated once.
 *
 * The coordinate carries kind, namespace, name and version, so those need no
 * separate entry. Targets are included because "which datasets have forces?"
 * is the question this registry exists to answer, and roles and filenames are
 * included because an entry's files are how people name it out loud —
 * `aspirin` should find revMD17 even though the word appears nowhere else.
 */
function haystackOf(entry: RegistryEntry): string {
  const parts = [
    entry.coordinate,
    entry.title,
    entry.description ?? "",
    entry.license ?? "",
    ...entry.targets.graph_level,
    ...entry.targets.atom_level,
    ...entry.artifacts.map((artifact) => artifact.role),
    ...entry.artifacts.map((artifact) => artifact.filename),
  ];
  return parts.join("\n").toLowerCase();
}
