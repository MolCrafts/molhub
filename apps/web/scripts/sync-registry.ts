import { copyFile, mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { RegistryBuilder } from "@molcrafts/molhub-registry-tools";

const webRoot = path.resolve(import.meta.dirname, "..");
const localRegistryArtifacts = path.resolve(webRoot, "../../../molhub-registry/artifacts");
const configuredSnapshot = process.env.MOLHUB_REGISTRY_JSON;
const destinationDirectory = path.resolve(webRoot, ".generated");
const destination = path.resolve(destinationDirectory, "registry.json");

await mkdir(destinationDirectory, { recursive: true });
const source = configuredSnapshot ? path.resolve(process.cwd(), configuredSnapshot) : destination;

if (configuredSnapshot) {
  await copyFile(source, destination);
} else {
  try {
    new RegistryBuilder().build(localRegistryArtifacts, destinationDirectory);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(
      [
        `Could not build the MolHub registry from ${localRegistryArtifacts}.`,
        "Keep molhub-registry beside molhub, or set MOLHUB_REGISTRY_JSON to a generated snapshot.",
        detail,
      ].join("\n"),
    );
  }
}

let raw: string;
try {
  raw = await readFile(destination, "utf8");
} catch (error) {
  const detail = error instanceof Error ? error.message : String(error);
  throw new Error(
    [`Could not read the MolHub registry snapshot at ${destination}.`, detail].join("\n"),
  );
}

const snapshot: unknown = JSON.parse(raw);
if (!isRegistrySnapshot(snapshot)) {
  throw new Error(
    `${source} is not a supported MolHub registry snapshot (expected schema_version 1 and an entries array).`,
  );
}

console.log(
  configuredSnapshot
    ? `Synced ${snapshot.entries.length} registry entries from ${source}.`
    : `Built ${snapshot.entries.length} registry entries from ${localRegistryArtifacts}.`,
);

function isRegistrySnapshot(value: unknown): value is { schema_version: 1; entries: unknown[] } {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return candidate.schema_version === 1 && Array.isArray(candidate.entries);
}
