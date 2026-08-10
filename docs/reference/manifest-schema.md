# Manifest schema

The canonical schema is
[`spec/manifest.schema.yaml`](https://github.com/MolCrafts/molhub/blob/main/spec/manifest.schema.yaml).
It validates the authored document; the generated registry envelope has a separate schema.

Required identity fields are schema version, kind, namespace, name, version, and title. Each artifact
requires role, filename, at least one locator, and at least one of published digest or size. License and
version DOI are enforced by the shared semantic validator. `format` and `media_type` declare byte
semantics for consumers such as Inspector.

Run `npm run contract:check` to prove checked-in Python and TypeScript runtime copies match the source.
