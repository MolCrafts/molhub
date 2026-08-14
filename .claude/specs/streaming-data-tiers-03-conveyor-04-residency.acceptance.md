---
slug: streaming-data-tiers-03-conveyor-04-residency
criteria:
  - id: ac-001
    summary: TierStore owns exactly one subdirectory and defers the root rule
    type: code
    pass_when: |
      Every path returned by TierStore.path_for / admit is inside
      <root>/<subdir>/, TierStore resolves a default root through
      molhub.sources.BlobStore().root (no second reading of $MOLHUB_HOME in
      src/molhub/conveyor/), and tests/test_conveyor/test_tier.py::TestTierStore
      passes with a fake BlockLedger and no real ledger import.
    status: pending
  - id: ac-002
    summary: T1 and T2 byte budgets are enforced independently
    type: code
    pass_when: |
      With a raw store at budget 2_000_000 and a blocks store at 3_000_000 over
      the same root, filling either to its budget leaves the other's
      resident_bytes and entry set unchanged, and an over-budget admit raises
      TierOverBudget naming only the tier it was called on.
    status: pending
  - id: ac-003
    summary: Eviction never touches leased, resident-flagged or non-CONSUMED blocks
    type: code
    pass_when: |
      evict_until skips every entry that is leased per BlockLedger, resident-
      flagged, or not BlockState.CONSUMED; when the remaining candidates cannot
      meet the target it raises TierOverBudget with resident_bytes and the entry
      set byte-for-byte unchanged (feasibility checked before any unlink), and
      release() on a leased or flagged block raises BlockUnevictable.
    status: pending
  - id: ac-004
    summary: Eviction order follows the visit plan in the pinned sequence
    type: code
    pass_when: |
      For a fixture of five resident CONSUMED blocks and VisitOrder(order,
      cursor), evict_until returns candidates ordered: absent-from-plan first,
      then behind-cursor by ascending position, then ahead-of-cursor by
      descending position, ties by ascending BlockId — asserted as an exact
      tuple in tests/test_conveyor/test_tier.py, and VisitOrder is never
      accepted by admit (no tier entry represents the plan).
    status: pending
  - id: ac-005
    summary: TierStore writes exactly one ledger transition — REMOTE on deletion
    type: code
    pass_when: |
      A fake BlockLedger records exactly one REMOTE record per released or
      evicted block with its declared nbytes, and zero records for path_for,
      admit, flag_resident or a failed evict_until.
    status: pending
  - id: ac-006
    summary: Derived-artifact layout generalized; splits script output unchanged
    type: code
    pass_when: |
      scripts/build_class1_splits.py contains no inline "derived" path
      expression and no direct metadata.json write (grep for
      '"derived"' and 'metadata.json' finds only DerivedLayout calls), and
      running it on a fixture input produces the same four split files and a
      metadata.json byte-identical to the pre-change output for the same seed
      and inputs.
    status: pending
  - id: ac-007
    summary: ByteBoundedQueue refuses at capacity and admits after release
    type: code
    pass_when: |
      With capacity 2_000_000 and two 1_000_000 reservations held,
      reserve(..., timeout=0) raises QueueTimeout; take() leaves held_bytes
      unchanged; after release(item) the same reserve succeeds; a reservation
      larger than capacity_bytes raises QueueOversized without blocking.
    status: pending
  - id: ac-008
    summary: A blocked reserve wakes on release within a bounded wait
    type: runtime
    pass_when: |
      tests/test_conveyor/test_backpressure.py starts a waiter thread that sets
      a threading.Event immediately before reserve(..., timeout=5); after the
      main thread releases, thread.join(timeout=5) completes and the reservation
      is held; the test file contains no time.sleep call.
    status: pending
  - id: ac-009
    summary: PrepareWorkers uses spawn by default and per-pid worker handles
    type: code
    pass_when: |
      PrepareWorkers()'s default multiprocessing context is 'spawn', an injected
      context is used verbatim, and a fake runner whose __getstate__ drops its
      handle and pid runs submitted jobs to completion through submit/collect,
      re-opening its handle when os.getpid() differs.
    status: pending
  - id: ac-010
    summary: CoverageReport replays a ledger to exact pinned counts
    type: code
    pass_when: |
      For the fixture record stream in tests/test_conveyor/test_coverage.py,
      bytes_downloaded counts a retried fetch twice, bytes_prepared sums READY
      records, bytes_evicted sums only REMOTE-after-READY records for derived
      blocks (BlockId.split is not None), bytes_raw_released sums
      REMOTE-after-READY for raw blocks (split is None), and blocks_seen /
      blocks_consumed / units_seen / fraction(total) / the cumulative timeline
      all equal their pinned literals.
    status: pending
  - id: ac-011
    summary: Sampler-handoff metadata carries the named fields, digests verbatim
    type: code
    pass_when: |
      ReadyBlocks.metadata() over a fixture sealed manifest returns
      BlockMetadata with block_id, root, split, units, frames (= rows["frame"]),
      task_names, column_digests and block_digest equal to the literals in the
      fixture file (no digest recomputed anywhere in src/molhub/conveyor/), and
      raises BlockNotSealed for sealed:false and UnsupportedBlockFormat for
      schema_version 2.
    status: pending
  - id: ac-012
    summary: No torch or molix import in the conveyor package
    type: code
    pass_when: |
      tests/test_conveyor/test_layering.py parses every file under
      src/molhub/conveyor/ with ast and asserts no module-level import of torch,
      molix or molrs anywhere in the package, and no import of them at any depth
      in tier.py, backpressure.py and coverage.py.
    status: pending
  - id: ac-013
    summary: cache status and cache coverage print the golden lines
    type: code
    pass_when: |
      In tests/test_cli.py, `cache status --home <tmp>` prints one line per tier
      carrying the tier name, entry count, resident bytes and budget bytes,
      exits 1 when a tier is over budget and prints "No conveyor tiers under
      <root>." on an empty root; `cache coverage --home <tmp>` prints blocks
      seen, consumed-of-total with percentage, units and the three byte totals,
      and exits 1 with a message when no roster is present.
    status: pending
  - id: ac-014
    summary: Regression reproduces the eviction, queue, coverage and metadata goldens
    type: runtime
    evaluator_hint: "python regressions/streaming-data-tiers-03-conveyor-04-residency.py"
    pass_when: |
      regressions/streaming-data-tiers-03-conveyor-04-residency.py exits 0 using
      only public molhub APIs, asserting the hard-coded goldens: eviction
      sequences ("b00",) then ("b02",), the infeasible evict_until raising
      TierOverBudget with residency unchanged at 3_000_000 B (three resident
      entries b01/b02/b03) and the leased and flagged blocks still present, peak
      blocks-tier residency 3_000_000 B, raw tier unaffected at 2_000_000 B,
      queue held_bytes trace (1_000_000, 2_000_000, 2_000_000, 2_000_000,
      1_000_000, 2_000_000), coverage bytes_downloaded 5_000_000 /
      bytes_prepared 5_000_000 / bytes_evicted 2_000_000 (derived) /
      bytes_raw_released 1_000_000 (raw, split=None) /
      blocks_consumed ("b00","b01","b02") / units_seen 12 /
      fraction(8) 0.375 / timeline ((1,3),(2,5),(3,8)), and b03 metadata
      split "train", units 2, frames 8, task_names ("equilibrium","torsion").
      No network and no third-party oracle runs.
    status: pending
  - id: ac-015
    summary: Docstrings argue the boundaries the modules depend on
    type: docs
    pass_when: |
      Each of tier.py, backpressure.py and coverage.py carries a Google-style
      module docstring stating, respectively: why the budget is enforced on
      declared bytes and why evict_until plans before deleting; why processes
      rather than threads and why spawn is the default; and why molhub copies
      the producer's digests instead of computing them (citing
      .claude/notes/notes.md) plus the metadata.json vs manifest.json boundary.
      Every public method has Args/Returns/Raises with byte units named.
    status: pending
  - id: ac-016
    summary: Full check and test suite are green
    type: runtime
    pass_when: |
      `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`
      and `uv run pytest -v` all exit 0 on the branch containing this spec's
      changes.
    status: pending
---

# Acceptance criteria

Sixteen criteria: ac-001..ac-006 bind the residency tier and the generalization,
ac-007..ac-009 the backpressure and worker pool, ac-010..ac-011 the reporting and
sampler-handoff surface, ac-012 the torch-free guarantee, ac-013 the CLI,
ac-014 the regression, ac-015 the documented boundaries, ac-016 the delivery gate.

`ac-003`, `ac-004` and `ac-005` together are the enforceable form of invariants
I4 and I9: bounded residency, never at the cost of a live lease, with the
deletion recorded so I10 can be answered after a restart. `ac-011` and `ac-012`
together are what keeps molhub a data-plane repo — the molnex-side successor
(`streaming-data-tiers-04-scheduler-integration`) gets everything it needs to
build a batch plan from JSON alone.
