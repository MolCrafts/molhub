/**
 * RegistrySource — a directory of manifests laid out as
 * `<kind>/<namespace>/<name>/<version>.yaml`.
 *
 * The same layout the Python client's `RegistrySource` walks, so `artifacts/` can
 * be handed to `MOLHUB_REGISTRY` unchanged and resolve offline. That is the point
 * of the layout: this repository is not a service, it is a directory that
 * happens to also be published as one file.
 *
 * Loading never throws on a bad manifest. A malformed file is a *finding* — the
 * validator reports it with an explanation, and the build refuses to run — but
 * an exception thrown mid-walk would hide every other problem in the pull
 * request behind whichever file sorted first.
 */

import { type Dirent, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import yaml from "js-yaml";
import { byCodePoint } from "./order.js";

/** A manifest file that parsed as YAML. `data` still has to face the schema. */
export interface ParsedManifest {
  readonly relativePath: string;
  readonly data: unknown;
  readonly error: null;
}

/** A manifest file that did not survive `yaml.load`. */
export interface UnreadableManifest {
  readonly relativePath: string;
  readonly data: null;
  readonly error: string;
}

export type LoadedManifest = ParsedManifest | UnreadableManifest;

/** Every file that is not a `.yaml` manifest, so the gate can object to it. */
export interface StrayFile {
  readonly relativePath: string;
}

const MANIFEST_SUFFIX = ".yaml";

/** A directory of manifests. */
export class RegistrySource {
  constructor(private readonly rootDir: string) {}

  get root(): string {
    return this.rootDir;
  }

  /**
   * Manifest paths relative to the root, in code-point order.
   *
   * Sorting here rather than at each call site is what makes the build
   * reproducible: `readdirSync` order is filesystem-dependent, and a registry
   * whose entry order tracked inode allocation would produce a different
   * `dist/registry.json` on every machine.
   *
   * @throws If the root is not a readable directory. That is a wrong invocation,
   *   not a registry defect, and silently returning nothing would let a gate
   *   pointed at the wrong path report success.
   */
  manifestPaths(): string[] {
    return this.walk("").filter(isManifest).sort(byCodePoint);
  }

  /** Files under the root that no client will ever read. See {@link isManifest}. */
  strayFiles(): StrayFile[] {
    return this.walk("")
      .filter((path) => !isManifest(path))
      .sort(byCodePoint)
      .map((relativePath) => ({ relativePath }));
  }

  /** Read and YAML-parse every manifest, in {@link manifestPaths} order. */
  load(): LoadedManifest[] {
    return this.manifestPaths().map((relativePath) => this.read(relativePath));
  }

  private read(relativePath: string): LoadedManifest {
    try {
      const text = readFileSync(join(this.rootDir, relativePath), "utf8");
      return { relativePath, data: yaml.load(text), error: null };
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : String(cause);
      return { relativePath, data: null, error: detail };
    }
  }

  private walk(prefix: string): string[] {
    const absolute = prefix === "" ? this.rootDir : join(this.rootDir, prefix);
    let entries: Dirent[];
    try {
      entries = readdirSync(absolute, { withFileTypes: true });
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : String(cause);
      throw new Error(`Cannot read registry directory ${absolute}: ${detail}`);
    }
    const found: string[] = [];
    for (const entry of entries) {
      // Dotfiles are never registry content — `.DS_Store` and friends are not
      // committed, and objecting to one would fail the gate on a macOS laptop
      // for a reason the contributor cannot see in `git status`.
      if (entry.name.startsWith(".")) continue;
      // Posix separators unconditionally: the relative path is compared against
      // `Coordinate.relativePath`, which every molhub client spells with `/`.
      const relative = prefix === "" ? entry.name : `${prefix}/${entry.name}`;
      if (entry.isDirectory()) {
        found.push(...this.walk(relative));
      } else if (entry.isFile()) {
        found.push(relative);
      }
    }
    return found;
  }
}

/**
 * Whether a path is a manifest.
 *
 * The Python client globs `*.yaml` and nothing else, so a file named `.yml`,
 * `.json`, or `.yaml.bak` is not a manifest that molhub reads slowly — it is a
 * dataset that molhub never sees. That is the failure this repository exists to
 * prevent, so the gate names those files rather than skipping past them.
 */
function isManifest(relativePath: string): boolean {
  return relativePath.endsWith(MANIFEST_SUFFIX);
}
