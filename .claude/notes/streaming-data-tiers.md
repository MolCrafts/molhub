# Streaming data tiers — strategy of record

Source: spec `streaming-data-tiers-01-strategy` (2026-08-14, operator-directed).
Successors: -02-block-format [molnex], -03-conveyor [molhub], -04-scheduler-integration [molnex].

### 1. Three tiers

| Tier | Contents | Size budget | Lifetime | Deletion |
|---|---|---|---|---|
| **T0 REMOTE** | full corpus + provenance (THEMol, OMol25, OPoly26 as published) | arbitrary (TB) | permanent, immutable, versioned | never (upstream) |
| **T1 LOCAL rolling** | compressed/published blocks in flight | bytes-bounded queue, ≈ 40 GB | minutes | deleted as soon as its READY block is confirmed |
| **T2 READY** | decompressed, converted, indexed, directly consumable blocks | bytes-bounded queue, ≈ 40 GB | one consumption window | deleted after consumption unless resident-flagged |
| **T-HOT** (cross-cutting) | indexes, split manifests, count/label metadata, validation sets, Hessian core | tens of GB, ≈ 60 GB | whole run | never during the run |

Peak local footprint is therefore `hot + T1 + T2 ≈ 60 + 40 + 40 = 140 GB`,
leaving ≈ 160 GB of the 300 GB budget as prepare scratch and headroom. Note the
queues must be bounded **in bytes, not in block count**: four published THEMol
shards at the 20 GB end of the range would alone be 80 GB.

A training machine **never holds a full copy** of T0. There is no "download
everything first" mode, and no configuration flag may create one.

### 3. Block state machine — exactly four states

```
REMOTE ──fetch──> DOWNLOADING ──unpack+prepare+verify──> READY ──consume──> CONSUMED
   ^                   │                                    │                  │
   └───────────────────┘ (failed / digest mismatch: retry)   │        delete unless resident
                                                             └── resident-flagged: stays READY
```

- **REMOTE** — known from the hot index (uri, size, sha256, split, task, unit
  count); nothing local.
- **DOWNLOADING** — bytes arriving into T1; partial files are never visible to
  the consumer.
- **READY** — downloaded **and** unpacked **and** preprocessed **and** digest
  verified. "READY" is a single conjunctive state on purpose: there is no
  half-ready state a consumer could accidentally read.
- **CONSUMED** — every registered consumer plan has finished with it; deleted
  unless resident-flagged.

State lives in a **tiny local ledger** (one small append-oriented file per block
store, hot tier). Every stage is idempotent, so after a crash the true state is
re-derivable from *files present ∧ ledger*, and any block in an intermediate
state is simply re-run. Digest verification happens at the remote→local boundary
with bounded retry: transient corruption of a downloaded shard has been observed
in practice, so a mismatch must trigger re-fetch, and a mismatching block must
never reach READY. The in-repo precedent for digest-pinned fetching is
`WaterLESSource` (`molnex:src/molix/datasets/_data_acquisition.md`,
`molnex:src/molix/datasets/water_les.py`); which layer implements the fetcher is a
successor decision, but the invariant is fixed here.

### 11. Invariant register (binding on every successor)

| # | Invariant | Owner of enforcement |
|---|---|---|
| **I1** | Block independence — every block is independently downloadable, preparable, consumable, deletable; no correctness property depends on another block being present. | -02, -03 |
| **I2** | Unit integrity — a sampling unit (molecule bundle / complete torsion scan) never straddles two blocks; a block is split-pure. | -02 |
| **I3** | No double copy — compressed and prepared copies of one block coexist only during its prepare window; compressed input is deleted once READY is confirmed. | -03 |
| **I4** | Bounded residency — queues are bounded in **bytes**; `hot + T1 + T2 ≤ local budget`; no code path and no flag may materialize a full local copy. | -03 |
| **I5** | Four states only — `REMOTE → DOWNLOADING → READY → CONSUMED`; every stage idempotent; true state re-derivable from files present ∧ ledger after a crash. | -02, -03 |
| **I6** | Digest at the boundary — sha256 verified on every remote→local transfer, bounded retry on mismatch; a mismatching block never reaches READY. | -03 |
| **I7** | Sampling discipline preserved — molecule-level split before configuration sampling; no flat frame pool; no block mixes splits; `task → unit → configuration` intact. | -02, -04 |
| **I8** | Plan authority — the plan is computed from hot metadata only; the conveyor may reorder *prefetch* but never the consumed order; shuffling stays plan-level, never within-block-only; a missing block stalls and is reported, never silently skipped or substituted. | -04 |
| **I9** | Scoped deletion — deletion is plan-scoped and refcounted across concurrent consumers; resident-flagged blocks are exempt. | -03 |
| **I10** | Coverage accounting — every pass records the blocks it visited; partial coverage is legitimate but must be reported, never implicit. | -03, -04 |

### 12. Successor chain — handoff contracts

| Spec | Owned surface | Must satisfy | Exit criterion |
|---|---|---|---|
| **-02-block-format** (repo: **molnex**) | the READY-tier block store format (`PackedCache` v2 / `PackedStore`) as a *streaming-appendable column store* | I1, I2, I5, I7 | format is: **appendable** (a block can be written incrementally without rewriting predecessors), **unit-aligned** (I2 structural, not checked), **mmap zero-copy** on read, **few files per block** (HPC inode discipline, per `molnex:src/molix/store/cache.py:1-49`), **per-block provenance + sha256** embedded. Requirements only — the class design is out of scope here. |
| **-03-conveyor** (repo: **molhub**) | prefetch / prepare stages, the block ledger, queue backpressure, leases | I3, I4, I5, I6, I9, I10 | a bounded-residency conveyor that keeps a ready queue non-empty under measured `B_net`, recovers from a mid-block crash, and provably never exceeds the byte budget. |
| **-04-scheduler-integration** (repo: **molnex**) | block-aware batch iterator behind `batch_sampler_source`, plan↔block mapping, R1 resolution | I7, I8, I10 | the eager plan of `molnex:src/molix/batch/sampler.py:267` drives consumption unchanged at small scale, with the per-frame-table crossover measured and the chosen representation landed. |

`PackedCache` v1 (`molnex:src/molix/store/cache.py:91`) keeps its documented **run-scoped,
non-persistence** charter (`cache.py:1-49`) and is **not** retrofitted into the
block store; the READY-tier format is a new artifact owned by `-02`.

### 13. Shape constraints on successor APIs (default design preferences apply)

Successor specs must expose **primitive types with single-responsibility
methods** — construct → configure → one concern → read result. Specifically
forbidden, per molnex/molhub `CLAUDE.md § Design preferences` (shared MolCrafts defaults): a `run_everything()` /
`StreamingPipeline.start()` all-in-one façade that hides download+prepare+train
wiring; an ambient "streaming context" blob threaded through every layer;
`make_*` / `create_*` factory wrappers around construction. Composition of the
three stages is the caller's job (scripts, `regressions/`, molexp).

