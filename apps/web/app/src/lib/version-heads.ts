/**
 * Which version of an artifact is the current one.
 *
 * The registry holds one entry per *version*, and nothing in a manifest says "this
 * one is superseded" — a published `<version>.yaml` never changes meaning, so
 * the fact that a newer sibling exists can only be read off the registry as a
 * whole. That is the `archival` tone in the design system's state vocabulary,
 * and this is where it is decided.
 */

import type { RegistryEntry } from "@/types/registry";

/** `kind:namespace/name` — the coordinate with its version removed. */
function familyOf(entry: RegistryEntry): string {
  return `${entry.kind}:${entry.namespace}/${entry.name}`;
}

/**
 * Compare two version strings, newest last.
 *
 * The registry's versions are upstream's own labels — `v2`, `v4`, `1` — so
 * this understands exactly the shape that appears there: an optional `v` and a
 * number. `v10` must sort after `v9`, which a plain string comparison gets
 * wrong. Anything else falls back to code-point order, which is at least
 * stable and matches how `build-registry.ts` orders the file.
 */
function compareVersions(left: string, right: string): number {
  const a = numericPart(left);
  const b = numericPart(right);
  if (a !== null && b !== null && a !== b) return a - b;
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

function numericPart(version: string): number | null {
  const digits = /^v?(\d+)$/.exec(version)?.[1];
  return digits === undefined ? null : Number(digits);
}

/**
 * The head version of every artifact family in a set of entries.
 *
 * Built from whatever entries it is given rather than from a module-level
 * registry, so a page renders the same answer for the set it is actually
 * showing and stays testable with a handful of literals.
 */
export class VersionHeads {
  readonly #headByFamily: Map<string, RegistryEntry>;

  constructor(entries: readonly RegistryEntry[]) {
    const heads = new Map<string, RegistryEntry>();
    for (const entry of entries) {
      const family = familyOf(entry);
      const incumbent = heads.get(family);
      if (incumbent === undefined || compareVersions(incumbent.version, entry.version) < 0) {
        heads.set(family, entry);
      }
    }
    this.#headByFamily = heads;
  }

  /**
   * The newer entry that supersedes this one, or `null` when it is the head.
   *
   * A superseded entry is still resolvable and still correct — someone's
   * pinned coordinate depends on it — so this is a note, never a warning.
   */
  supersessorOf(entry: RegistryEntry): RegistryEntry | null {
    const head = this.#headByFamily.get(familyOf(entry));
    if (head === undefined || head.coordinate === entry.coordinate) return null;
    return head;
  }
}
