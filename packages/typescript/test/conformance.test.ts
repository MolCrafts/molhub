import { readFile, readdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "@rstest/core";
import yaml from "js-yaml";

import {
  AllLocatorsFailed,
  Coordinate,
  Digest,
  Fetcher,
  FileStore,
  InvalidCoordinate,
  InvalidDigest,
  ManifestValidator,
  type MolhubRegistry,
  Registry,
  type Source,
  Sources,
  digestBytes,
} from "../src/node.js";

// biome-ignore lint/suspicious/noExplicitAny: each YAML file intentionally has a different data-only shape.
type VectorCase = Record<string, any>;
const vectorRoot = path.resolve(import.meta.dirname, "../../../spec/conformance/vectors");
const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true })),
  );
});

function vector(name: string): VectorCase {
  return yaml.load(requireText(path.join(vectorRoot, name))) as VectorCase;
}

function requireText(file: string): string {
  const fs = process.getBuiltinModule("node:fs");
  if (!fs) throw new Error("Node fs is unavailable.");
  return fs.readFileSync(file, "utf8");
}

function cases(name: string): VectorCase[] {
  return vector(name).cases;
}

describe("coordinate conformance", () => {
  for (const testCase of cases("coordinate.yaml")) {
    it(testCase.name, () => {
      const expected = testCase.expect;
      if (expected.error) {
        expect(expected.error).toBe("invalid_coordinate");
        expect(() => Coordinate.parse(testCase.input)).toThrow(InvalidCoordinate);
        return;
      }
      const coordinate = Coordinate.parse(testCase.input);
      expect({
        kind: coordinate.kind,
        namespace: coordinate.namespace,
        name: coordinate.name,
        version: coordinate.version,
        canonical: coordinate.canonical,
        manifest_path: coordinate.manifestPath,
        cache_path: coordinate.cachePath,
      }).toEqual(expected);
    });
  }
});

describe("digest conformance", () => {
  for (const testCase of cases("digest.yaml")) {
    it(testCase.name, async () => {
      const expected = testCase.expect;
      if (expected.error) {
        expect(expected.error).toBe("invalid_digest");
        expect(() => Digest.parse(testCase.input)).toThrow(InvalidDigest);
        return;
      }
      const actual =
        "body_utf8" in testCase
          ? await digestBytes(new TextEncoder().encode(testCase.body_utf8), testCase.algorithm)
          : Digest.parse(testCase.input);
      expect(actual.toString()).toBe(expected.canonical);
    });
  }
});

describe("cache-layout conformance", () => {
  for (const testCase of cases("cache_layout.yaml")) {
    it(testCase.name, async () => {
      const root = await temporaryDirectory();
      const relative = path
        .relative(root, new FileStore(root).pathFor(testCase.key))
        .split(path.sep)
        .join("/");
      expect(relative).toBe(testCase.expect_path);
    });
  }
});

describe("manifest conformance", () => {
  const validator = new ManifestValidator();
  for (const testCase of cases("manifest.yaml")) {
    it(testCase.name, () => {
      const result = validator.validate(testCase.document);
      if (testCase.expect.valid) {
        expect(result.ok).toBe(true);
        return;
      }
      expect(result.ok).toBe(false);
      if (result.ok) throw new Error("Expected invalid manifest.");
      const stableCode = result.issues.some((issue) => issue.code === "duplicate_role")
        ? "duplicate_role"
        : "invalid_manifest";
      expect(stableCode).toBe(testCase.expect.error);
    });
  }
});

describe("registry conformance", () => {
  const document = vector("registry.yaml");
  const registry = new Registry(document.registry as MolhubRegistry);
  for (const testCase of document.cases) {
    it(testCase.name, () => {
      if (testCase.action === "resolve") {
        expect(registry.resolve(testCase.coordinate).coordinate).toBe(testCase.expect.coordinate);
        return;
      }
      const result = registry.search({ kind: testCase.kind, query: testCase.query });
      expect(result.map((entry) => entry.coordinate)).toEqual(testCase.expect.coordinates);
    });
  }
});

describe("fallback conformance", () => {
  for (const testCase of cases("fallback.yaml")) {
    it(testCase.name, async () => {
      const root = await temporaryDirectory();
      const store = new FileStore(root);
      const key = "dataset/molcrafts/example@v1/main";
      if (testCase.cached_body_utf8) {
        const cached = store.pathFor(key);
        await store.ensureTempParent(cached);
        await writeFile(cached, testCase.cached_body_utf8, "utf8");
      }

      let calls = 0;
      const source: Source = {
        scheme: "mock",
        async resolve(locator) {
          return [{ url: locator.toString(), filename: locator.path }];
        },
      };
      const fetcher = new Fetcher({
        sources: new Sources([source]),
        store,
        fetch: async (input) => {
          calls += 1;
          const response = testCase.responses[String(input)];
          return new Response(response.body_utf8, { status: response.status });
        },
      });

      if (testCase.expect.error) {
        expect(testCase.expect.error).toBe("all_locators_failed");
        await expect(fetcher.fetch(testCase.locators, key, testCase.digest)).rejects.toThrow(
          AllLocatorsFailed,
        );
      } else {
        const result = await fetcher.fetch(testCase.locators, key, testCase.digest);
        expect(await readFile(result, "utf8")).toBe(testCase.expect.body_utf8);
      }
      expect(calls).toBe(testCase.expect.network_calls);
      expect(await countFiles(path.join(root, "files"))).toBe(testCase.expect.files_written);
    });
  }
});

it("collects every language-neutral vector case", async () => {
  const names = (await readdir(vectorRoot)).filter((name) => name.endsWith(".yaml"));
  const expected = names.reduce((total, name) => total + cases(name).length, 0);
  expect(expected).toBe(25);
});

it("the runner rejects an intentionally wrong expectation", () => {
  expect(() =>
    expect(Coordinate.parse("qm9@v2").canonical).toBe("dataset:molcrafts/qm9@wrong"),
  ).toThrow();
});

async function temporaryDirectory(): Promise<string> {
  const fs = process.getBuiltinModule("node:fs/promises");
  if (!fs) throw new Error("Node fs/promises is unavailable.");
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "molhub-conformance-"));
  temporaryDirectories.push(directory);
  return directory;
}

async function countFiles(root: string): Promise<number> {
  try {
    const entries = await readdir(root, { withFileTypes: true, recursive: true });
    return entries.filter((entry) => entry.isFile()).length;
  } catch {
    return 0;
  }
}
