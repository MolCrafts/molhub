/**
 * Prove the gate can fail.
 *
 *     npm run registry:test
 *
 * `test/fixtures/` holds complete, registry-shaped directories, each broken in
 * exactly one way. This runs `src/validate.ts` — the real program,
 * as a real process, so the exit code is proven and not just the message — once
 * per fixture, and asserts two things:
 *
 *   1. every broken registry is rejected, **for the reason it was written to
 *      test**. Merely checking that it was rejected would pass even if every
 *      fixture failed for the same unrelated reason;
 *   2. `good/` is accepted, so a fixture failing because of a bug in the
 *      validator shows up as `good/` failing too rather than as a false sense
 *      of coverage.
 *
 * A gate nobody has watched fail is not a gate. When a rule is added to
 * `ManifestValidator` or `lib/validator.ts`, a fixture is added here in the same
 * change: a rule without a fixture has never been proven to fire.
 */

import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { TOOL_ROOT } from "./lib/repo.js";

/** A registry the gate must refuse, and the words it must refuse it with. */
interface RejectedFixture {
  /** Directory under `test/fixtures/`. */
  readonly directory: string;
  /** A phrase the report must contain, identifying *which* rule fired. */
  readonly expects: string;
}

const REJECTED: readonly RejectedFixture[] = [
  { directory: "figshare-unpinned", expects: "Pin a Figshare article version" },
  { directory: "github-branch-ref", expects: "Pin GitHub URLs to a commit" },
  { directory: "hf-no-revision", expects: "Pin Hugging Face to a commit revision" },
  { directory: "hf-branch-revision", expects: "Pin Hugging Face to a commit revision" },
  { directory: "unknown-scheme", expects: "No MolHub source handles" },
  { directory: "missing-doi", expects: "Add the DOI for this exact published version" },
  { directory: "no-digest-no-size", expects: "[schema]" },
  { directory: "zero-size", expects: "[schema]" },
  {
    directory: "path-coordinate-mismatch",
    expects: "Filed at a path that does not match the coordinate inside it",
  },
  { directory: "duplicate-role", expects: 'Role "main" is declared more than once' },
  { directory: "malformed-yaml", expects: "could not be read as YAML" },
  { directory: "schema-violation", expects: "[schema]" },
  { directory: "stray-yml-file", expects: "no MolHub client will read it" },
  { directory: "empty-registry", expects: "No manifests found here" },
];

/** Registries the gate must accept, so that a broken gate cannot pass silently. */
const ACCEPTED: readonly string[] = ["good"];

const FIXTURES_DIR = join(TOOL_ROOT, "test", "fixtures");
const VALIDATE = join(TOOL_ROOT, "src", "validate.ts");

interface Outcome {
  readonly status: number;
  readonly output: string;
}

/**
 * Run the gate against one fixture directory.
 *
 * `node --import tsx` rather than the `tsx` shim, so the child is the same
 * runtime as the parent and needs nothing on `PATH`.
 */
function validate(directory: string): Outcome {
  const result = spawnSync(
    process.execPath,
    ["--import", "tsx", VALIDATE, join(FIXTURES_DIR, directory)],
    { cwd: TOOL_ROOT, encoding: "utf8" },
  );
  if (result.error !== undefined) throw result.error;
  return { status: result.status ?? -1, output: `${result.stdout}${result.stderr}` };
}

function main(): number {
  const failures: string[] = [];

  for (const fixture of REJECTED) {
    const { status, output } = validate(fixture.directory);
    if (status === 0) {
      failures.push(
        `${fixture.directory}: the gate ACCEPTED a registry that is broken. ` +
          `Expected it to object with "${fixture.expects}".`,
      );
      continue;
    }
    if (status !== 1) {
      failures.push(
        `${fixture.directory}: exited ${status}, which means the validator crashed rather than reporting a violation.\n${output}`,
      );
      continue;
    }
    if (!output.includes(fixture.expects)) {
      failures.push(
        `${fixture.directory}: rejected, but for the wrong reason. ` +
          `Expected the report to contain "${fixture.expects}".\n${output}`,
      );
      continue;
    }
    process.stdout.write(`  rejected  ${fixture.directory} — ${fixture.expects}\n`);
  }

  for (const directory of ACCEPTED) {
    const { status, output } = validate(directory);
    if (status !== 0) {
      failures.push(`${directory}: the gate REJECTED a valid registry.\n${output}`);
      continue;
    }
    process.stdout.write(`  accepted  ${directory}\n`);
  }

  if (failures.length > 0) {
    process.stderr.write(`\n${failures.length} fixture(s) behaved wrongly:\n\n`);
    for (const failure of failures) process.stderr.write(`${failure}\n\n`);
    return 1;
  }
  process.stdout.write(
    `\n${REJECTED.length} broken registry(s) rejected for the right reason, ` +
      `${ACCEPTED.length} valid one(s) accepted.\n`,
  );
  return 0;
}

process.exit(main());
