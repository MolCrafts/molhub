import { spawnSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const webRoot = path.resolve(import.meta.dirname, "..");
const repoRoot = path.resolve(webRoot, "../..");
const destinationDirectory = path.resolve(webRoot, ".generated");
const destination = path.resolve(destinationDirectory, "registry.json");

const python = process.env.MOLHUB_PYTHON ?? "uv";
const pythonArgs =
  python === "uv"
    ? [
        "run",
        "python",
        "-c",
        "from molhub.registry import Registry; import json; print(json.dumps(Registry.builtin().snapshot(), indent=2))",
      ]
    : [
        "-c",
        "from molhub.registry import Registry; import json; print(json.dumps(Registry.builtin().snapshot(), indent=2))",
      ];

const result = spawnSync(python, pythonArgs, {
  cwd: repoRoot,
  encoding: "utf8",
});
if (result.status !== 0) {
  throw new Error(
    [
      "Could not load artifacts from the molhub Python package.",
      "The Web catalog is Registry.builtin().snapshot() — there is no YAML registry to walk.",
      result.stderr?.trim() || result.stdout?.trim() || `exit ${result.status}`,
    ].join("\n"),
  );
}

const raw = result.stdout;
const snapshot: unknown = JSON.parse(raw);
if (!isRegistrySnapshot(snapshot)) {
  throw new Error(
    "Python Registry.builtin().snapshot() is not a supported MolHub registry snapshot (expected schema_version 1 and an entries array).",
  );
}

await mkdir(destinationDirectory, { recursive: true });
await writeFile(destination, `${JSON.stringify(snapshot, null, 2)}\n`, "utf8");

console.log(`Synced ${snapshot.entries.length} registry entries from molhub.Registry.builtin().`);

function isRegistrySnapshot(value: unknown): value is { schema_version: 1; entries: unknown[] } {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return candidate.schema_version === 1 && Array.isArray(candidate.entries);
}
