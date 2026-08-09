import { InvalidLocator } from "./errors.js";

export class Locator {
  readonly scheme: string;
  readonly path: string;

  constructor(scheme: string, path: string) {
    if (!scheme || !path) throw new InvalidLocator("A locator needs both a scheme and a path.");
    this.scheme = scheme.toLowerCase();
    this.path = path;
  }

  static parse(text: string): Locator {
    const separator = text.trim().indexOf("://");
    if (separator <= 0 || separator === text.trim().length - 3) {
      throw new InvalidLocator(
        `Malformed locator ${JSON.stringify(text)}; expected scheme://path.`,
      );
    }
    const candidate = text.trim();
    return new Locator(candidate.slice(0, separator), candidate.slice(separator + 3));
  }

  toString(): string {
    return `${this.scheme}://${this.path}`;
  }
}
