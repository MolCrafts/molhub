# Manifests

A manifest describes one coordinate and its files. Each artifact has a role, filename, ordered
locators, at least a published digest or byte size, and optional declared `format` and `media_type`.
Inspector support is decided from those byte semantics, never by guessing from the filename.

The digest is optional. When an upstream platform publishes one, copy its algorithm and value
verbatim. MolHub does not download a file merely to invent a digest for the registry.

Use the [manifest schema](../reference/manifest-schema.md) and the website manifest builder. Approved
manifests live in `molhub-registry`; generated registry snapshots do not.
