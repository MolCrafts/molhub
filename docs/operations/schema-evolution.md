# Schema evolution

`spec/manifest.schema.yaml` and `spec/registry.schema.yaml` are the hand-authored contract. Run
`npm run contract:sync`, review generated Python/TypeScript validators, and add cross-language vectors
for every proposal.

Schema versions are independent of Python/npm package versions. A release note states contract changes,
registry snapshot revision, cache/layout changes, migrations, and minimum compatible clients. Additive
fields still require old-client tests; incompatible envelope changes bump `schema_version`.

Never hand-edit generated validators. The canonical registry must pass the new validator before a client
release consumes it.
