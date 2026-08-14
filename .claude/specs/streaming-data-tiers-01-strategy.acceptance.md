---
slug: streaming-data-tiers-01-strategy
criteria:
  - id: ac-001
    summary: Three-tier model and hot/cold classification are fully specified
    type: docs
    pass_when: |
      The spec contains a tier table defining T0 REMOTE, T1 LOCAL rolling,
      T2 READY and the cross-cutting hot tier, each with contents, byte budget,
      lifetime and deletion rule; states the peak-footprint arithmetic
      (hot + T1 + T2 approximately 140 GB against the 300 GB local budget);
      classifies validation sets, split manifests, block index, metadata and the
      Hessian core (about 5.8 GB at 1e5 molecules) as resident hot data and
      relaxation/torsion/OMol25 bulk as rolling cold data; and states that a
      training node never holds a full local copy and that no flag may create one.
    status: pending
  - id: ac-002
    summary: Block decomposition and the four-state lifecycle are binding and complete
    type: docs
    pass_when: |
      The spec fixes 1-5 GB independent blocks as the unit of work
      (download one, prepare one, consume one, delete one); states the
      unit-integrity cut rule (a molecule bundle or complete torsion scan never
      straddles two blocks) and split-purity; defines exactly four states
      REMOTE, DOWNLOADING, READY, CONSUMED with READY as the conjunction of
      downloaded, unpacked, preprocessed and digest-verified; and specifies the
      tiny local ledger, per-stage idempotency, crash recovery from
      files-present AND ledger, sha256 verification with bounded retry at the
      remote-to-local boundary, and the resident flag exempting a block from
      deletion. No fifth state appears anywhere in the document.
    status: pending
  - id: ac-003
    summary: Invariant register I1-I10 is enumerated with rationale and owner
    type: docs
    pass_when: |
      The spec contains a numbered invariant register covering, at minimum,
      block independence, unit integrity plus split purity, no-double-copy,
      byte-bounded residency, four-states-only with idempotent recovery,
      digest-at-boundary, preserved sampling discipline, plan authority
      (prefetch may be reordered, consumed order may not; no within-block-only
      shuffling; a missing block stalls and is reported rather than skipped or
      substituted), plan-scoped refcounted deletion, and coverage accounting;
      each entry names the successor spec responsible for enforcing it.
    status: pending
  - id: ac-004
    summary: Throughput condition recorded in byte-rate form with honest worked numbers
    type: docs
    pass_when: |
      Domain basis records the measured anchors (20 MB/s sustained HF download,
      6.5 TB THEMol raw, 4-20 GB published shards, 300 GB local budget, 1-5 GB
      derived block target, GH200 2000 conf/s medium h512 and 3700 conf/s small
      both explicitly marked indicative and superseded-dataset) and the per-frame
      byte accounting (40 atoms: about 500 B E-only, about 1.0 kB E+F, 57.6 kB
      full Hessian per molecule); states the condition in rate form
      r_train * B_frame <= B_net and r_train <= W / c_prep, notes that block size
      cancels so feasibility is size-independent while block size sets latency and
      peak disk; tabulates at least the 1-GPU medium (about 20x margin), 1-GPU
      small (about 10.8x), multi-GPU binding case, and the raw-shard
      unused-payload violation; and states explicitly that the prepare stage
      binds before the download stage as r_train grows, with the core-count
      arithmetic shown. Every number is re-derivable from the stated inputs.
    status: pending
  - id: ac-005
    summary: Plan-globally-consume-rolling resolution cites the verified loader seams
    type: docs
    pass_when: |
      The spec explains that TaskMixtureBatchSampler builds its eager
      deterministic plan from metadata only, that plan-level metadata is hot-tier
      resident, and therefore that the global plan is computed up front, induces
      the block visit order, and is realized by the conveyor; asserts that the
      sampling policy needs no redesign and that the block-aware iterator enters
      through the existing batch_sampler_source seam owned by
      -04-scheduler-integration; and cites molnex:src/molix/batch/sampler.py:267,
      molnex:src/molix/batch/sampler.py:811, molnex:src/molix/batch/datamodule.py:148 and
      :264-266, each resolving to the cited symbol in the current tree. The
      per-frame Python-table scaling wall is recorded as a named owned risk with
      molnex:src/molix/batch/sampler.py:89 evidence, quantified memory estimates, and the
      two candidate resolutions assigned to -04.
    status: pending
  - id: ac-006
    summary: Coverage semantics and streaming levels L1-L3 with publishing rule
    type: docs
    pass_when: |
      The spec defines "using all data" as coverage over time (blocks visited in
      plan order across passes; partial per-pass coverage legitimate), quantifies
      it (10 percent round and full-coverage network wall times, plus the 90 h
      full raw pass that motivates it), and states the two guardrails: recorded
      per-pass block coverage and plan-level rather than within-block-only
      shuffling. It also tabulates streaming levels L1 must-fully-unpack, L2
      stream-decompressable, L3 natively chunked random-access, and binds the
      publishing recommendation to many medium (1-5 GB) unit-aligned digest-pinned
      independent L3 shards, tying that choice to the prepare-stage bound.
    status: pending
  - id: ac-007
    summary: Successor chain contracts are named with owned surface and exit criteria
    type: docs
    pass_when: |
      The spec contains a handoff table with one row per successor
      (-02-block-format, -03-conveyor, -04-scheduler-integration) giving owned
      surface, inherited invariant ids, and an exit criterion. The -02 row lists
      the block-format requirements only (streaming-appendable, unit-aligned,
      mmap zero-copy, few files per block, per-block provenance and sha256)
      without designing a class; the PackedCache v1 run-scoped charter is
      preserved and explicitly not retrofitted; and API shape constraints forbid
      an all-in-one facade, an ambient context blob, and make_/create_ factory
      constructors in any successor.
    status: pending
  - id: ac-008
    summary: Layer boundary and dual-use derivation conveyor are recorded
    type: docs
    pass_when: |
      The spec states that the molhub-side shard-to-derived-block converter is
      the same three-stage conveyor with train replaced by convert, sharing the
      four-state ledger, byte-bounded queues, no-double-copy rule and digest
      discipline; reaffirms the molexp / molhub / molnex boundary from
      molnex:.claude/notes/learnable-classical-ff.md, including that no MolHub adapter
      or dataset coordinate enters a molnex library API and that THEMol, OMol25
      and OPoly26 appear only as sizing examples; and records
      molcrafts/class1-universal-splits@1 (molecule-level 8:1:1, seed 20260814)
      as a hot-tier input with split-before-sampling and
      task-to-molecule/scan-to-configuration still binding per
      molnex:.claude/notes/production-training-checklist.md section 1. Multi-run
      consumption is resolved as plan-scoped refcounted leases, with the
      mechanism explicitly deferred to -03.
    status: pending
  - id: ac-009
    summary: Strategy lands as documentation only, with a durable note and index entry
    type: docs
    pass_when: |
      `git diff --stat` for this spec shows changes confined to `.claude/` paths
      (spec, acceptance, `.claude/notes/streaming-data-tiers.md`,
      `.claude/specs/INDEX.md`) with no file under molhub `src/` or `tests/` touched; molhub's `uv run ruff check src/ tests/` and
      `uv run pytest -q` are green and unchanged from the branch
      baseline; `.claude/notes/streaming-data-tiers.md` carries the tier table,
      the four-state lifecycle and the invariant register so the strategy
      survives deletion of this spec; `.claude/specs/INDEX.md` lists this spec in
      the active set; and the spec states which successor owns each deferred
      `regressions/` example.
    status: pending
---

# Acceptance criteria

This is a strategy-of-record spec: it lands no code, so every criterion is typed
`docs` and is checked by reading the persisted document against the current tree.
Code-typed criteria would be dishonest here — there is no new symbol to exercise,
and ac-009 exists precisely to prove that nothing under `src/` moved.

- **ac-001 – ac-003** bind the strategy's structural core: the tier model, the
  four-state block lifecycle, and the invariant register. These three are what
  successors inherit; a gap here propagates into every later spec.
- **ac-004** is the feasibility argument and the one place numbers can be wrong
  in a load-bearing way. It fails if any figure is unsourced, unlabelled as
  indicative where it is indicative, or not re-derivable by hand — and
  specifically if the document claims a comfortable margin without stating that
  the prepare stage, not the network, is the first constraint to bind.
- **ac-005** is the compatibility argument against the verified loader surfaces,
  and requires the scaling risk to be *named* rather than smoothed over, per the
  repository's no-silent-debt rule.
- **ac-006 – ac-008** bind the remaining strategy decisions that successors must
  not re-litigate: coverage semantics, the publishing level, the successor
  contracts, and the layer boundary.
- **ac-009** is the code-freeze and durability gate. Because active specs are
  deleted on completion, the strategy is only genuinely landed once
  `.claude/notes/streaming-data-tiers.md` carries it.

Deferred regression obligations (inherited, not waived):
`regressions/streaming-data-tiers-02-block-format.py` is owned by
`-02-block-format`, `regressions/streaming-data-tiers-03-conveyor.py` by
`-03-conveyor`. Each successor must carry its own `type: runtime` criterion with
hard-coded goldens.
