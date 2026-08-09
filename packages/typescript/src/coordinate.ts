import { InvalidCoordinate } from "./errors.js";

export const ARTIFACT_KINDS = ["dataset", "model", "plugin"] as const;
export type ArtifactKind = (typeof ARTIFACT_KINDS)[number];

const SEGMENT = /^[a-z0-9][a-z0-9-]*$/;
const VERSION = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export class Coordinate {
  readonly kind: ArtifactKind;
  readonly namespace: string;
  readonly name: string;
  readonly version: string;

  constructor(kind: ArtifactKind, namespace: string, name: string, version: string) {
    if (!ARTIFACT_KINDS.includes(kind)) {
      throw new InvalidCoordinate(`Unknown kind ${JSON.stringify(kind)}.`);
    }
    for (const [label, value] of [
      ["namespace", namespace],
      ["name", name],
    ] as const) {
      if (!SEGMENT.test(value)) {
        throw new InvalidCoordinate(
          `Invalid ${label} ${JSON.stringify(value)}; use lowercase letters, digits, and hyphens.`,
        );
      }
    }
    if (!VERSION.test(version)) {
      throw new InvalidCoordinate(`Invalid version ${JSON.stringify(version)}.`);
    }
    this.kind = kind;
    this.namespace = namespace;
    this.name = name;
    this.version = version;
  }

  static parse(text: string): Coordinate {
    const candidate = text.trim();
    if (!candidate) throw new InvalidCoordinate("Coordinate must not be empty.");

    const colon = candidate.indexOf(":");
    const kindText = colon === -1 ? "dataset" : candidate.slice(0, colon);
    const rest = colon === -1 ? candidate : candidate.slice(colon + 1);
    if (!ARTIFACT_KINDS.includes(kindText as ArtifactKind)) {
      throw new InvalidCoordinate(`Unknown kind ${JSON.stringify(kindText)}.`);
    }

    const at = rest.lastIndexOf("@");
    if (at === -1)
      throw new InvalidCoordinate(`Coordinate ${JSON.stringify(text)} is missing @version.`);
    const body = rest.slice(0, at);
    const version = rest.slice(at + 1);
    if (!version)
      throw new InvalidCoordinate(`Coordinate ${JSON.stringify(text)} has an empty version.`);

    const slash = body.indexOf("/");
    const namespace = slash === -1 ? "molcrafts" : body.slice(0, slash);
    const name = slash === -1 ? body : body.slice(slash + 1);
    if (!name) throw new InvalidCoordinate(`Coordinate ${JSON.stringify(text)} has an empty name.`);
    return new Coordinate(kindText as ArtifactKind, namespace, name, version);
  }

  get canonical(): string {
    return `${this.kind}:${this.namespace}/${this.name}@${this.version}`;
  }

  get unversioned(): string {
    return `${this.kind}:${this.namespace}/${this.name}`;
  }

  get manifestPath(): string {
    return `${this.kind}/${this.namespace}/${this.name}/${this.version}.yaml`;
  }

  get cachePath(): string {
    return `${this.kind}/${this.namespace}/${this.name}@${this.version}`;
  }

  toString(): string {
    return this.canonical;
  }
}
