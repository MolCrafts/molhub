export class MolhubError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

export class InvalidCoordinate extends MolhubError {}
export class InvalidLocator extends MolhubError {}
export class InvalidDigest extends MolhubError {}
export class InvalidManifest extends MolhubError {}
export class UnknownArtifact extends MolhubError {}
export class UnknownScheme extends MolhubError {}
export class BadStatus extends MolhubError {}
export class DigestMismatch extends MolhubError {}

export class AllLocatorsFailed extends MolhubError {
  readonly reasons: ReadonlyArray<readonly [string, Error]>;

  constructor(reasons: ReadonlyArray<readonly [string, Error]>) {
    const detail = reasons.map(
      ([locator, error]) => `  ${locator} -> ${error.name}: ${error.message}`,
    );
    super(
      reasons.length === 0
        ? "No locators were supplied."
        : `All ${reasons.length} locator(s) failed:\n${detail.join("\n")}`,
    );
    this.reasons = reasons;
  }
}
