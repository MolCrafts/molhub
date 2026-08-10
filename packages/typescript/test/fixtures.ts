import type { MolhubRegistry } from "../src/types.js";

export const REGISTRY: MolhubRegistry = {
  schema_version: 1,
  entries: [
    {
      coordinate: "dataset:molcrafts/example@v1",
      kind: "dataset",
      namespace: "molcrafts",
      name: "example",
      version: "v1",
      title: "Example molecular dataset",
      description: "Energy and forces",
      license: "CC0-1.0",
      doi: "10.0000/example",
      targets: { graph_level: ["energy"], atom_level: ["forces"] },
      artifacts: [
        {
          role: "main",
          filename: "example.xyz",
          format: "extxyz",
          media_type: "chemical/x-xyz",
          locators: ["https://example.test/example.xyz"],
          digest: null,
          size: 4,
        },
      ],
    },
  ],
};
