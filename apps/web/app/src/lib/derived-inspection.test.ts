import { describe, expect, it } from "@rstest/core";

import {
  type DerivedInspectionDescriptor,
  derivedInspectionDescriptorSchema,
  derivedInspectionKey,
} from "@/lib/derived-inspection";

function descriptor(
  overrides: Partial<DerivedInspectionDescriptor> = {},
): DerivedInspectionDescriptor {
  return {
    schema_version: 1,
    source: {
      coordinate: "dataset:molcrafts/revmd17@v4",
      role: "aspirin",
      digest: "md5:0123456789abcdef",
      size: 67_000_000,
    },
    converter: {
      name: "molhub-molrec-indexer",
      version: "1.2.0",
      commit: "98eb42525975a2ada46c619d163679b62cc94faf",
    },
    molrec_schema_version: "3",
    generated_at: "2026-08-09T12:00:00Z",
    record: {
      format: "molrec-zarr-v3",
      url: "https://data.molhub.dev/derived/abc/",
      frames: 100_000,
    },
    properties: [
      { name: "energy", target: "structure", unit: "kcal/mol" },
      { name: "forces", target: "atom", unit: "kcal/(mol angstrom)" },
    ],
    ...overrides,
  };
}

describe("derived inspection descriptors", () => {
  it("requires source and converter provenance", () => {
    expect(derivedInspectionDescriptorSchema.parse(descriptor()).source.digest).toContain("md5:");
    expect(() =>
      derivedInspectionDescriptorSchema.parse(
        descriptor({ converter: { name: "indexer", version: "latest", commit: "abcdef0" } }),
      ),
    ).toThrow(/immutable/);
  });

  it("regenerates the same key from the same immutable inputs", async () => {
    const first = descriptor();
    const regenerated = descriptor({
      generated_at: "2026-08-10T12:00:00Z",
      record: {
        format: "molrec-zarr-v3",
        url: "https://data.molhub.dev/derived/rebuilt/",
        frames: 100_000,
      },
    });

    await expect(derivedInspectionKey(first)).resolves.toBe(
      await derivedInspectionKey(regenerated),
    );
  });

  it("changes the key when source bytes or converter version changes", async () => {
    const first = await derivedInspectionKey(descriptor());
    const changedSource = await derivedInspectionKey(
      descriptor({
        source: {
          coordinate: "dataset:molcrafts/revmd17@v4",
          role: "aspirin",
          digest: "md5:fedcba9876543210",
          size: 67_000_000,
        },
      }),
    );
    expect(changedSource).not.toBe(first);
  });
});
