import { describe, expect, it } from "@rstest/core";

import { normalizeExtxyzForMolvis, readBoundedText } from "./extxyz-compat";

describe("normalizeExtxyzForMolvis", () => {
  it("omits unsupported JSON metadata without changing structural data", () => {
    const source = [
      "2",
      'Lattice="1 0 0 0 1 0 0 0 1" Properties=species:S:1:pos:R:3 energy=-1.5 dihedrals="_JSON [10.0, 20.0, 30.0]" pbc="F F F"',
      "H 0 0 0",
      "H 0 0 1",
      "1",
      'Properties=species:S:1:pos:R:3 energy=-1.0 tags="_JSON [true, false, true]"',
      "He 0 0 0",
      "",
    ].join("\n");

    const result = normalizeExtxyzForMolvis(source);

    expect(result.omittedFields).toEqual(["dihedrals", "tags"]);
    expect(result.omittedOccurrences).toBe(2);
    expect(result.content).not.toContain("_JSON");
    expect(result.content).toContain('energy=-1.5 pbc="F F F"');
    expect(result.content).toContain("H 0 0 1\n1\n");
    expect([...result.numericLabels]).toEqual([["energy", Float64Array.from([-1.5, -1])]]);
  });

  it("rejects truncated frames instead of silently rewriting them", () => {
    expect(() => normalizeExtxyzForMolvis("2\ncomment\nH 0 0 0\n")).toThrow(/truncated/);
  });
});

describe("readBoundedText", () => {
  it("rejects a declared oversized response before reading it", async () => {
    const response = new Response("not read", { headers: { "content-length": "100" } });
    await expect(readBoundedText(response, 10)).rejects.toThrow(/browser limit/);
  });

  it("reads a response within the byte limit", async () => {
    await expect(readBoundedText(new Response("molecule"), 16)).resolves.toBe("molecule");
  });
});
