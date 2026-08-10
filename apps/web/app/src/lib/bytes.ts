/**
 * Byte counts, rendered the way a person reads them.
 *
 * Decimal units, because that is what Figshare, Zenodo and a `content-length`
 * header report — showing `146 MiB` beside an upstream page saying `153.6 MB`
 * would make a reader think two different files were being described.
 */

const UNITS = ["B", "kB", "MB", "GB", "TB"] as const;

/**
 * Format a byte count, e.g. `86.1 MB`.
 *
 * @param bytes Byte count. Negative and non-finite values are refused rather
 *   than rendered, because a size that cannot be true should not be displayed
 *   as if it were.
 * @returns The formatted size, or `null` when there is nothing truthful to show.
 */
export function formatBytes(bytes: number | null): string | null {
  if (bytes === null || !Number.isFinite(bytes) || bytes < 0) return null;

  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }

  const label = UNITS[unit] ?? "B";
  // Whole bytes stay whole; anything scaled gets one decimal, which is the
  // precision a reader can act on when deciding whether to start a download.
  return unit === 0 ? `${value} ${label}` : `${value.toFixed(1)} ${label}`;
}
