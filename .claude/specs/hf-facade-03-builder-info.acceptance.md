---
slug: hf-facade-03-builder-info
criteria:
  - id: ac-001
    summary: Shorthand names resolve to a pinned coordinate with a recorded revision
    type: code
    pass_when: |
      DatasetName("themol/mbis").resolve(registry) returns the coordinate
      dataset:themol/mbis@1 against the bundled registry, an explicit revision
      overrides it, and an artifact whose versions do not order unambiguously
      raises an error naming the available revisions.
    status: pending
  - id: ac-002
    summary: DatasetInfo describes content and never a shard role
    type: code
    pass_when: |
      DatasetInfo exposes description, citation, license, features (name, level,
      units), splits (name, num_examples, provenance), record_type and
      download_size, and tests/test_loader/test_info.py asserts the substring
      "shard-" appears in no field of a rendered DatasetInfo.
    status: pending
  - id: ac-003
    summary: split is an argument and a required one
    type: code
    pass_when: |
      molhub.load_dataset accepts split as a required keyword argument and returns
      an object satisfying molhub.dataset.protocol.Dataset; calling it without
      split raises TypeError, and no DatasetDict-like container exists.
    status: pending
  - id: ac-004
    summary: A map-style split view reports its length without fetching bytes
    type: runtime
    pass_when: |
      tests/test_loader/test_mapstyle.py::TestSplitDataset asserts len(ds) equals
      the injected split table's train count while the injected fake ArtifactHub
      records zero fetch calls.
    status: pending
  - id: ac-005
    summary: Shard indexing is lazy, memoized and loud on a key-space mismatch
    type: runtime
    pass_when: |
      A ShardIndex writes its index once under the DerivedLayout root and reuses it
      on reconstruction without reopening the shard, and a group key absent from
      the split table raises an error naming both key spaces rather than defaulting
      a split.
    status: pending
  - id: ac-006
    summary: SplitTable is internal
    type: code
    pass_when: |
      molhub.conveyor.__all__ does not contain "SplitTable", src/molhub/conveyor/
      splits.py defines _SplitTable, and no module outside src/molhub/loader/ and
      src/molhub/conveyor/ imports it.
    status: pending
  - id: ac-007
    summary: The loader layer is one-way
    type: runtime
    pass_when: |
      tests/test_loader/test_layering.py passes, asserting no file under
      src/molhub/dataset/ or src/molhub/conveyor/ references molhub.loader.
    status: pending
  - id: ac-008
    summary: Builder regression reproduces the pinned info and first record offline
    type: runtime
    pass_when: |
      `python regressions/hf-facade-03-builder-info.py` exits 0 with no network,
      reproducing the hard-coded resolved coordinate, per-split counts and the
      first record's meta values embedded as literals in the script.
    status: pending
---

# Acceptance criteria

ac-002 is complaint (1) made mechanical: content-first discovery with a literal
no-"shard-" assertion. ac-003 is complaint (3): split is a required keyword,
PyTorch/HF idiom, no dict-of-splits container. ac-004/ac-005 charge the
map-style costs honestly (length is free, rows fetch shards, indexes memoize,
key-space mismatches refuse loudly). ac-007 keeps the façade a one-way layer on
top of the primitives, per the scoped operator override.
