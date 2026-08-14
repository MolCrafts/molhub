---
title: Conveyor residency, backpressure and coverage — byte-budgeted tiers, prepare workers, CLI
status: approved
grilled: true
slug: streaming-data-tiers-03-conveyor-04-residency
repo: molhub
chain: streaming-data-tiers-03-conveyor
created: 2026-08-14
---

# Conveyor residency, backpressure and coverage — byte-budgeted tiers, prepare workers, CLI

> **Repo: molhub** (`/home/jicli594/work/molcrafts/molhub`). Last of the four-spec
> `-03-conveyor` chain. `-01-ledger` (`BlockId` / `BlockState` / `Ledger` with
> lease-TTL records), `-02-roster` (`BlockRoster` / `ShardTransfer`) and
> `-03-prepare` (`PrepareJob` / `PreparedBlocks` / `THEMolUnitEncoder`, optional
> `prepare` extra) are **given contracts**: this spec consumes them through narrow
> read seams and redesigns none of them.

## Summary

This spec lands the part of the conveyor that decides *what stays on local disk*
and *what the run can prove it saw*: a byte-budgeted `TierStore` per tier (T1 raw
shards, T2 READY blocks), a byte-bounded backpressure queue plus a
multiprocessing prepare pool, a coverage report replayed from the ledger, a
torch-free metadata handoff for the molnex-side sampler, and two `molhub cache`
verbs to inspect both. It discharges the residency half of the `-03-conveyor`
exit criterion from `streaming-data-tiers-01-strategy`: invariants **I3** (no
double copy), **I4** (bounded residency, bounded in bytes), **I9** (scoped,
refcounted deletion — leased and resident-flagged blocks exempt) and **I10**
(coverage reported, never implicit). Eviction is ordered by the consumer's own
visit plan rather than by observed access time, which is what makes
"plan globally, consume rolling" mechanical instead of hopeful. Nothing here
imports torch: the sampler handoff is `manifest.json` read as JSON, so molhub
stays a data-plane repo and the block reader stays molnex's.

## Design

### 1. What each module owns

| Module | Owns | Does not own |
|---|---|---|
| `conveyor/tier.py` | one tier's on-disk residency: byte budget, admit / release / evict, the derived-artifact path + provenance convention | block state, leases, transfers, prepare |
| `conveyor/backpressure.py` | byte-weighted admission control between stages, and the worker processes that run `-03`'s prepare jobs | what a prepare job *is* (`-03`) |
| `conveyor/coverage.py` | what the run has seen (ledger replay) and what it can consume right now (sealed manifests) | batch composition, sampler construction (molnex `-04`) |

### 1b. Single-writer discharge — who appends transitions

`-01-ledger` R1 requires a single transition writer per ledger. This chain
discharges it operationally: **the conveyor driver — the one process that owns
the `ShardTransfer`, submits jobs to `PrepareWorkers`, and holds the
`TierStore`s — is the sole ledger-transition writer.** `PrepareWorkers` workers
never touch the ledger (they return `outcome`/`PreparedBlocks` values); the
driver appends DOWNLOADING/REMOTE through `-02`'s `ShardTransfer` (which it
invokes in-process), READY per sealed derived root and READY → CONSUMED for the
raw shard from `-03`'s `PreparedBlocks`, and REMOTE-on-deletion through
`TierStore`. Lease records are exempt from R1 (any number of holders). Running
**two drivers over one ledger is out of contract**: multi-node / multi-driver
writer election is explicitly deferred to a named future spec,
`streaming-data-tiers-05-multinode` — single-node single-driver is the v0
operating mode. [Added 2026-08-14 after spec-audit: `-01` R1's deferral
previously had no accepting owner.]

### 2. `TierStore` — one store, one subdirectory, one budget

Shape of record is `molhub.dataset.cache.DownloadCache` (`src/molhub/dataset/cache.py:51`):
a store owns exactly one subdirectory, injects its collaborators, and **defers
root resolution to `BlobStore`** so `$MOLHUB_HOME` is resolved in exactly one
place in the repo. `TierStore(root=None, *, subdir, budget_bytes, ledger)`; the
conveyor uses two instances — `subdir="conveyor/raw"` (T1, published shards in
flight) and `subdir="conveyor/blocks"` (T2, sealed READY blocks). Two instances
means the two budgets are **structurally independent**: there is no shared
counter, no shared candidate set, and no code path in which pressure on one tier
can delete an entry of the other. Neither subdirectory is under `files/`, which
stays the cross-client layout contract the TypeScript client reads.

Primitives (construct → configure → one concern → read result):

- `path_for(block_id) -> Path` — where that block's bytes live in this tier;
  touches nothing.
- `admit(block_id, *, nbytes) -> Path` — record residency of *nbytes* and return
  the (created) directory. Raises `TierOverBudget` when it does not fit; it does
  **not** evict silently, because a stage that is out of room must decide
  whether stalling or evicting is correct, and hiding that decision inside
  `admit` is exactly the all-in-one façade the strategy's § 13 forbids.
- `release(block_id)` — delete this tier's copy and free its bytes. Refuses with
  `BlockUnevictable` when the ledger reports a live lease (I9) or when the block
  is resident-flagged.
- `evict_until(free_bytes, *, plan) -> tuple[BlockId, ...]` — free at least
  *free_bytes*. **Plans before deleting**: it builds the ordered candidate list,
  checks feasibility, and only then unlinks. If the target cannot be met it
  raises `TierOverBudget` **having deleted nothing**, naming the blocked
  candidates and why (leased / resident-flagged / not CONSUMED). Stalling is the
  correct failure; breaking a lease is not.
- `flag_resident(block_id)` — the T-HOT exemption (validation sets, Hessian
  core). Idempotent; makes the entry permanently ineligible for eviction.
- `resident_bytes`, `headroom`, `entries()` — read-only residency.

**Byte accounting.** The budget is enforced against **declared** sizes, because a
shard must be admitted before its bytes exist. Disk is the source of truth
exactly once, at construction: the store re-derives its entries and their sizes
by walking its own subdirectory, so residency survives a crash from
*files present ∧ ledger* (I5) with no extra recovery verb.

**Eviction order — LRU re-expressed as plan distance.** Candidates are this
tier's entries that are `BlockState.CONSUMED`, unleased and unflagged. They are
ordered by their position in the consumer's `VisitOrder`:

1. not in the plan at all → coldest (nothing will ask for it again),
2. behind the cursor → ascending position (longest since the plan passed it),
3. ahead of the cursor → descending position (the furthest future first),
4. ties → ascending `BlockId`, so the sequence is reproducible.

`VisitOrder(order, cursor)` is a frozen value object holding block ids and an
integer. It is **metadata-only and never evictable**: it is never admitted to a
tier, occupies no entry, and no method accepts it as an admission target. This is
the mechanical form of the strategy's § 5 — the plan induces the visit order and
the conveyor realizes it.

**Ledger writes.** `TierStore` writes exactly one kind of record: the return to
`REMOTE` when local bytes are deleted (by `release` or `evict_until`). No fifth
state is invented — a block with nothing local *is* REMOTE by `-01`'s own
definition. Every other transition belongs to `-02`/`-03`. That one record is
what makes `bytes_evicted` and the coverage timeline derivable after a restart
instead of living in process memory.

**Seams.** `BlockLedger` is a `Protocol` in `tier.py` with the three methods this
module needs — block state, live-lease query, record append — and `-01`'s
`Ledger` satisfies it structurally (method spellings follow `-01` verbatim; this
is a read/append *view*, never a second ledger). Unit tests drive `TierStore`
with a fake implementing those three methods and nothing else.

### 3. `DerivedLayout` — the generalized derived-artifact convention

`scripts/build_class1_splits.py` invented the convention that this spec's blocks
tier needs: a coordinate-shaped artifact directory
`<root>/<subdir>/<ns>/<name>/<ver>/` (`scripts/build_class1_splits.py:91`) plus a
`metadata.json` recording input sha256s, output sha256s, seed and generator
(`:141-167`). It is ownerless — a path expression inline in a script — and this
spec needs the identical rule for `conveyor/blocks/`. It is therefore
**generalized**, not reimplemented: `DerivedLayout(root, *, subdir)` with
`artifact_dir(namespace, name, version) -> Path` and
`write_metadata(directory, document)` (tmp → fsync → `os.replace`, `indent=2`
plus trailing newline — byte-identical to what the script writes today, with
presence of `generator` / `generated_at` validated and contents left to the
producer). `TierStore` holds one for its subdirectory; the splits script
constructs its own for `derived/` and **keeps producing splits exactly as now**.
Two users, one rule.

**`metadata.json` vs `manifest.json` — a boundary worth stating once.**
`metadata.json` sits at the *artifact* level and describes the derivation run
(inputs, outputs, seed, generator). `manifest.json` sits *inside* a block
directory and is molnex's `molix.block/1` contract (columns, split, task_names,
units, rows, digests, sealed). They never merge and never nest; a block
directory that grew a `metadata.json` would be a schema collision waiting to be
mis-parsed by one of the two repos.

### 4. `ByteBoundedQueue` — bounded in bytes, released by deletion

Queues are bounded **in bytes, not in block count** (I4; four 20 GB THEMol shards
would be 80 GB). The queue is byte-weighted FIFO handoff between two stages:

- `reserve(item, *, nbytes, timeout=None)` — blocks until *nbytes* fit under the
  capacity, then holds them and appends *item*. `timeout=0` polls once and raises
  `QueueTimeout`; `None` waits indefinitely. `nbytes > capacity_bytes` raises
  `QueueOversized` **immediately** — a reservation that can never be satisfied is
  a deadlock, not backpressure.
- `take(timeout=None) -> tuple[str, int]` — hand the next item downstream. It
  does **not** free bytes: the bytes are still on disk. This is the whole reason
  the queue is not `queue.Queue` — freeing on dequeue would let residency exceed
  the budget by a full pipeline depth.
- `release(item)` — the item's bytes are gone from disk; free them and wake
  waiters.
- `held_bytes`, `capacity_bytes`, `pending`.

**Determinism, pinned.** The binding contract is the `timeout=0` probe: full →
`QueueTimeout`, after `release` → admitted. That is a single-threaded,
sleep-free, wall-clock-free assertion, and it is what the acceptance criteria and
the regression pin. Exactly one threaded test proves a genuinely *blocked*
reserve wakes: the waiter sets a `threading.Event` immediately before calling
`reserve(..., timeout=5)`, the main thread waits on that event, releases, and
asserts `thread.join(timeout=5)` completed. Event-synchronized and bounded — no
`time.sleep` anywhere in the file.

### 5. `PrepareWorkers` — processes, because prepare is the stage that binds

Condition (2) of the strategy's Domain basis is the binding one: prepare needs
`W ≥ c_prep · r_train` cores, so the pool must use **processes** (CPU-bound work
behind the GIL), not threads. There is no multiprocessing anywhere in
`src/molhub/` today; the only concurrency-shaped precedent in the repo is
`THEMolCollection`'s per-pid lazy handle (`src/molhub/dataset/themol.py:149-161`:
`__getstate__` drops the handle and the pid, `_h5()` reopens when
`os.getpid()` changes), and that discipline is adopted verbatim.

`PrepareWorkers(runner, *, workers, mp_context=None)`:

- `runner` is any object with `run(job) -> outcome` (a `Protocol` seam). It
  crosses the process boundary by pickling, so it **must** drop live handles in
  `__getstate__` and re-materialize them per pid. `-03`'s `THEMolUnitEncoder` is
  the production runner; unit tests use a fake with the same discipline.
- `mp_context` defaults to `multiprocessing.get_context("spawn")`. Spawn is the
  default because forking a process that holds an open HDF5 file or a torch
  runtime is a known corruption path, and the runner is required to be picklable
  anyway. Tests inject `get_context("fork")` to stay fast; one test asserts the
  default is spawn.
- `submit(job)` / `collect(*, timeout)` / `close()` / context-manager support.
  No `run_all()`: composing submit-collect loops is the caller's job.

### 6. `CoverageReport` and `ReadyBlocks` — the reporting surface

Both answer "what does the consumer get to see" — one over time, one right now —
which is what makes them one module.

`CoverageReport.replay(records, *, units_by_block)` folds `-01`'s record stream
into a frozen report: `blocks_seen` (reached READY), `blocks_consumed`,
`units_seen`, `bytes_downloaded` (Σ over DOWNLOADING records, so a retried fetch
counts twice — it measures network bytes honestly), `bytes_prepared` (Σ over
READY), `bytes_evicted` (Σ over REMOTE records that follow a READY record for
the same **derived** block — `BlockId.split is not None`; the initial REMOTE
registration is not a deletion), `bytes_raw_released` (Σ over REMOTE records
following READY for **raw** blocks — `BlockId.split is None` — i.e. raw shards
deleted after their prepare consumed them, the I3 reclaim), and
`timeline`, a tuple of `CoveragePoint(at, blocks, units)` cumulative at each
CONSUMED record. `fraction(total_blocks)` is consumed over corpus. `units_by_block`
is a plain `Mapping[BlockId, int]` supplied by the caller from `-02`'s roster —
no protocol, no coupling, trivially fakeable. Partial coverage is legitimate;
unreported coverage is not (I10).

`ReadyBlocks(tier)` is the **torch-free sampler handoff**. It walks the blocks
tier and parses each sealed `manifest.json` with stdlib `json`;
`metadata() -> tuple[BlockMetadata, ...]` returns, per block: `block_id`, `root`,
`split`, `units`, `frames` (`rows["frame"]`), `task_names`, `column_digests`,
`block_digest`. Those are exactly the fields the molnex-side successor needs to
build a `TaskMixtureBatchSampler` behind `BatchSamplerSource`
(`molnex:src/molix/batch/sampler.py:267`, `:811`) — split selection, plan slots,
group granularity, mixture keys, provenance pin — **without opening one column**.
Constructing that sampler stays `streaming-data-tiers-04-scheduler-integration`'s
job in molnex; this spec only guarantees the surface is sufficient.

Refusals are part of the contract: an unsealed manifest raises `BlockNotSealed`
(READY is conjunctive — there is no half-ready state a consumer may read), and a
`format`/`schema_version` other than `molix.block/1` / `1` raises
`UnsupportedBlockFormat` rather than mis-reading a future layout.

**Digests are copied, never computed.** Per `.claude/notes/notes.md`
§ "版本标识靠 DOI 与钉版本的 locator，不靠 digest", molhub never computes a
digest of its own. `block_digest` and `column_digests` are carried verbatim from
the producer's manifest; column verification is molnex's `BlockReader.verify()`,
transfer verification is `-02`'s `ShardTransfer`. This also keeps `coverage.py`
free of any re-derivation of molnex's canonical-JSON rule, which would be a
cross-repo drift hazard.

### 7. CLI — two verbs on the existing `cache` sub-app

Hung on the `cache` typer sub-app (`src/molhub/cli.py:27`) and shaped like
`cache_verify`'s sweep-then-summary pattern (`src/molhub/cli.py:128-167`):
`--home` with the same defaulting rule, a loop, one summary line, non-zero exit
on trouble.

- `molhub cache status` — one line per tier (`raw`, `blocks`) with entry count,
  resident bytes and budget bytes; a trailing summary. Exits **1** when a tier is
  over its budget on disk, which is the residency invariant failing (I4). Empty
  root prints `No conveyor tiers under <root>.` and exits 0.
- `molhub cache coverage` — replays `-01`'s ledger through `CoverageReport` and
  prints blocks seen / consumed of total (percent), units, and the three byte
  totals. It **requires** `-02`'s roster for the denominator and exits 1 with a
  message when it is absent: a coverage number without the corpus denominator is
  precisely the implicit coverage I10 forbids.

Budgets enter as `--budget-raw` / `--budget-blocks` (bytes), defaulting to the
strategy's ≈ 40 GB per tier, restated in one place with a comment pointing at
`.claude/notes/streaming-data-tiers.md`.

### 8. Naming and style guard

House vocabulary from `.claude/notes/notes.md` § glossary: **"index" means entry
file only** and **"Catalog" is not used for a directory of things**. The visit
plan therefore exposes `position` / `cursor`, the block table stays `-02`'s
`roster`, and nothing here is named `*Index` or `*Catalog`. Otherwise: frozen
dataclasses for value types, `Protocol` seams, keyword-only options, no
`make_*` / `create_*`, one typed exception per distinguishable failure
(`TierError` → `TierOverBudget` / `BlockUnevictable` / `BlockNotResident`;
`QueueError` → `QueueTimeout` / `QueueOversized`; `BlockNotSealed` /
`UnsupportedBlockFormat`), and module docstrings that argue the boundary rather
than restate the code — the register of `src/molhub/dataset/hub.py` and
`src/molhub/sources/blobs.py`.

### Reuse decision

No `librarian_report` accompanied this task, so every verdict below comes from a
direct read of the named file and line.

- `molhub.sources.BlobStore` (`src/molhub/sources/blobs.py:29`, `.root`) —
  **reuse**. `TierStore` takes its root from it, exactly as `DownloadCache` does;
  the `$MOLHUB_HOME` rule is never re-implemented.
- `molhub.dataset.cache.DownloadCache` (`src/molhub/dataset/cache.py:51`) —
  **pattern**. One store, one subdirectory, injected collaborators, `path_for`
  before `fetch`. `TierStore` reads the same way.
- `scripts/build_class1_splits.py:91,167` derived layout + `metadata.json` —
  **generalize** into `DerivedLayout`; the script is repointed at it and keeps
  writing splits. (Task 3 — no parallel implementation.)
- `THEMolCollection.__getstate__` / `_h5` per-pid handle
  (`src/molhub/dataset/themol.py:149-161`) — **pattern** for `PrepareWorkers`'
  runner contract; the repo's only concurrency-shaped precedent.
- `cache_verify` (`src/molhub/cli.py:128-167`) — **pattern** for both verbs:
  sweep, count, one summary line, non-zero exit on an invariant failure.
- `tests/test_sources/test_layering.py` — **pattern** for the AST source-level
  guard; the new guard is its structural twin.
- `-01` `Ledger` / `BlockId` / `BlockState` — **reuse** through the narrow
  `BlockLedger` protocol. No second ledger, no second state enum.
- `-02` `BlockRoster` — **reuse** as the coverage denominator and unit-count
  source. No second block table.
- `-03` `PrepareJob` / `PreparedBlocks` / `THEMolUnitEncoder` — **reuse**;
  `PrepareWorkers` runs them and defines no job type of its own.
- molnex `BlockReader` / `BlockManifest`
  (`molnex:src/molix/store/block.py:572,1176`) — **new — not adopted**: both
  import torch and live in molnex. molhub reads the same `manifest.json` as JSON,
  which is what keeps the handoff torch-free and the reader single-owner.
- `molhub.sources.Digest.of_file` (`src/molhub/sources/digest.py`) — **new — not
  used**: molhub never computes a digest of its own; block digests are copied
  verbatim from the producer.
- `molhub.dataset.neighbor` function-local `molix` import — **pattern** for the
  cross-repo direction only; `conveyor/tier|backpressure|coverage` import molix
  at no depth.

## Files to create or modify

> Paths relative to `/home/jicli594/work/molcrafts/molhub`.

- `src/molhub/conveyor/tier.py` (new) — `TierStore`, `VisitOrder`,
  `DerivedLayout`, `BlockLedger` protocol, `TierError` family
- `src/molhub/conveyor/backpressure.py` (new) — `ByteBoundedQueue`,
  `PrepareWorkers`, `JobRunner` protocol, `QueueError` family
- `src/molhub/conveyor/coverage.py` (new) — `CoverageReport`, `CoveragePoint`,
  `ReadyBlocks`, `BlockMetadata`, `BlockNotSealed`, `UnsupportedBlockFormat`
- `src/molhub/conveyor/__init__.py` — created by `-01-ledger`; re-export this
  spec's public names
- `src/molhub/cli.py` — `cache status` and `cache coverage`
- `scripts/build_class1_splits.py` — repoint onto `DerivedLayout`
- `tests/test_conveyor/test_tier.py` (new)
- `tests/test_conveyor/test_backpressure.py` (new)
- `tests/test_conveyor/test_coverage.py` (new)
- `tests/test_conveyor/test_layering.py` (new)
- `tests/test_cli.py`
- `regressions/streaming-data-tiers-03-conveyor-04-residency.py` (new)

## Tasks

- [ ] Write failing unit tests for `TierStore` and `DerivedLayout` (`tests/test_conveyor/test_tier.py` → `TestTierStore`, `TestVisitOrder`, `TestDerivedLayout`) with a fake `BlockLedger`: admit/release/headroom, on-disk re-derivation at construction, independent budgets, leased and resident-flagged blocks never evicted, pinned plan-ordered eviction sequence, `TierOverBudget` deletes nothing (RED)
- [ ] Implement `TierStore`, `VisitOrder`, the `BlockLedger` protocol and the `TierError` family in `src/molhub/conveyor/tier.py` — one owned subdirectory, root from `BlobStore`, declared-byte budget, `path_for` / `admit` / `release` / `flag_resident` / `evict_until` (plan first, then delete), and the single REMOTE ledger record on deletion
- [ ] Generalize the derived-artifact layout out of `scripts/build_class1_splits.py:91,167` into `DerivedLayout` in `src/molhub/conveyor/tier.py` (`artifact_dir`, atomic `write_metadata`), have `TierStore` hold one for its subdirectory, and repoint the script at it so its four split files and `metadata.json` stay byte-identical
- [ ] Write failing unit tests for `ByteBoundedQueue` and `PrepareWorkers` (`tests/test_conveyor/test_backpressure.py`) — `timeout=0` full/free probes, pinned `held_bytes` trace, `QueueOversized` on an unsatisfiable reservation, event-synchronized bounded-wait wake, fake picklable runner whose `__getstate__` drops its per-pid handle, default context is spawn (RED)
- [ ] Implement `ByteBoundedQueue` and `PrepareWorkers` in `src/molhub/conveyor/backpressure.py` — byte-weighted FIFO with `reserve` / `take` / `release` (bytes freed by deletion, never by dequeue), injectable `mp_context` defaulting to spawn, `JobRunner` protocol and the per-pid handle contract
- [ ] Write failing tests for the reporting surface and the guards: `tests/test_conveyor/test_coverage.py` (`TestCoverageReport` pinned replay counts and timeline, `TestReadyBlocks` metadata fields, unsealed and unsupported-schema refusals, digests copied verbatim), `tests/test_conveyor/test_layering.py` (AST guard, per `tests/test_sources/test_layering.py`), and the `cache status` / `cache coverage` cases in `tests/test_cli.py` (RED)
- [ ] Implement `CoverageReport`, `CoveragePoint`, `ReadyBlocks` and `BlockMetadata` in `src/molhub/conveyor/coverage.py` using stdlib `json` only, re-export this spec's public names from `src/molhub/conveyor/__init__.py`, and write the three module docstrings ac-015 binds (tier.py: declared-bytes budget + plan-before-delete; backpressure.py: processes + spawn default; coverage.py: digests-copied-never-computed citing .claude/notes/notes.md + the metadata.json vs manifest.json boundary)
- [ ] Implement the `cache status` and `cache coverage` verbs in `src/molhub/cli.py` on the existing `cache` sub-app, shaped like `cache_verify` (`--home`, per-tier lines, summary line, exit 1 on an over-budget tier or a missing roster)
- [ ] Add regression example `regressions/streaming-data-tiers-03-conveyor-04-residency.py` (public API only; hard-coded goldens, no third-party runtime)
- [ ] Run full check + test suite

## Testing strategy

Unit tests only under `tests/`, mirroring `src/molhub/conveyor/`
(`tier.py` → `test_tier.py`, `backpressure.py` → `test_backpressure.py`,
`coverage.py` → `test_coverage.py`), types mirrored (`TierStore` →
`TestTierStore`). One function or method per test; fakes only — no network, no
real ledger, no real block reader, seconds at most.
`tests/test_conveyor/__init__.py` comes from `-01-ledger`; fakes stay inline in
the module that uses them (each is used by one module's tests), per
"inline until the second real use".

**`test_tier.py`** — `admit` returns a path under the store's own subdirectory
and refuses over budget; residency re-derived from disk at construction (write a
file of known size, assert `resident_bytes`); `release` frees bytes and deletes;
`release`/`evict_until` refuse a leased block (`BlockUnevictable`) and a
resident-flagged block; the eviction order rule (not-in-plan → behind ascending →
ahead descending → `BlockId` tiebreak) asserted as an exact tuple; infeasible
`evict_until` raises `TierOverBudget` with `resident_bytes` and the entry set
unchanged; two stores with different budgets do not see each other's entries;
exactly one REMOTE record is appended per deletion and none on `admit`.
`TestDerivedLayout`: `artifact_dir` shape, atomic `write_metadata` byte output,
missing `generator` rejected.

**`test_backpressure.py`** — `reserve`/`take`/`release` `held_bytes` trace;
`take` does not free bytes; `timeout=0` raises `QueueTimeout` when full and
succeeds after `release`; `QueueOversized` raised without blocking; the one
threaded wake test (Event handshake + `join(timeout=5)`, no `time.sleep`);
`PrepareWorkers` default context is spawn, an injected `fork` context runs a fake
runner end to end, the fake runner's `__getstate__` drops its handle and `run`
re-opens on a new pid.

**`test_coverage.py`** — `CoverageReport.replay` over a hand-built record stream:
`bytes_downloaded` counts a retried fetch twice, `bytes_prepared`,
`bytes_evicted` counts only a REMOTE that follows a READY, `blocks_seen` /
`blocks_consumed` ordering, `units_seen`, cumulative `timeline`, `fraction`.
`ReadyBlocks.metadata()` over hand-written fixture `manifest.json` files:
every named field, `frames` read from `rows["frame"]`, digests identical to the
file's bytes (never recomputed), `BlockNotSealed` on `sealed: false`,
`UnsupportedBlockFormat` on `schema_version: 2`.

**`test_layering.py`** — AST source-level guard, the structural twin of
`tests/test_sources/test_layering.py`: (a) no **module-level** `torch` / `molix` /
`molrs` import in any file under `src/molhub/conveyor/` (function-local imports
stay legal, which is how `-03`'s optional `prepare` extra works); (b) no such
import at **any** depth in `tier.py`, `backpressure.py`, `coverage.py`.

**`tests/test_cli.py`** — `cache status` prints one line per tier with entries,
resident and budget bytes; exits 1 when a tier is over budget; prints the
empty-root message otherwise. `cache coverage` prints the counts and percentage
against a fixture roster and exits 1 with a message when no roster is present.

**Regression example** — `regressions/streaming-data-tiers-03-conveyor-04-residency.py`,
public API only, hard-coded goldens, no third-party oracle at runtime:

1. Five fake block directories with hand-written sealed manifests; blocks tier
   budget 3 000 000 B, raw tier budget 2 000 000 B, declared 1 000 000 B each.
2. Admit `b00`,`b01`,`b02`; `b00`,`b01` CONSUMED, `b02` READY and leased;
   `VisitOrder((b00..b04), cursor=2)`. `evict_until(1_000_000)` → **`("b00",)`**,
   `resident_bytes == 2_000_000`.
3. Admit `b03`; `flag_resident("b01")`; `evict_until(1_000_000)` → raises
   `TierOverBudget`, `resident_bytes` still **3 000 000** and all three resident
   entries (`b01`, `b02`, `b03`) still on disk (leased and flagged blocks
   survive; nothing partially deleted).
4. Release `b02`'s lease, mark it CONSUMED, cursor → 3; `evict_until(1_000_000)`
   → **`("b02",)`**. Admit `b04`. Peak blocks-tier residency never exceeds
   **3 000 000 B**; the raw tier stays at **2 000 000 B** throughout and loses no
   entry to blocks-tier pressure; releasing a raw shard after its block is READY
   drops it to 1 000 000 B (I3).
5. Queue capacity 2 000 000: `held_bytes` trace
   **(1 000 000, 2 000 000, 2 000 000, 2 000 000, 1 000 000, 2 000 000)** across
   reserve, reserve, refused `timeout=0` reserve, `take`, `release`, reserve;
   a 3 000 000 B reservation raises `QueueOversized`.
6. `CoverageReport.replay` over the ledger the run actually wrote:
   `bytes_downloaded == 5_000_000`, `bytes_prepared == 5_000_000`,
   `bytes_evicted == 2_000_000` (derived blocks `b00`, `b02`),
   `bytes_raw_released == 1_000_000` (the raw shard released in step 4 —
   split=None, so it counts here, not in bytes_evicted), `blocks_seen` = the
   five ids,
   `blocks_consumed == ("b00", "b01", "b02")`, `units_seen == 12`,
   `fraction(8) == 0.375`, cumulative timeline `((1, 3), (2, 5), (3, 8))`.
   Timestamps are asserted monotone, never pinned to a literal.
7. `ReadyBlocks(...).metadata()` for `b03`: `split == "train"`, `units == 2`,
   `frames == 8`, `task_names == ("equilibrium", "torsion")`, `block_digest`
   equal to the literal in the fixture manifest.

## Out of scope

- **Block state, transfers, prepare semantics** — `-01-ledger`, `-02-roster`,
  `-03-prepare` own `BlockId` / `BlockState` / `Ledger` / lease TTL semantics,
  `BlockRoster` / `ShardTransfer` / digest-at-the-boundary (I6), and
  `PrepareJob` / `PreparedBlocks` / `THEMolUnitEncoder`. This spec consumes them.
- **Sampler construction** — building `TaskMixtureBatchSampler` or anything
  behind `BatchSamplerSource` is `streaming-data-tiers-04-scheduler-integration`
  in molnex. Here only the metadata surface is guaranteed sufficient.
- **The block format** — `molix.block/1` is molnex's (`-02-block-format`);
  molhub reads its `manifest.json` and never writes, verifies or re-derives it.
- **Multi-node lease visibility and writer election** — leases are
  single-filesystem here, as `-01` defined them; the single-writer discharge is
  §1b's single-driver operating mode. Cross-node coordination is the named
  future spec `streaming-data-tiers-05-multinode`, not a flag.
- **Throughput measurement** — no `B_net` or `c_prep` number is asserted or
  calibrated; the strategy's rate condition is design input, and any production
  submission remains gated by `molnex:.claude/notes/production-training-checklist.md`.
- **Any training or download run** — every test and the regression use fakes on
  a temp directory; nothing here touches the network.
- **Chain registration** in `.claude/specs/INDEX.md` — done once for the whole
  `-03-conveyor` chain by the caller, not per sub-spec.
- **`pyproject.toml` changes** — the pool is stdlib `multiprocessing`; the
  optional `prepare` extra belongs to `-03`.
