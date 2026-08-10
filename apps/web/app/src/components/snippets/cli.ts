import { formatBytes } from "@/lib/bytes";
import type { RegistryEntry } from "@/types/registry";
import type { Snippet } from "./snippet";

/**
 * The shell snippet: `molhub info`, `molhub fetch --into`, `molhub cache verify`.
 *
 * These are the only three verbs and the only flag involved; `fetch` has no
 * role selector, so the snippet says so and points at the Python argument that
 * does, rather than inventing one.
 */
export function cliSnippet(entry: RegistryEntry): Snippet {
  const roleCount = entry.artifacts.length;
  const undigested = entry.artifacts.filter((artifact) => artifact.digest === null).length;
  const total = formatBytes(
    entry.artifacts.reduce((sum, artifact) => sum + (artifact.size ?? 0), 0),
  );

  const lines = [
    "# Everything the registry knows about this coordinate. Reads the bundled",
    "# registry — no network, no download.",
    `molhub info ${entry.coordinate}`,
    "",
    "# Download, then copy the files into ./data. Cached under $MOLHUB_HOME, so",
    "# a second run costs nothing.",
  ];

  if (roleCount > 1) {
    const size = total ? `, ${total}` : "";
    lines.push(
      `# fetch takes every role — ${roleCount} files${size} here. Python's roles=[…] takes one.`,
    );
  }

  lines.push(`molhub fetch ${entry.coordinate} --into ./data`);
  lines.push("");
  lines.push("# Re-check what is already cached against the digests upstream published.");

  if (undigested === roleCount) {
    lines.push(
      `# Upstream publishes no checksum for ${
        roleCount === 1 ? "this file" : `these ${roleCount} files`
      }, so they are counted`,
    );
    lines.push("# and skipped here rather than failing — there is nothing to check against.");
  } else if (undigested > 0) {
    lines.push(
      `# ${undigested} of ${roleCount} files publish no checksum upstream; those are counted and skipped.`,
    );
  }

  lines.push("molhub cache verify");

  return {
    language: "cli",
    label: "CLI",
    caption: "the molhub command, installed with the package",
    code: lines.join("\n"),
    commentPrefix: "#",
    availability: "runnable",
  };
}
