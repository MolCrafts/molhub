import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "@rstest/core";

import { FileStore, Molhub } from "../src/node.js";
import { REGISTRY } from "./fixtures.js";

const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true })),
  );
});

describe("node Molhub", () => {
  it("streams a file into the Python-compatible cache and reuses it", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "molhub-js-"));
    temporaryDirectories.push(root);
    let calls = 0;
    const fetcher: typeof fetch = async () => {
      calls += 1;
      return new Response("data", { status: 200 });
    };
    const hub = new Molhub({ registry: REGISTRY, store: new FileStore(root), fetch: fetcher });

    const first = await hub.fetch("example@v1");
    const second = await hub.fetch("dataset:molcrafts/example@v1");

    expect(first.main).toBe(path.join(root, "files", "dataset", "molcrafts", "example@v1", "main"));
    expect(second).toEqual(first);
    expect(await readFile(first.main ?? "", "utf8")).toBe("data");
    expect(calls).toBe(1);
  });

  it("does not leave a cache file after a bad response", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "molhub-js-"));
    temporaryDirectories.push(root);
    const hub = new Molhub({
      registry: REGISTRY,
      store: new FileStore(root),
      fetch: async () => new Response(null, { status: 202 }),
    });
    await expect(hub.fetch("example@v1")).rejects.toThrow("returned HTTP 202");
    expect(await new FileStore(root).has("dataset/molcrafts/example@v1/main")).toBe(false);
  });
});
