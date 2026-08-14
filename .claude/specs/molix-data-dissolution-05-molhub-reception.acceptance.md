---
slug: molix-data-dissolution-05-molhub-reception
criteria:
  - id: ac-001
    summary: tombstone record names the deleted sources and their verdicts
    type: docs
    pass_when: |
      .claude/notes/molnex-etl-tombstone.md exists and states the molnex
      deletion commit SHA, the full deleted file list (molix/data/**,
      molix/datasets/**), and one verdict per module: re-expressed here /
      owned by python-native-dataset-protocol-0x / superseded by
      streaming-data-tiers-03 / dropped.
    status: pending
  - id: ac-002
    summary: no second dataset protocol is introduced
    type: code
    pass_when: |
      src/molhub/dataset/ defines exactly one dataset declaration surface —
      the @dataset + load() protocol — and contains no DataSource,
      PipelineSpec, Node, DAGCache or molnex Task/SampleTask/DatasetTask
      definition of its own beyond the neighbour delegate.
    status: pending
  - id: ac-003
    summary: WaterLES adapter reproduces the molnex target schema and units
    type: scientific
    pass_when: |
      tests/test_dataset/test_water_les.py passes, asserting the graph-level /
      atom-level target split and the unit conversion against values hard-coded
      from the deleted molnex tests, with no live external download.
    status: pending
  - id: ac-004
    summary: MolRec adapter reproduces per-instance schema and source identity
    type: code
    pass_when: |
      tests/test_dataset/test_molrec.py passes, covering record -> sample
      mapping, per-instance target-schema derivation, and a stable source_id
      whose value is pinned as a literal.
    status: pending
  - id: ac-005
    summary: AtomicDress baseline fit is numerically unchanged
    type: scientific
    pass_when: |
      tests/test_dataset/test_transforms.py asserts the per-element baseline
      vector from a hand-built 3-element fixture against hard-coded expected
      values (tolerance 1e-10) and round-trips it through state_dict /
      load_state_dict without drift.
    status: pending
  - id: ac-006
    summary: neighbour handling delegates, never duplicates
    type: code
    pass_when: |
      src/molhub/dataset/neighbor.py contains no pair enumeration, no NaN-strip,
      no symmetry expansion and no sign negation — it calls
      molix.batch.NeighborList — and tests/test_dataset/test_neighbor.py shows
      its output is identical to that class's on a 3-atom chain and that the
      node is treated as cacheable.
    status: pending
  - id: ac-007
    summary: cross-repo dependency direction respected
    type: code
    pass_when: |
      molhub imports molix (molhub -> molnex) and no molnex source file imports
      molhub; molnex's tests/test_repository_boundaries.py still passes against
      the molnex checkout used for this work.
    status: pending
  - id: ac-008
    summary: stale molnex paths in molhub notes repaired
    type: docs
    pass_when: |
      .claude/notes/streaming-data-tiers.md cites
      molnex:src/molix/batch/sampler.py and molnex:src/molix/store/cache.py, and
      `grep -rn "molix/data/\|molix\.data\b" .claude/` returns no matches except
      inside the tombstone note's historical file list.
    status: pending
  - id: ac-009
    summary: reception regression reproduces hard-coded goldens offline
    type: runtime
    pass_when: |
      `python regressions/molix-data-dissolution-05-molhub-reception.py` exits 0
      with no network access, reproducing its literal goldens for both adapters,
      the AtomicDress baseline, and the neighbour delegate's
      edge_index / edge_diff / edge_dist. Any externally derived value is
      embedded as a literal with tool, version, command and date in a comment.
    status: pending
  - id: ac-010
    summary: molhub suite and lint gate green
    type: code
    pass_when: |
      molhub's configured test command passes and its configured lint/format
      check is clean with the new modules included.
    status: pending
---

# Acceptance criteria

ac-002 is the criterion that encodes the tombstone verdict: if a straight port
had been chosen, molhub would carry two dataset protocols and this criterion
would fail. ac-006 is the one that keeps a physics contract from being forked
across repositories.
