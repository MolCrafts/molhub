/**
 * What one registry entry says about itself, reduced to the things a scanner
 * decides on.
 *
 * The design system fixes the vocabulary — `neutral`, `attested`, `caution`,
 * `archival` — and its README fixes the mapping from manifest fields to tones.
 * This module is that mapping, in one place, so a badge in the directory and a
 * badge anywhere else cannot disagree about what "no digest" means. The
 * components downstream only render what they are handed.
 *
 * Each `Signal` carries its own explanation. That is not decoration: `single
 * source` and `no digest` are consequential facts about whether an entry will
 * still resolve next year, and a badge that cannot explain itself is a badge a
 * reader learns to ignore.
 */

import type { BadgeTone } from "@/components/ui/badge";
import type { RegistryEntry } from "@/types/registry";

export interface Signal {
  readonly tone: BadgeTone;
  /** Badge text. Short enough for an 11px chip. */
  readonly label: string;
  /** The sentence behind the chip, shown on hover and on focus. */
  readonly detail: string;
}

export interface TargetChip {
  readonly label: string;
  /** `graph` is one value per structure; `atom` is one value per atom. */
  readonly scope: "graph" | "atom";
}

export interface EntrySize {
  readonly bytes: number;
  /** `false` when at least one artifact publishes no size, so `bytes` is a floor. */
  readonly complete: boolean;
}

/** The derived reading of one entry. Cheap enough to build per render. */
export class EntryFacts {
  readonly #entry: RegistryEntry;

  constructor(entry: RegistryEntry) {
    this.#entry = entry;
  }

  get fileCount(): number {
    return this.#entry.artifacts.length;
  }

  /** Total download size. `complete: false` means "at least this much". */
  get size(): EntrySize {
    let bytes = 0;
    let complete = true;
    for (const artifact of this.#entry.artifacts) {
      if (artifact.size === null) complete = false;
      else bytes += artifact.size;
    }
    return { bytes, complete };
  }

  /** Declared targets, graph-level first — the order a manifest lists them in. */
  get targets(): TargetChip[] {
    const { graph_level, atom_level } = this.#entry.targets;
    return [
      ...graph_level.map((label): TargetChip => ({ label, scope: "graph" })),
      ...atom_level.map((label): TargetChip => ({ label, scope: "atom" })),
    ];
  }

  get licence(): Signal {
    const license = this.#entry.license;
    if (license === null) {
      return {
        tone: "caution",
        label: "licence unstated",
        detail:
          "This manifest records no SPDX identifier, so the terms of reuse are whatever upstream says elsewhere. Check before redistributing.",
      };
    }
    return {
      tone: "neutral",
      label: license,
      detail: `SPDX identifier ${license}, copied from what upstream publishes.`,
    };
  }

  /**
   * Whether upstream published a checksum for every file.
   *
   * A digest is an optional secondary cross-check here, never an integrity
   * anchor molhub invents: a value computed locally would attest only to one
   * download. So the absence of one is a fact about the *host*, not a defect in
   * the manifest — the wording says so, and the tone is caution rather than
   * critical.
   */
  get integrity(): Signal {
    const artifacts = this.#entry.artifacts;
    const digested = artifacts.filter((artifact) => artifact.digest !== null);

    if (digested.length === 0) {
      return {
        tone: "caution",
        label: "no digest",
        detail:
          "This host publishes no checksum, and molhub never computes one of its own. A finished transfer is checked against the byte count instead.",
      };
    }

    const algorithms = [
      ...new Set(digested.map((artifact) => algorithmOf(artifact.digest))),
    ].sort();
    if (digested.length === artifacts.length) {
      return {
        tone: "attested",
        label: algorithms.join(" · "),
        detail: `Every file carries the ${algorithms.join(" and ")} checksum its host published, copied verbatim and checked after a fetch.`,
      };
    }

    return {
      tone: "caution",
      label: `${artifacts.length - digested.length} of ${artifacts.length} undigested`,
      detail: `${digested.length} file(s) carry a published checksum; the rest are checked against their byte count, because their host publishes none.`,
    };
  }

  /**
   * How many places each file can be fetched from, at its worst.
   *
   * The minimum across artifacts, not the average: an entry is only as
   * resolvable as its least-mirrored file.
   */
  get sources(): Signal {
    const counts = this.#entry.artifacts.map((artifact) => artifact.locators.length);
    const fewest = counts.length === 0 ? 0 : Math.min(...counts);

    if (fewest === 0) {
      return {
        tone: "caution",
        label: "unfetchable",
        detail:
          "At least one file in this entry lists no locator at all, so there is nowhere for molhub to fetch it from.",
      };
    }
    if (fewest === 1) {
      return {
        tone: "caution",
        label: "single source",
        detail:
          "Every file has exactly one place to come from. If that host stops serving it, the coordinate stops resolving — there is no mirror to fall back to.",
      };
    }
    return {
      tone: "attested",
      label: `${fewest} mirrors`,
      detail: `Every file lists at least ${fewest} sources, tried in the order the manifest gives them.`,
    };
  }

  /** Artifacts with no locator at all — an entry that cannot be fetched. */
  get unlocatedCount(): number {
    return this.#entry.artifacts.filter((artifact) => artifact.locators.length === 0).length;
  }
}

/** `md5:abc…` → `md5`. Whatever the platform published, unaltered. */
function algorithmOf(digest: string | null): string {
  if (digest === null) return "digest";
  const [algorithm] = digest.split(":");
  return algorithm === undefined || algorithm === "" ? "digest" : algorithm;
}
