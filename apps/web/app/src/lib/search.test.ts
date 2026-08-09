import { describe, expect, it } from "@rstest/core";

import { REGISTRY } from "@/lib/registry";
import { RegistrySearch } from "@/lib/search";

describe("RegistrySearch", () => {
  const search = new RegistrySearch(REGISTRY.entries);

  it("matches every token across scientific metadata", () => {
    const results = search.matches("qm9 homo");

    expect(results.map((entry) => entry.coordinate)).toEqual(["dataset:molcrafts/qm9@v2"]);
  });

  it("matches roles and filenames without changing registry order", () => {
    expect(search.matches("aspirin")[0]?.coordinate).toBe("dataset:molcrafts/revmd17@v4");
    expect(search.matches("")).toEqual(REGISTRY.entries);
  });
});
