import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const temporary = await mkdtemp(path.join(os.tmpdir(), "molhub-cli-parity-"));
const registryRoot = path.join(temporary, "registry");
const manifestPath = path.join(registryRoot, "dataset", "lab", "sample", "v1.yaml");
const snapshotPath = path.join(temporary, "registry.json");
const cacheRoot = path.join(temporary, "cache");

try {
  await mkdir(path.dirname(manifestPath), { recursive: true });
  await writeFile(
    manifestPath,
    [
      "schema_version: 1",
      "kind: dataset",
      "namespace: lab",
      "name: sample",
      "version: v1",
      "title: Shared CLI fixture",
      "license: CC0-1.0",
      "doi: 10.0000/sample",
      "artifacts:",
      "  - role: main",
      "    filename: sample.xyz",
      "    format: extxyz",
      "    media_type: chemical/x-xyz",
      "    size: 4",
      "    locators: [https://example.invalid/sample.xyz]",
      "  - role: readme",
      "    filename: readme.txt",
      "    format: text",
      "    media_type: text/plain",
      "    size: 4",
      "    locators: [https://example.invalid/readme.txt]",
      "targets:",
      "  graph_level: [energy]",
      "  atom_level: [forces]",
      "",
    ].join("\n"),
  );
  await writeFile(
    snapshotPath,
    `${JSON.stringify(
      {
        schema_version: 1,
        entries: [
          {
            coordinate: "dataset:lab/sample@v1",
            kind: "dataset",
            namespace: "lab",
            name: "sample",
            version: "v1",
            title: "Shared CLI fixture",
            description: null,
            license: "CC0-1.0",
            doi: "10.0000/sample",
            targets: { graph_level: ["energy"], atom_level: ["forces"] },
            artifacts: [
              {
                role: "main",
                filename: "sample.xyz",
                format: "extxyz",
                media_type: "chemical/x-xyz",
                locators: ["https://example.invalid/sample.xyz"],
                digest: null,
                size: 4,
              },
              {
                role: "readme",
                filename: "readme.txt",
                format: "text",
                media_type: "text/plain",
                locators: ["https://example.invalid/readme.txt"],
                digest: null,
                size: 4,
              },
            ],
          },
        ],
      },
      null,
      2,
    )}\n`,
  );
  for (const role of ["main", "readme"]) {
    const cached = path.join(cacheRoot, "files", "dataset", "lab", "sample@v1", role);
    await mkdir(path.dirname(cached), { recursive: true });
    await writeFile(cached, "data");
  }

  const environment = { ...process.env, MOLHUB_HOME: cacheRoot };
  const python = (args: readonly string[]) =>
    run("uv", ["run", "molhub", ...args, "--registry", registryRoot], environment);
  const node = (args: readonly string[]) =>
    run(
      process.execPath,
      [path.join(root, "packages/typescript/dist/cli.js"), ...args, "--registry", snapshotPath],
      environment,
    );

  assertEqual("search coordinates", coordinates(python(["search", "sample"])), coordinates(node(["search", "sample"])));
  const coordinate = "dataset:lab/sample@v1";
  assertEqual("info coordinate", coordinates(python(["info", coordinate])), coordinates(node(["info", coordinate])));
  assertEqual("info roles", bracketedRoles(python(["info", coordinate])), bracketedRoles(node(["info", coordinate])));
  assertEqual("fetch roles", fetchedRoles(python(["fetch", coordinate])), fetchedRoles(node(["fetch", coordinate])));
  process.stdout.write("Python and Node CLIs agree on search, info, fetch, coordinates, and roles.\n");
} finally {
  await rm(temporary, { recursive: true });
}

function run(command: string, args: readonly string[], env: NodeJS.ProcessEnv): string {
  const result = spawnSync(command, args, { cwd: root, env, encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed:\n${result.stderr}\n${result.stdout}`);
  }
  return result.stdout;
}

function coordinates(output: string): string[] {
  return [...output.matchAll(/(?:dataset|model|plugin):[a-z0-9-]+\/[a-z0-9-]+@[A-Za-z0-9._-]+/g)].map(
    ([coordinate]) => coordinate,
  );
}

function bracketedRoles(output: string): string[] {
  return [...output.matchAll(/^  \[([^\]]+)\]/gm)].map(([, role]) => role).filter(Boolean).sort();
}

function fetchedRoles(output: string): string[] {
  return output.split("\n").filter(Boolean).map((line) => line.split("\t", 1)[0] ?? "").sort();
}

function assertEqual(label: string, left: readonly string[], right: readonly string[]): void {
  if (JSON.stringify(left) !== JSON.stringify(right)) {
    throw new Error(`${label} differ: Python=${JSON.stringify(left)}, Node=${JSON.stringify(right)}`);
  }
}
