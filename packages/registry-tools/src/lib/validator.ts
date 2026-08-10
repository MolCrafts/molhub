import { relative } from "node:path";
import { ManifestValidator, manifestCoordinate } from "@molcrafts/molhub/core";

import type { ManifestDocument } from "@molcrafts/molhub/core";
import type { LoadedManifest, RegistrySource } from "./registry-source.js";
import type { Violation } from "./violation.js";

export class RegistryValidator {
  constructor(
    private readonly source: RegistrySource,
    private readonly manifests = new ManifestValidator(),
  ) {}

  run(): Violation[] {
    const loaded = this.source.load();
    return [
      ...this.checkPopulated(loaded),
      ...this.source.strayFiles().map((file) => ({
        where: file.relativePath,
        message: "This file is not a .yaml manifest and no MolHub client will read it.",
      })),
      ...loaded.flatMap((manifest) => this.checkManifest(manifest)),
    ];
  }

  private checkPopulated(loaded: readonly LoadedManifest[]): Violation[] {
    return loaded.length > 0
      ? []
      : [
          {
            where: this.source.root,
            message: "No manifests found here. Expected <kind>/<namespace>/<name>/<version>.yaml.",
          },
        ];
  }

  private checkManifest(loaded: LoadedManifest): Violation[] {
    if (loaded.error !== null) {
      return [
        {
          where: loaded.relativePath,
          message: `This file could not be read as YAML: ${loaded.error}`,
        },
      ];
    }
    const result = this.manifests.validate(loaded.data);
    if (!result.ok) {
      return result.issues.map((issue) => ({
        where: `${loaded.relativePath}${issue.path === "/" ? "" : issue.path}`,
        message: `[${issue.code}] ${issue.message}`,
      }));
    }
    return this.checkPath(loaded.relativePath, result.value);
  }

  private checkPath(relativePath: string, document: ManifestDocument): Violation[] {
    const coordinate = manifestCoordinate(document);
    if (coordinate.manifestPath === relativePath) return [];
    return [
      {
        where: relativePath,
        message: [
          "Filed at a path that does not match the coordinate inside it.",
          `Expected: ${coordinate.manifestPath}`,
          `Actual:   ${relativePath}`,
        ].join("\n"),
      },
    ];
  }
}

export function displayPath(path: string): string {
  const local = relative(process.env.INIT_CWD ?? process.cwd(), path);
  return local && !local.startsWith("..") ? local : path;
}
