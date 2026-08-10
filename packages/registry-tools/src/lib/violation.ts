/**
 * A finding, and the report a contributor reads.
 *
 * The message is the deliverable. Someone has just had a pull request rejected
 * by a program, and the only thing standing between them and giving up is the
 * text this file prints. So a violation is not an error code with a location —
 * it is a short statement of what is wrong, why it matters, and what to write
 * instead, addressed to someone who is not a molhub maintainer.
 */

/** One thing wrong with the registry. */
export interface Violation {
  /** Where to look: a repository-relative path, plus coordinate and role. */
  readonly where: string;
  /** What is wrong, why it matters, and exactly what to write instead. */
  readonly message: string;
}

const INDENT = "    ";

/** A set of findings, rendered for a terminal. */
export class ViolationReport {
  constructor(private readonly violations: readonly Violation[]) {}

  get isClean(): boolean {
    return this.violations.length === 0;
  }

  get count(): number {
    return this.violations.length;
  }

  /**
   * The full report.
   *
   * Findings are printed in the order they were produced — which is registry
   * order, file by file — so a contributor can work top to bottom instead of
   * hunting for the file each one belongs to.
   */
  render(): string {
    const blocks = this.violations.map((violation, position) => {
      const heading = `${position + 1}. ${violation.where}`;
      const body = violation.message
        .split("\n")
        .map((line) => (line === "" ? "" : INDENT + line))
        .join("\n");
      return `${heading}\n${body}`;
    });
    const noun = this.violations.length === 1 ? "problem" : "problems";
    return `${blocks.join("\n\n")}\n\n${this.violations.length} ${noun} found.`;
  }
}
