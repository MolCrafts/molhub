# Contract development

Before 1.0, the project maintains only the current contract. There are no schema-version gates,
old-client compatibility branches, or historical upgrade paths.

`spec/manifest.schema.yaml` and `spec/registry.schema.yaml` are the hand-authored contract. Run
`npm run contract:sync`, review generated Python/TypeScript validators, and update cross-language
vectors and current registry records together. Never hand-edit generated validators.
