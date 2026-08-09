/**
 * Where things live in this repository.
 *
 * Default paths are derived from this file's location. Explicit CLI paths are
 * resolved from npm's original invocation directory, not the workspace package
 * directory npm switches into before executing a script.
 *
 * None of these absolute paths may reach an emitted artefact. `dist/registry.json`
 * must be byte-identical between a contributor's laptop and CI, and a build
 * machine's home directory is exactly the kind of thing that quietly breaks
 * that.
 */

import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** Tool package root: this file is `<workspace>/packages/registry-tools/src/lib/repo.ts`. */
export const TOOL_ROOT = dirname(dirname(dirname(fileURLToPath(import.meta.url))));

/** MolHub product workspace, which owns the language-neutral contract. */
export const REPO_ROOT = dirname(dirname(TOOL_ROOT));

/** Local sibling used when a caller does not pass a registry path explicitly. */
export const DEFAULT_REGISTRY_ROOT = resolve(REPO_ROOT, "../molhub-registry");

/** The registry: `<kind>/<namespace>/<name>/<version>.yaml` beneath here. */
export const ARTIFACTS_DIR = join(DEFAULT_REGISTRY_ROOT, "artifacts");

/** Build output. Git-ignored; regenerated from `artifacts/` on every build. */
export const DIST_DIR = join(DEFAULT_REGISTRY_ROOT, "dist");

/** The contract one manifest answers to. Shared verbatim with the Python client. */
export const MANIFEST_SCHEMA = join(REPO_ROOT, "spec", "manifest.schema.yaml");

/** The contract the aggregate answers to. Consumed by the product Web and SDKs. */
export const REGISTRY_SCHEMA = join(REPO_ROOT, "spec", "registry.schema.yaml");

/** Resolve CLI input relative to the directory from which npm was invoked. */
export function commandPath(value: string | undefined, fallback: string): string {
  if (value === undefined) return fallback;
  return resolve(process.env.INIT_CWD ?? process.cwd(), value);
}
