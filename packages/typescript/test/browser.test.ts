import { describe, expect, it } from "@rstest/core";

import { Molhub } from "../src/browser.js";
import { REGISTRY } from "./fixtures.js";

describe("browser Molhub", () => {
  it("resolves and searches without exposing a byte fetcher", async () => {
    const hub = new Molhub({ registry: REGISTRY });
    expect((await hub.resolve("example@v1")).title).toBe("Example molecular dataset");
    expect(await hub.search({ query: "forces" })).toHaveLength(1);
    expect("fetch" in hub).toBe(false);
  });

  it("rejects a malformed registry snapshot", async () => {
    const hub = new Molhub({ registry: { schema_version: 1, entries: [{}] } as never });
    await expect(hub.search()).rejects.toThrow("registry.schema.yaml");
  });
});
