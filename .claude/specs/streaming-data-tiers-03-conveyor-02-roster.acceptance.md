---
slug: streaming-data-tiers-03-conveyor-02-roster
criteria:
  - id: ac-001
    summary: roster carries manifest artifact fields without re-deriving them
    type: code
    pass_when: |
      For every artifact in the fixture manifest, the projected RemoteBlock
      satisfies filename == Artifact.filename, size == Artifact.size,
      digest is Artifact.digest and locators is Artifact.locators (object
      identity, not just equality), and RemoteBlock declares no unit, target,
      sampling_unit or reference_method attribute. Pinned by
      tests/test_conveyor/test_roster.py::TestRemoteBlock.
    status: pending
  - id: ac-002
    summary: only shard roles become blocks; hot roles are reported, not dropped
    type: code
    pass_when: |
      BlockRoster over src/molhub/registry_data/dataset/themol/mbis/1.yaml
      yields exactly 8 blocks in manifest role order, hot_roles == ("index",),
      and total_bytes() == 29588617144; a manifest with no shard-<digits> role
      raises NoShardArtifacts rather than returning an empty roster.
    status: pending
  - id: ac-003
    summary: blocks the invariants cannot cover are refused at construction
    type: code
    pass_when: |
      An artifact with size=None raises UnsizedBlock (I4 cannot budget it) and
      an artifact with digest=None raises UnverifiableBlock (I6 cannot verify
      it), both at BlockRoster construction; RemoteBlock.size and
      RemoteBlock.digest are non-optional types.
    status: pending
  - id: ac-004
    summary: BlockId is the hub addressing plus task and an honest split
    type: code
    pass_when: |
      For every projected block, id.source == manifest.coordinate.canonical,
      id.task == role.name, id.block_id == the manifest artifact role, and
      id.split is None for published shards; a manifest whose coordinate is
      absent from role.source_coordinates raises RoleSourceMismatch. No module
      under src/molhub/conveyor/ contains a per-shard split assignment derived
      from anything other than a manifest it produced itself.
    status: pending
  - id: ac-005
    summary: split table is provenance-verified against metadata.json
    type: code
    pass_when: |
      SplitTable.from_derived (per-source, uuid-keyed, explicit literal
      filename mapping incl. torsion_scan_splits.csv.gz without _uuid_) and
      SplitTable.from_identity (identity_splits.csv.gz, identity-keyed) both
      verify every .csv.gz they read with Digest.of_file(path).matches(...)
      against that file's entry in metadata.json output_sha256, raise
      SplitProvenanceMismatch naming the file when they disagree, and expose
      coordinate, seed, ratios and generator from metadata.json verbatim; unit facts used by the roster come
      from the injected CollectionRole (roster.role) and are never copied onto
      RemoteBlock.
    status: pending
  - id: ac-006
    summary: lease is taken before the first fetch and always released
    type: code
    pass_when: |
      In tests/test_conveyor/test_transfer.py the fake ledger's call log shows
      lease([block.id], ttl) strictly before the first ArtifactHub.fetch call,
      and release recorded exactly once on the success path and once on the
      PersistentDigestMismatch path (finally, not a happy-path-only call).
    status: pending
  - id: ac-007
    summary: transient mismatch retries within bounds and re-verifies
    type: code
    pass_when: |
      With a hub serving corrupt bytes then good bytes, transfer() returns the
      verified path after exactly two fetch calls, unlinks the corrupt file
      before re-fetching (so Fetcher's cache short-circuit cannot re-serve it),
      appends BlockState.DOWNLOADING exactly once for the whole call, and
      performs at most `retries` attempts in total (retries=3 means 3 attempts;
      retries=0 raises ValueError).
    status: pending
  - id: ac-008
    summary: persistent mismatch fails typed, deletes bytes, then regresses to REMOTE
    type: code
    pass_when: |
      With an always-corrupt hub and retries=3, transfer() raises
      PersistentDigestMismatch carrying all three attempts (index, expected and
      actual value, failure reason size|digest); the local file no longer
      exists; the ledger rows for the block are exactly [DOWNLOADING, REMOTE]
      in that order with the unlink preceding the REMOTE append;
      PersistentDigestMismatch is not a subclass of
      molhub.sources.errors.DigestMismatch.
    status: pending
  - id: ac-009
    summary: nothing in this spec ever writes READY
    type: code
    pass_when: |
      grep for BlockState.READY under src/molhub/conveyor/roster.py,
      splits.py and transfer.py returns no match, and no test in
      tests/test_conveyor/ observes a READY append on any path.
    status: pending
  - id: ac-010
    summary: the transport layer is untouched and the layering edge is one-way
    type: code
    pass_when: |
      `git diff --stat <branch-base>..HEAD -- src/molhub/sources/` produces no
      output, and tests/test_conveyor/test_layering.py passes: no module under
      src/molhub/sources/ or src/molhub/dataset/ imports molhub.conveyor, and
      no module under src/molhub/conveyor/ imports anything outside stdlib and
      molhub.* — in particular no torch, numpy or h5py.
    status: pending
  - id: ac-011
    summary: regression reproduces roster and retry goldens offline
    type: runtime
    pass_when: |
      `uv run python regressions/streaming-data-tiers-03-conveyor-02-roster.py`
      exits 0 with no network and no third-party import, asserting the
      hard-coded literals: 8 blocks / hot_roles ("index",) / total_bytes
      29588617144 / shard-003 size 3549593228 and sha256
      b364c682c2d871951c80db3d0c5daac5aebfe6cc09596e29ed0a64e4d0adc557 from the
      shipped themol/mbis@1 manifest; the transient scenario returning the good
      payload after exactly 2 fetch calls with ledger rows [DOWNLOADING]; and
      the persistent scenario raising PersistentDigestMismatch with 3 attempts,
      the file absent, and ledger rows [DOWNLOADING, REMOTE].
    status: pending
  - id: ac-012
    summary: full local gate green
    type: runtime
    pass_when: |
      `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`
      and `uv run pytest -v` all pass on the branch with the new
      tests/test_conveyor/ suite included and no test marked network.
    status: pending
---

# Acceptance criteria

- **ac-001 … ac-005** bind the roster to being a *projection*: the manifest
  stays the single remote index, the collection role stays the single source of
  task and unit facts, and the split table is trusted only after its own
  producer's sha256 agrees. ac-004 additionally forbids the tempting lie — a
  per-shard split the roster cannot derive without opening bytes.
- **ac-006 … ac-009** bind the transfer to the four-state machine of
  `streaming-data-tiers-01-strategy` I5 / I6. ac-009 is the structural form of
  "a mismatching block never reaches READY": this layer has no way to write it.
  ac-008's ordering clause is what makes the DOWNLOADING → REMOTE regression
  honest — REMOTE means nothing local, so the bytes must go first.
- **ac-010** protects the two boundaries this spec must not cross: `Fetcher`'s
  deliberate no-retry, upstream-changed semantics stay exactly as written, and
  the conveyor stays a leaf above `sources` and `dataset`.
- **ac-011 / ac-012** are the delivery gates, verified by `/mol:impl`.

Not gated here, and deliberately so: the fixed `.part` name in
`src/molhub/sources/blobs.py:69-75` remains a live L1 defect routed to
`/mol:fix`. The lease in ac-006 protects conveyor callers from each other; it
does not protect anyone from a concurrent non-conveyor `Fetcher` call.
