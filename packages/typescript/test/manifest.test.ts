import { describe, expect, it } from "@rstest/core";

import { ManifestValidator, serializeManifest, toRegistryEntry } from "../src/index.js";

const DOCUMENT = {
  schema_version: 1,
  kind: "dataset",
  namespace: "lab",
  name: "sample",
  version: "v1",
  title: "Sample",
  doi: "10.0000/sample",
  artifacts: [
    {
      role: "main",
      filename: "sample.xyz",
      format: "extxyz",
      media_type: "chemical/x-xyz",
      size: 4,
      locators: ["https://example.test/sample.xyz"],
    },
  ],
} as const;

describe("ManifestValidator", () => {
  it("validates and projects the canonical contract", () => {
    const result = new ManifestValidator().validate(DOCUMENT);
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("Expected a valid manifest.");
    expect(toRegistryEntry(result.value).coordinate).toBe("dataset:lab/sample@v1");
    expect(toRegistryEntry(result.value).artifacts[0]).toMatchObject({
      format: "extxyz",
      media_type: "chemical/x-xyz",
    });
    expect(serializeManifest(result.value)).toContain("schema_version: 1");
  });

  it("rejects display labels where a stable format identifier is required", () => {
    const result = new ManifestValidator().validate({
      ...DOCUMENT,
      artifacts: [{ ...DOCUMENT.artifacts[0], format: "Extended XYZ" }],
    });
    expect(result.ok).toBe(false);
  });

  it("rejects a moving Hugging Face revision", () => {
    const result = new ManifestValidator().validate({
      ...DOCUMENT,
      artifacts: [{ ...DOCUMENT.artifacts[0], locators: ["hf://lab/data@main/sample.xyz"] }],
    });
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("Expected an invalid manifest.");
    expect(result.issues.some((issue) => issue.code === "unpinned_locator")).toBe(true);
  });

  it("rejects a digest with the right algorithm but wrong length", () => {
    const result = new ManifestValidator().validate({
      ...DOCUMENT,
      artifacts: [{ ...DOCUMENT.artifacts[0], digest: "md5:0" }],
    });
    expect(result.ok).toBe(false);
  });
});
