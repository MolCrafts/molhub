---
title: Streaming data tiers — remote / rolling / ready strategy
status: approved
created: 2026-08-14
chain: streaming-data-tiers
scope: design-strategy
---

# Streaming data tiers — remote / rolling / ready strategy

## Summary

Training collections we intend to consume (THEMol raw ≈ 6.5 TB, plus OMol25 and
OPoly26 later) are one to two orders of magnitude larger than the local disk
budget of a training node (≈ 300 GB), yet training must **logically** consume the
whole collection. This spec binds the strategy that makes that possible: data
lives in three tiers (permanent **REMOTE** full corpus, a fixed-size **LOCAL
rolling buffer**, and a few **TRAINING-READY** blocks), the corpus is decomposed
into many independent 1–5 GB blocks instead of one giant archive, and download ∥
prepare ∥ train run as a three-stage conveyor with two short byte-bounded queues.
It also resolves the one real tension with the existing loader: the eager global
plan built by `TaskMixtureBatchSampler` stays authoritative because plan-level
metadata is hot-tier resident, so we **plan globally and consume rolling** — the
plan induces the block visit order and the conveyor merely realizes it. This spec
lands **no code**: it fixes the tier model, the four-state block lifecycle, ten
binding invariants, the throughput condition with measured numbers, and the
handoff contracts for the successor specs (`-02-block-format`, `-03-conveyor`,
`-04-scheduler-integration`). The document itself is the deliverable, following
the closed investigation-spec precedent
`molnex:.claude/specs/lammps-pair-molnex-01-aoti-force-export-wall.md` (closed).

## Domain basis — measured rates, byte accounting, sampling discipline

Units: `MB/s = 10^6 B/s`, `GB = 10^9 B`, `conf/s` = configurations (frames)
consumed per second by the training step, coordinates stored `float32`
(4 B/component), positions in Å.

### Measured / observed anchors

| Quantity | Value | Provenance |
|---|---|---|
| Sustained HF download, login node | **20 MB/s** | observed, sustained (not burst) |
| THEMol raw corpus | **≈ 6.5 TB** | upstream publication layout |
| THEMol published shard size | **4–20 GB** per shard | upstream layout |
| Local per-node disk budget | **≈ 300 GB** | site constraint |
| Derived block target | **1–5 GB** | this spec (see § Design) |
| GH200 train rate, medium (h512), packed | **≈ 2000 conf/s** | prior calibration, indicative |
| GH200 train rate, small, packed | **≈ 3700 conf/s** | prior calibration, indicative |

The two GH200 rates were measured on a **superseded dataset composition** and are
recorded here as order-of-magnitude anchors only. Any production submission must
re-derive them under `molnex:.claude/notes/production-training-checklist.md` § 5 for the
exact configuration; nothing in this spec licenses reusing them as calibration
evidence.

### Per-frame byte accounting (40-atom drug-like molecule)

| Payload | Arithmetic | Bytes/frame |
|---|---|---|
| Coordinates only | 40 × 3 × 4 B | 480 |
| + energy, frame scalars, index overhead | 480 + ~20 | **≈ 500 (E-only)** |
| + forces | 480 + 480 + 4 | **≈ 1.0 kB (E+F)** |
| Hessian (per molecule, full) | (3·40)² × 4 B = 14 400 × 4 | 57.6 kB |
| Hessian (per molecule, upper triangle) | 7 260 × 4 | 29 kB |

Topology (atomic numbers, bond graph, types) is stored **once per molecule /
scan**, not per frame, so it is amortized away at scan lengths ≫ 1.

Consequences used below: a 2 GB E-only derived block holds
`2·10^9 / 500 ≈ 4.0 × 10^6` frames; a 2 GB E+F block holds `≈ 2.0 × 10^6` frames.
A Hessian core of 10^5 molecules costs `10^5 × 57.6 kB ≈ 5.8 GB` — small enough
to be permanently resident, which is why Hessian data is classified hot below.

### The throughput condition, in byte-rate form

The naive form is `t_download + t_prepare ≲ t_train` per block. Because all three
times scale linearly in block size, the block size **cancels**: feasibility is a
*rate* condition, and block size only sets pipeline latency and peak disk.

```
(1)  r_train · B_frame  ≤  B_net          [network stage]
(2)  r_train            ≤  W / c_prep     [prepare stage]
```

where `r_train` is aggregate frames/s across all training ranks fed by one
conveyor, `B_frame` the *transferred* bytes per consumed frame (including any
downloaded payload the run does not use), `B_net = 20 MB/s`, `W` prepare worker
cores, and `c_prep` single-core CPU seconds per prepared frame.

Condition (1), evaluated:

| Regime | `r_train` | `B_frame` | consumed byte rate | margin vs 20 MB/s |
|---|---|---|---|---|
| medium h512, 1 GPU, E-only | 2 000 | 500 B | 1.0 MB/s | 20× |
| small, 1 GPU, E-only | 3 700 | 500 B | 1.85 MB/s | 10.8× |
| medium h512, 1 GPU, E+F relax | 2 000 | 1.0 kB | 2.0 MB/s | 10× |
| small, 4 GPUs, E-only | 14 800 | 500 B | 7.4 MB/s | 2.7× |
| small, 8 GPUs, E-only | 29 600 | 500 B | 14.8 MB/s | **1.35× — binds** |
| small, 8 GPUs, raw shards, 4× unused payload | 29 600 | ≈ 2 kB | 59 MB/s | **violated (≈ 3× over)** |

Condition (2), evaluated at a plausible `c_prep = 5 ms/frame` (neighbor list +
pack, single core): 1 GPU medium needs `W ≥ 5·10^-3 × 2000 = 10` cores; 8-GPU
small needs `W ≥ 148` cores, which **exceeds** the 72 Grace cores of a GH200
node. Honest ranking of the two stages:

> **Download has an order-of-magnitude margin in the single-GPU regime; the
> prepare stage is the first thing that binds as `r_train` grows.** The strategic
> answer is therefore not "download faster" but "publish blocks that need almost
> no prepare" — see streaming level L3 and the derivation conveyor in § Design.

Latency and disk sanity checks at the chosen block size: a 2 GB block downloads
in `2·10^9 / 20·10^6 = 100 s` and trains for `4·10^6 / 2000 = 2000 s ≈ 33 min`
(E-only, medium) or `2·10^6 / 2000 = 1000 s ≈ 17 min` (E+F). A 20–50 GB pre-warm
before training starts costs `1 000–2 500 s ≈ 17–42 min` of wall time. One full
pass over the *raw* 6.5 TB corpus costs `6.5·10^12 / 20·10^6 = 3.25·10^5 s
≈ 90 h ≈ 3.8 days` of network — which is exactly why coverage-over-time
(§ Design 7) replaces rigid full-epoch sweeps at this scale.

### Sampling-discipline basis (why streaming must not relax it)

- Molecule-level split before configuration sampling, groups never straddling a
  split: Wang, Fass, Chodera, *End-to-End Differentiable Construction of
  Molecular Mechanics Force Fields*, Chem. Sci. **13**, 12016 (2022).
  DOI:10.1039/D2SC02739A — https://doi.org/10.1039/D2SC02739A
- Stage/mixture structure the current sampler already encodes: Zheng et al.,
  *ByteFF*, arXiv:2408.12817 (2024) — https://arxiv.org/abs/2408.12817
- Sharded streaming I/O for large-scale training (many medium independent shards,
  sequential-within-shard reads): Aizman, Maltby, Breuel, *High Performance I/O
  For Large Scale Deep Learning*, arXiv:2001.01858 (2020) —
  https://arxiv.org/abs/2001.01858
- Stage overlap / prefetch as the standard input-pipeline remedy: Murray et al.,
  *tf.data: A Machine Learning Data Processing Framework*, PVLDB **14**(12) 2945
  (2021). DOI:10.14778/3476311.3476374, arXiv:2101.12127
- Why a shuffled *visit order over units* (not i.i.d. sampling with replacement)
  is an acceptable optimization regime: Mishchenko, Khaled, Richtárik, *Random
  Reshuffling: Simple Analysis with Vast Improvements*, NeurIPS 2020,
  arXiv:2006.05988 — https://arxiv.org/abs/2006.05988

Streaming introduces one genuine statistical hazard: if shuffling degenerates to
*within-block only*, batches become block-correlated and the mixture guarantees
of `TaskMixtureBatchSampler` no longer hold across the epoch. Invariant I8 below
forbids that degeneration — the plan, not the arrival order, decides consumption
order.

## Design

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

### 2. Block decomposition is the enabling premise

The corpus is treated as **many independent blocks of 1–5 GB**, never one giant
file. The unit of work at every stage is one block: download one → prepare one →
consume one → delete one. Blocks are independent in the strong sense that no
correctness property of block *k* depends on block *j* being present.

**Block boundaries are cut on sampling-unit boundaries.** A sampling unit — a
molecule's conformer bundle, or a *complete* torsion scan — must never straddle
two blocks. This is the streaming-tier mirror of the unit-integrity property that
`TokenBudgetPacker` already provides inside a batch
(`molnex:src/molix/batch/sampler.py:47`, and its aggregate-cost use at
`molnex:src/molix/batch/sampler.py:571-620`): a scan only carries its torsion profile
when its frames are comparable within one batch, so a scan split across two
blocks would either break the profile or force both blocks resident, defeating
delete-after-consume. Blocks are additionally **split-pure**: one block belongs
to exactly one of train / validation / test.

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
molhub's own `Molhub.fetch` + `sources/digest.py`, consumed by the reception
adapters (`src/molhub/dataset/water_les.py`; the former molnex `WaterLESSource`
was deleted at molnex `6d425f7` — see `molnex-etl-tombstone.md`); which layer
implements the fetcher is a
successor decision, but the invariant is fixed here.

### 4. Three-stage conveyor

```
network:  download C ──► [compressed queue: 2–4 blocks, byte-bounded]
cpu:                     prepare B ──────► [ready queue: 2–4 blocks, byte-bounded]
gpu:                                        train A
```

GPU trains block A while CPU prepares B while the network downloads C. The two
short queues exist to absorb jitter (HF throughput dips, filesystem stalls), not
to accumulate data. Sizing follows from the rate condition in § Domain basis,
with the four listed remedies when it is violated, in increasing order of cost
and decreasing order of preference:

1. **Raise per-byte utilization** — one download of a molecule should serve every
   task that needs that molecule (conformers, Hessian, torsion frames, forces)
   rather than being re-downloaded per task. This is the single most effective
   lever, because `B_frame` in condition (1) counts *transferred* bytes, and the
   8-GPU raw-shard row of the table fails by a factor of 3 purely on unused
   payload.
2. **Deeper prefetch** — more queued blocks; costs disk, buys jitter tolerance
   only, does not change the mean rate.
3. **Parallel downloads** — several concurrent block fetches; raises effective
   `B_net` where the bottleneck is per-connection, not per-site.
4. **Pre-warm 20–50 GB before training starts** (≈ 17–42 min) — the most
   practical mitigation in practice, because it converts a steady-state deficit
   into a bounded head start and hides cold-start latency entirely.

Never hold a compressed and an unpacked copy of the same block for longer than
the prepare window: download → unpack → confirm READY → **delete compressed** →
train → **delete unpacked**.

### 5. Plan globally, consume rolling — the resolution

`TaskMixtureBatchSampler` (`molnex:src/molix/batch/sampler.py:267`) builds an **eager,
fully deterministic** plan in `__init__` from **metadata only**: per-sample
atom/edge counts via packed-cache pointer arithmetic
(`sampler.py:532-547`), caller-supplied `task_labels` / `group_ids`, a mixture,
largest-remainder apportionment with anti-starvation, and a `seed + epoch`
reseed convention that keeps epoch *k* re-derivable on resume. It never unpacks a
sample.

This looks incompatible with streaming ("how can you plan an epoch you have not
downloaded?"), and it is not. **Plan-level metadata is hot-tier data** — indexes,
split manifests, counts, labels, and the block index total order GBs, not TBs, so
they are resident for the whole run. Therefore:

- the **global plan is computed up front**, exactly as today;
- the plan **induces the block visit order** (each planned batch's frames belong
  to known units, each unit to exactly one block, by § 2);
- the **conveyor realizes the plan**: it makes the next-needed blocks READY ahead
  of time and may reorder *prefetch* freely, but never the consumed order.

**The sampler needs no redesign.** What is missing is a *block-aware iterator /
scheduler layer* that maps plan slices to READY blocks and applies backpressure
when a needed block is not yet READY. `DataModule` already has the seam for it:
`batch_sampler_source` (`molnex:src/molix/batch/datamodule.py:148`, called once per epoch
with `seed + epoch` at `molnex:src/molix/batch/datamodule.py:264-266`, protocol at
`molnex:src/molix/batch/sampler.py:811`). That layer is owned by
`-04-scheduler-integration`, not by this spec.

Named scaling risk (recorded, not waived — Iron law):

> **R1 — per-frame Python tables are the plan's memory wall, not the policy.**
> `TaskMixtureBatchSampler` consumes `task_labels` / `group_ids` as parent-space
> Python sequences of length `len(dataset)`, and `TokenBudgetPacker.__init__`
> materializes counts as Python int lists (`molnex:src/molix/batch/sampler.py:89`). At
> 10^6–10^7 frames this is irrelevant. At 10^8 frames it is ≈ 0.8–3.6 GB per
> count vector plus ≈ 6–8 GB for distinct `"<mol>:<dihedral>"` group strings.
> The sampling *policy* is sound at any scale; the *representation* is not.
> `-04` must measure the crossover and choose one of: plan at **unit/block**
> granularity (units per block ≪ frames), or replace Python-int materialization
> with tensor arithmetic and dictionary-encoded int32 label columns. Blocks make
> this cheap: the block index itself is tiny (10^5 blocks × ~200 B ≈ 20 MB).

### 6. Hot vs cold classification

| Class | Data | Why | Residency |
|---|---|---|---|
| **Hot** | split manifests, block index, count/label metadata, validation sets, Hessian core (≈ 5.8 GB at 10^5 molecules), unit→block map | small, high-value, read every epoch or needed to plan at all | permanently resident, tens of GB |
| **Cold / bulk** | relaxation trajectories, torsion frames, OMol25 bulk | huge, each frame seen rarely | rolls through T1/T2, deleted after consumption |

Validation sets are hot by necessity: an eval phase that had to wait on the
network would couple the scheduler's `best_metric` read to download jitter.

### 7. Coverage semantics — "using all data" ≠ simultaneous residence

Logical consumption of the full corpus is defined as **coverage over time**: the
plan visits blocks in plan order across passes, so every block is eventually
visited even though only a handful are ever resident. Partial coverage per pass
is legitimate and expected at this scale — visiting ~10% of the corpus per round
and eventually covering everything is strictly better than a rigid full-epoch
sweep that cannot start until 90 h of network has elapsed (§ Domain basis). At an
assumed 2 TB derived corpus, a 10% round costs `200·10^9 / 20·10^6 = 10^4 s
≈ 2.8 h` of network, and full coverage ≈ 28 h — overlapped with training, not
serialized before it.

Two guardrails make this a sampling statement rather than an excuse:

- Every pass **records which blocks it visited**; coverage is reported, never
  implicit (I10). A pass that silently skipped a block is a failure, not a
  sample.
- Shuffling must remain **plan-level**, over units across the whole split, not
  within-block only (I8) — otherwise batch composition becomes block-correlated
  and the mixture fidelity of `TaskMixtureBatchSampler` is lost.

### 8. Streaming levels of published data

| Level | Format | Local cost | Verdict |
|---|---|---|---|
| **L1** | must be fully unpacked before any read (`tar.gz` of a whole source) | worst: needs whole-archive space, no partial progress, prepare cannot overlap | tolerate only for legacy sources |
| **L2** | stream-decompressable (sequential decode while downloading) | prepare overlaps download; still no random access | acceptable |
| **L3** | natively chunked, random-access shards, already READY-shaped | verify + mmap only; prepare stage nearly collapses | **best — the target for anything we publish** |

Publishing recommendation, binding for MolCrafts-produced data: **many medium
independent shards** (1–5 GB), unit-aligned, digest-pinned, at L3. This is the
only structural fix for the prepare-stage bound of condition (2): if published
blocks are already READY-shaped, `c_prep` collapses toward verify+mmap and the
8-GPU regime stops being prepare-bound. It is also the standard conclusion of the
sharded-streaming literature (arXiv:2001.01858).

### 9. Derivation is the same conveyor, with `train` replaced by `convert`

The producer side — turning published upstream shards into unit-aligned derived
blocks — is **the same three-stage pipeline**: `download shard ∥ convert ∥ delete
shard`, with the same four-state ledger, the same byte-bounded queues, the same
no-double-copy rule, and the same digest discipline. Naming this dual use is
deliberate: the conveyor abstraction earns its keep twice, and neither side may
invent a private lifecycle.

The layer boundary from `molnex:.claude/notes/learnable-classical-ff.md` (§ *Library and
experiment boundaries*) is unchanged and binding:

- **molhub** owns versioned datasets/collections, parsing, provenance, units,
  grouping, identity, splits — therefore it owns the *derivation* conveyor and
  every concrete remote coordinate.
- **molnex** owns dataset-agnostic consumption primitives. MolNex must never
  import a concrete MolHub dataset adapter or hard-code a dataset coordinate in
  its library API. THEMol / OMol25 / OPoly26 appear in this spec only as sizing
  examples.
- **molexp** owns the experiment that resolves coordinates and pins the
  fingerprint (`molnex:.claude/notes/production-training-checklist.md` § 0).

Splits are already produced upstream and are hot-tier inputs here:
`molcrafts/class1-universal-splits@1`, molecule-level 8:1:1, seed 20260814.
Split-before-sampling and `task → molecule/scan → configuration` remain binding
(molnex checklist § 1); streaming changes *when bytes arrive*, never *what is sampled*.

### 10. Multi-source, multi-run, multi-node

Sources are **not** downloaded one whole source at a time. The training schedule
declares its near-future need — "next I need Hessian block H31, Torsion T72,
Relax R291" — and the conveyor makes exactly those READY ahead of time. Block
identity is therefore `(source, task, split, block_id)`, and interleaving across
sources is the normal case.

One block store may be consumed concurrently by a calibration run and a training
run. Deletion must therefore be **plan-scoped and refcounted**: a consumer
registers its plan's block set as a lease; a block reaches CONSUMED-and-deleted
only when every live lease has released it, and resident-flagged blocks are never
deleted. Decision stated here; mechanism (lease file format, stale-lease
expiry, multi-node visibility) is owned by `-03-conveyor`.

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

### Reuse decision

No `librarian_report` was supplied with this task, so the following verdicts come
from direct inspection of the surfaces named above; a blueprint refresh before
`-02` starts is advisable.

- `TaskMixtureBatchSampler` (`molnex:src/molix/batch/sampler.py:267`) — **reuse**. The
  eager metadata-only plan *is* the streaming plan authority (§ 5). No parallel
  sampler.
- `TokenBudgetPacker` (`molnex:src/molix/batch/sampler.py:47`) — **reuse** as the
  precedent and vocabulary for unit integrity (I2). No block-side packer is
  designed here.
- `BatchSamplerSource` (`molnex:src/molix/batch/sampler.py:811`) + `DataModule
  batch_sampler_source` (`molnex:src/molix/batch/datamodule.py:148`) — **reuse**. The
  block-aware iterator enters through this existing seam; `DataModule` needs no
  new entry point.
- `group_split_indices` (`molnex:src/molix/batch/group_split.py:11`) and the upstream
  `class1-universal-splits@1` manifests — **reuse** as hot-tier inputs. Streaming
  never re-splits.
- `PackedCache` (`molnex:src/molix/store/cache.py:91`) — **new** (in `-02`). Its
  docstring binds it to run-scoped, unversioned, unvalidated caching; the READY
  tier needs versioning, appendability, and per-block provenance, so widening
  v1 would violate its own stated charter.
- `MmapDataset` / `PackedView` / `SubsetDataset`
  (`molnex:src/molix/store/dataset.py:358`, `:48`, `:396`) — **generalize** in `-02`/`-04`
  (not here): the zero-copy read path and pointer-derived `atom_counts` /
  `edge_counts` accessors are exactly what a block-backed dataset must also
  expose, so the block store should serve the same accessors rather than
  spawning a parallel dataset hierarchy.
- `WaterLESSource` digest-pinned fetch precedent
  (the former molnex `_data_acquisition.md`, deleted at `6d425f7`; the surviving digest-pinned-fetch precedent is molhub `sources/fetcher.py`) — **pattern**. I6 follows its
  expected/actual sha256 discipline; no code is reused across the layer boundary.
- molhub / molexp responsibilities — **reuse** the boundary in
  `molnex:.claude/notes/learnable-classical-ff.md`; no MolHub coordinate or adapter is
  introduced into any molnex library API (§ 9).

## Files to create or modify

- `molhub:.claude/specs/streaming-data-tiers-01-strategy.md` (new) — this document; the deliverable.
- `molhub:.claude/specs/streaming-data-tiers-01-strategy.acceptance.md` (new) — the binding criteria.
- `molhub:.claude/notes/streaming-data-tiers.md` (new) — durable copy of the tier model, four-state lifecycle, and invariant register, so the strategy survives deletion of this spec on completion.
- `molhub:.claude/specs/INDEX.md` — register this spec in the active set.

## Tasks

- [ ] Write the three-tier model and hot/cold classification sections (tier table with byte budgets, peak-footprint arithmetic, no-full-local-copy rule) into `.claude/specs/streaming-data-tiers-01-strategy.md`
- [ ] Write the block-decomposition and four-state-lifecycle sections (1–5 GB independent blocks, unit-integrity and split-purity cut rule, `REMOTE → DOWNLOADING → READY → CONSUMED`, ledger, idempotency, digest-with-retry) into `.claude/specs/streaming-data-tiers-01-strategy.md`
- [ ] Record the measured anchors and derive the byte-rate throughput condition in Domain basis of `.claude/specs/streaming-data-tiers-01-strategy.md` (20 MB/s, 6.5 TB, 4–20 GB shards, 300 GB budget, 2000/3700 conf/s marked indicative, 500 B and 1 kB per-frame accounting, the six-row margin table, the prepare-core arithmetic, and the explicit statement that prepare binds before download)
- [ ] Write the invariant register I1–I10 with rationale and enforcing successor into `.claude/specs/streaming-data-tiers-01-strategy.md`
- [ ] Write the plan-globally-consume-rolling resolution into `.claude/specs/streaming-data-tiers-01-strategy.md`, citing `molnex:src/molix/batch/sampler.py:267`, `molnex:src/molix/batch/sampler.py:811`, `molnex:src/molix/batch/datamodule.py:148` and `:264-266`, asserting no sampling-policy redesign, and recording risk R1 with its `molnex:src/molix/batch/sampler.py:89` evidence
- [ ] Write the coverage-over-time semantics, streaming levels L1–L3 with the L3 publishing recommendation, and the derivation-conveyor dual use plus molhub/molnex/molexp layer boundary into `.claude/specs/streaming-data-tiers-01-strategy.md`
- [ ] Define the successor handoff contracts for `-02-block-format`, `-03-conveyor`, `-04-scheduler-integration` in `.claude/specs/streaming-data-tiers-01-strategy.md`, each with owned surface, inherited invariants, exit criterion, plus the API shape constraints and the `PackedCache` v1 charter carve-out
- [ ] Write the acceptance contract `.claude/specs/streaming-data-tiers-01-strategy.acceptance.md` with every criterion typed `docs` and `status: pending`
- [ ] Record the durable strategy summary (tier table, four states, invariant register, successor chain) in `.claude/notes/streaming-data-tiers.md` and register this spec in the active set of `.claude/specs/INDEX.md`
- [ ] Verify the doc-only gate: `git diff --stat` for this spec touches only `.claude/` paths in molhub, and `uv run ruff check src/ tests/` plus `uv run pytest -q` are green and unchanged from the branch baseline

## Testing strategy

This spec introduces **no Python symbol**, so it has no unit tests: there is
nothing under `src/` to mirror into `tests/`, and inventing a test would be
testing prose. Verification is documentary and structural:

- **Section completeness** — each acceptance criterion below names the section
  and the specific content that must be present; a missing table, number, or
  invariant fails that criterion.
- **Anchor validity** — every repo path and line reference in the document
  (`molnex:src/molix/batch/sampler.py:47`, `:89`, `:267`, `:532-547`, `:571-620`,
  `:811`; `molnex:src/molix/batch/datamodule.py:148`, `:264-266`;
  `molnex:src/molix/store/cache.py:1-49`, `:91`; `molnex:src/molix/store/dataset.py:48`, `:358`,
  `:396`; `molnex:src/molix/batch/group_split.py:11`;
  the former molnex `_data_acquisition.md` (deleted at `6d425f7`, superseded by molhub `sources/`);
  `molnex:.claude/notes/production-training-checklist.md`;
  `molnex:.claude/notes/learnable-classical-ff.md`) must resolve to the cited symbol or
  statement in the current tree.
- **Arithmetic re-derivation** — every number in § Domain basis must be
  reproducible from the stated inputs by hand (block frame counts, margin ratios,
  core counts, pre-warm and pass wall times). A number that cannot be
  re-derived is a defect.
- **Code-freeze check** — the diff for this spec must touch only `.claude/`;
  `ruff` and the unit suite must be green and unchanged, proving the strategy
  landed without silent code drift.

**Deliberate omission of a `regressions/` example.** The standing rule is one
regression example per spec, but a public-API script requires a public API, and
this spec lands none. The obligation is *inherited, not waived*, and is assigned
explicitly: `-02-block-format` owns `regressions/streaming-data-tiers-02-block-format.py`
(write two unit-aligned blocks, mmap-read them back, assert unit integrity and
per-block sha256 against hard-coded goldens) and `-03-conveyor` owns
`regressions/streaming-data-tiers-03-conveyor.py` (drive a fake three-block
remote through the four states with a hard-coded byte budget and assert peak
local bytes never exceed it). Neither may use a live third-party oracle. This
mirrors the closed investigation-spec precedent, which likewise deferred its
runtime criterion to the route-forward spec.

## Out of scope

- **MolHub API design** — remote coordinate resolution, collection/version APIs,
  the fetcher's own interface. Owned by molhub; this spec only fixes the
  invariants any fetcher must satisfy (I6).
- **Cache / block-store class design** — the concrete `PackedCache` v2 /
  `PackedStore` types, their methods, on-disk byte layout, and schema versioning.
  Owned by `-02-block-format`; only requirements are stated here.
- **Concrete daemon architecture** — process vs thread vs `asyncio`, worker
  counts, lease-file format, IPC, systemd/slurm supervision, multi-node
  coordination mechanism. Owned by `-03-conveyor`.
- **OMol25 / OPoly26 onboarding** — per-source schemas, unit conventions,
  dedup against THEMol, split production. Each needs its own dataset spec; they
  appear here only as sizing examples.
- **Any training run** — no calibration, smoke, or production job is authorized
  by this spec. The Iron law and
  `molnex:.claude/notes/production-training-checklist.md` remain fully binding, and the
  GH200 rates quoted here are explicitly **not** calibration evidence.
- **Re-tuning batch composition policy** — mixtures, token budgets,
  anti-starvation, stage curricula are unchanged; streaming alters byte arrival,
  not sampling policy.
- **Compression / codec selection** and on-the-wire format benchmarking
  (zstd level, chunk size) — a measurable sub-question for `-02`.
