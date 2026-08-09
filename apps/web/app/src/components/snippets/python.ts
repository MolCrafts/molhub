import type { RegistryEntry } from "@/types/registry";
import { type Snippet, demonstrationRole, quote } from "./snippet";

/**
 * The Python snippet: `Molhub().resolve()` then `Molhub().fetch()`.
 *
 * Every call here is on the public surface documented in molhub's README —
 * `Molhub`, `resolve`, `fetch(coordinate, *, roles=...)`, and the
 * `dict[str, Path]` it returns keyed by role. Nothing is invented.
 */
export function pythonSnippet(entry: RegistryEntry): Snippet {
  const coordinate = quote(entry.coordinate);
  const role = demonstrationRole(entry);
  const roleCount = entry.artifacts.length;

  const lines = [
    "from molhub import Molhub",
    "",
    "hub = Molhub()",
    "",
    "# resolve() reads the registry only — no network, no download.",
    `manifest = hub.resolve(${coordinate})`,
    "print(manifest.title)",
    "print(manifest.license, manifest.doi)",
  ];

  if (roleCount > 1) {
    lines.push("print(list(manifest.artifacts))  # every role this coordinate declares");
  }

  lines.push("");
  lines.push("# fetch() downloads on the first call and returns the cached path after that.");

  if (role === null) {
    lines.push(`paths = hub.fetch(${coordinate})`);
    lines.push("print(paths)");
  } else if (roleCount > 1) {
    lines.push(
      `# This manifest declares ${roleCount} roles — ask for the one you need, not all of them.`,
    );
    lines.push(`paths = hub.fetch(${coordinate}, roles=[${quote(role)}])`);
    lines.push(`print(paths[${quote(role)}])`);
  } else {
    lines.push(`paths = hub.fetch(${coordinate})`);
    lines.push(`print(paths[${quote(role)}])`);
  }

  return {
    language: "python",
    label: "Python",
    caption: "pip install molhub",
    code: lines.join("\n"),
    commentPrefix: "#",
    availability: "runnable",
  };
}
