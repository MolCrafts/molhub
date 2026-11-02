import type { FileHandle } from "node:fs/promises";
import { mkdir, mkdtemp, open, readFile, readdir, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, rs } from "@rstest/core";

import { Fetcher, FileStore, Molhub } from "../src/node.js";
import { REGISTRY } from "./fixtures.js";

const temporaryDirectories: string[] = [];

afterEach(async () => {
  rs.restoreAllMocks();
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

  it("does not treat a directory as a cached file", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "molhub-js-"));
    temporaryDirectories.push(root);
    const store = new FileStore(root);
    await mkdir(store.pathFor("dataset/lab/example@v1/main"), { recursive: true });
    expect(await store.has("dataset/lab/example@v1/main")).toBe(false);
  });

  it.each([2, 0])("handles a filesystem write of %i bytes", async (limit) => {
    const root = await mkdtemp(path.join(os.tmpdir(), "molhub-js-"));
    temporaryDirectories.push(root);
    const sample = await open(path.join(root, "probe"), "w");
    const prototype: {
      write(
        this: FileHandle,
        buffer: Uint8Array,
      ): Promise<{ bytesWritten: number; buffer: Uint8Array }>;
    } = Object.getPrototypeOf(sample);
    const original = prototype.write;
    await sample.close();
    const writes = rs.spyOn(prototype, "write").mockImplementation(function (
      this: FileHandle,
      buffer: Uint8Array,
    ) {
      return original.call(this, buffer.subarray(0, limit));
    });
    const store = new FileStore(root);
    const fetcher = new Fetcher({ store, fetch: async () => new Response("payload") });
    if (limit === 0) {
      await expect(fetcher.fetch(["https://example.test/data"], "data")).rejects.toThrow(
        "no progress",
      );
      expect(await store.has("data")).toBe(false);
    } else {
      const result = await fetcher.fetch(["https://example.test/data"], "data");
      expect(await readFile(result, "utf8")).toBe("payload");
      expect(writes.mock.calls.length).toBeGreaterThan(1);
    }
    expect(await readdir(path.join(root, "tmp"))).toEqual([]);
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
