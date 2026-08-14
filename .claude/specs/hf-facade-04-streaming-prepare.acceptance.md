---
slug: hf-facade-04-streaming-prepare
criteria:
  - id: ac-001
    summary: streaming=True returns an iterable dataset with HF-shaped take
    type: code
    pass_when: |
      molhub.load_dataset(name, split=..., streaming=True) returns an object
      satisfying molhub.dataset.protocol.IterableDataset and exposing take(n),
      yielding molpy Frame or Trajectory records.
    status: pending
  - id: ac-002
    summary: The streaming walk stays inside its byte budget
    type: runtime
    pass_when: |
      tests/test_loader/test_streaming.py asserts that after every yielded record
      the injected TierStore's resident_bytes is at most its budget_bytes, and that
      each shard is released before the next is admitted.
    status: pending
  - id: ac-003
    summary: Conveyor vocabulary never reaches the user path
    type: code
    pass_when: |
      No value returned by load_dataset or prepare, and no message of an exception
      they raise, contains a BlockId, a BlockState, a ledger record or the literal
      "shard-"; tests/test_loader/test_streaming.py asserts this on both the happy
      path and the missing-split-key failure.
    status: pending
  - id: ac-004
    summary: prepare materializes sealed blocks through the existing PrepareJob
    type: runtime
    pass_when: |
      molhub.prepare(name, split=..., output_dir=...) with an injected fake writer
      returns a molhub.conveyor.PreparedBlocks whose roots exist under output_dir,
      one per split-and-size fan-out, with unit_count and frame_count matching the
      literals in tests/test_loader/test_materialize.py.
    status: pending
  - id: ac-005
    summary: prepare fails closed without molnex rather than degrading
    type: runtime
    pass_when: |
      With the default writer factory and molix absent, prepare raises ImportError
      naming the prepare extra and the MOLNEX_SRC escape hatch, and writes no
      partial block directory.
    status: pending
  - id: ac-006
    summary: molhub info is content-first with roles behind a flag
    type: runtime
    pass_when: |
      `molhub info themol/mbis` prints description, features, splits with counts and
      an example record shape, and prints no artifact role; `molhub info themol/mbis
      --files` additionally prints roles, filenames, sizes, digests and locators.
    status: pending
  - id: ac-007
    summary: Documented examples execute
    type: docs
    pass_when: |
      docs/reference/python.md and docs/guides/finding-and-fetching.md document
      load_dataset_builder, load_dataset with split and streaming, and prepare; every
      Python fence carries an explicit test directive and
      `uv run pytest tests/test_docs_examples.py -v` passes.
    status: pending
  - id: ac-008
    summary: Streaming and prepare regression reproduces its pinned records offline
    type: runtime
    pass_when: |
      `python regressions/hf-facade-04-streaming-prepare.py` exits 0 with no network
      and no molnex import, reproducing the hard-coded streamed record ids, record
      count under take(3) and sealed-block unit and frame counts embedded as
      literals in the script.
    status: pending
---

# Acceptance criteria

ac-002 and ac-003 are complaint (4) made mechanical: bounded disk with the
conveyor invisible — no BlockId/BlockState/ledger/"shard-" in any user-facing
value or message. ac-004/ac-005 pin `prepare` as materialization over the
existing PrepareJob, failing closed without molnex. ac-006 finishes complaint
(1) on the CLI: content first, roles behind `--files`.
