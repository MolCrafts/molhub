/**
 * The one sort order this repository uses.
 *
 * `Array.prototype.sort` without a comparator stringifies and compares by UTF-16
 * code unit, which is already deterministic — but the obvious "readable" fix,
 * `String.prototype.localeCompare`, is not: its result depends on the ICU data
 * and default locale of the machine running the build. A registry sorted under
 * `en-US` and one sorted under `tr-TR` would disagree about `I`, and
 * `dist/registry.json` would differ between two machines with an unchanged
 * registry. Code-point order is boring, stable everywhere, and therefore the
 * only order allowed here.
 */

/** Compare two strings by code point. Never locale-aware, by design. */
export function byCodePoint(left: string, right: string): number {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}
