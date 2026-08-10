import { describe, expect, it } from "@rstest/core";

import { DIRECT_INSPECTION_LIMIT, inspectability } from "@/lib/inspectability";
import type { RegistryArtifact } from "@/types/registry";

function artifact(overrides: Partial<RegistryArtifact> = {}): RegistryArtifact {
  return {
    role: "train",
    filename: "opaque.data",
    format: "extxyz",
    media_type: "chemical/x-xyz",
    locators: ["https://example.test/data"],
    digest: null,
    size: 1_024,
    ...overrides,
  };
}

describe("inspectability", () => {
  it("maps declared ExtXYZ semantics to MolVis without reading the filename", () => {
    expect(inspectability(artifact({ filename: "not-an-xyz.bin" }))).toMatchObject({
      state: "direct",
      format: "xyz",
    });
  });

  it("never infers support from a filename", () => {
    expect(
      inspectability(artifact({ filename: "looks-valid.xyz", format: null, media_type: null })),
    ).toEqual({
      state: "unsupported",
      reason: "The manifest does not declare a format or media type.",
    });
  });

  it("routes large and archive records to the derived path", () => {
    expect(inspectability(artifact({ size: DIRECT_INSPECTION_LIMIT + 1 })).state).toBe("derived");
    expect(inspectability(artifact({ format: "npz", media_type: null })).state).toBe("derived");
  });

  it("requires an HTTP source for browser inspection", () => {
    expect(inspectability(artifact({ locators: ["zenodo://123/file"] }))).toMatchObject({
      state: "unsupported",
    });
  });
});
