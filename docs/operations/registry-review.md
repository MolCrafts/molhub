# Registry review

Review coordinates, version pinning, DOI, license, every role, format/media type, locator order, and the
platform-published size/digest. Source reachability is a manual reviewer check; the submission Worker is
not an arbitrary upstream proxy.

Approval creates a branch and pull request in `molhub-registry`. Rejection requires a concrete note.
Merging a registry pull request runs deterministic validation/build, uploads the snapshot with its source
commit, and dispatches a MolHub Web rebuild.

The scheduled health job only reads manifests and upstream metadata. It retries bounded transient
failures and reports them; it never edits or merges an artifact record.
