import type { RegistryEntry } from "@/types/registry";

/**
 * What a copy-paste snippet is, independent of which language renders it.
 *
 * `RegistryEntry` is the language-neutral data contract and cannot grow methods,
 * so the three renderers are free functions over it rather than methods on a
 * type — the one case the house style leaves open for a free operation.
 */

export type SnippetLanguage = "python" | "cli" | "typescript";

/**
 * `runnable` means the snippet works against a package that exists today.
 * `forthcoming` means it does not, and the panel says so rather than implying
 * an install that would fail.
 */
export type SnippetAvailability = "runnable" | "forthcoming";

export interface Snippet {
  readonly language: SnippetLanguage;
  /** Tab label. */
  readonly label: string;
  /** One line above the code: what running it actually does. */
  readonly caption: string;
  readonly code: string;
  /** Line prefix that starts a comment, so the block can dim commentary. */
  readonly commentPrefix: string;
  readonly availability: SnippetAvailability;
}

/**
 * Roles that exist to accompany the data rather than to be the data.
 *
 * Demonstrating `hub.fetch(..., roles=["readme"])` would technically run and
 * teach the wrong thing.
 */
const COMPANION_ROLES: ReadonlySet<string> = new Set(["readme", "license", "citation", "exclude"]);

/**
 * The role a snippet should demonstrate, or `null` when there is nothing to
 * demonstrate.
 *
 * `main` wins when the manifest declares it. Otherwise the first role that is
 * not a companion file, because revMD17's eleven roles start at `aspirin` and
 * end at `readme`, and a snippet must not teach the reader to download the
 * readme.
 */
export function demonstrationRole(entry: RegistryEntry): string | null {
  const named = entry.artifacts.find((artifact) => artifact.role === "main");
  if (named) return named.role;

  const substantive = entry.artifacts.find((artifact) => !COMPANION_ROLES.has(artifact.role));
  if (substantive) return substantive.role;

  const first = entry.artifacts[0];
  return first ? first.role : null;
}

/**
 * Quote a value for a source string.
 *
 * Coordinates and roles are constrained to `[A-Za-z0-9._-]` plus the coordinate
 * punctuation, so JSON quoting is exact in Python, shell-free contexts, and
 * TypeScript alike.
 */
export function quote(value: string): string {
  return JSON.stringify(value);
}
