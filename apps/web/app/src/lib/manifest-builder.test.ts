import { describe, expect, it } from "@rstest/core";
import { load } from "js-yaml";

import {
  DEFAULT_MANIFEST_DRAFT,
  buildManifestYaml,
  manifestCoordinate,
  validateManifestDraft,
} from "@/lib/manifest-builder";

const DEFAULT_ARTIFACT = DEFAULT_MANIFEST_DRAFT.artifacts[0];
if (!DEFAULT_ARTIFACT) throw new Error("The default manifest needs one artifact.");

describe("manifest builder", () => {
  it("emits valid YAML with a stable coordinate", () => {
    const yaml = buildManifestYaml(DEFAULT_MANIFEST_DRAFT);
    const manifest = load(yaml) as Record<string, unknown>;

    expect(manifest.schema_version).toBe(1);
    expect(manifest.kind).toBe("dataset");
    expect(manifestCoordinate(DEFAULT_MANIFEST_DRAFT)).toBe(
      "dataset:your-lab/molecular-benchmark@v1",
    );
    expect(validateManifestDraft(DEFAULT_MANIFEST_DRAFT)).toEqual([]);
  });

  it("rejects moving or incomplete source addresses", () => {
    const errors = validateManifestDraft({
      ...DEFAULT_MANIFEST_DRAFT,
      namespace: "Your Lab",
      artifacts: [
        {
          ...DEFAULT_ARTIFACT,
          locators: ["zenodo record 42"],
          size: "12.5",
        },
      ],
    });

    expect(errors).toHaveLength(3);
  });

  it("builds every artifact and every locator", () => {
    const yaml = buildManifestYaml({
      ...DEFAULT_MANIFEST_DRAFT,
      artifacts: [
        DEFAULT_ARTIFACT,
        {
          ...DEFAULT_ARTIFACT,
          id: "artifact-2",
          role: "readme",
          filename: "README.txt",
          format: "text",
          mediaType: "text/plain",
          locators: ["zenodo://1/README.txt", "https://example.test/README.txt"],
        },
      ],
    });
    const manifest = load(yaml) as { artifacts: Array<{ role: string; locators: string[] }> };
    expect(manifest.artifacts).toHaveLength(2);
    expect(manifest.artifacts[1]).toMatchObject({
      role: "readme",
      locators: ["zenodo://1/README.txt", "https://example.test/README.txt"],
    });
  });
});
