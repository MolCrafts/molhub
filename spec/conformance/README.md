# MolHub conformance vectors

The YAML files in `vectors/` are the language-neutral behavioral contract for
MolHub clients. They contain data only. Python and TypeScript test runners read
the same files; neither runner owns or rewrites them.

Stable error codes used by the vectors:

- `invalid_coordinate`
- `invalid_digest`
- `invalid_manifest`
- `duplicate_role`
- `all_locators_failed`

To change shared behavior, edit or add a vector first, then update every client
until both runners pass. Human-readable exception text is deliberately not part
of this contract.

The shared cases cover coordinate normalization, digest parsing and hashing,
the complete cache-relative path, manifest validation, registry resolution and
search ordering, and ordered source fallback. Driver discovery and browser/Node
module boundaries remain language-specific and are covered by their own tests.
