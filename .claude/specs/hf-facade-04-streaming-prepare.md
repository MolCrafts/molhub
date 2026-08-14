---
title: Streaming and prepare — bounded-disk IterableDataset over the conveyor, save_to_disk-shaped materialization, content-first CLI info
status: approved
grilled: true
slug: hf-facade-04-streaming-prepare
repo: molhub
chain: hf-facade (01-meta-dissolution → 02-frame-records → 03-builder-info → 04-streaming-prepare)
created: 2026-08-15
---

# Streaming and prepare — bounded-disk IterableDataset over the conveyor, save_to_disk-shaped materialization, content-first CLI info

> Last sub-spec of the `hf-facade` chain; depends on `01`–`03`. Governing
> basis: complaint (4) 「conveyor用法太怪/跨仓API看不懂，直接抄huggingface」,
> under the recorded operator override. The conveyor's vocabulary (BlockId,
> BlockState, ledger, tiers, leases) must appear in no signature, no return
> value and no error message on the user path.

## Summary

`load_dataset(..., streaming=True)` returns an `IterableDataset` that walks
shards in order under a byte budget with the ledger, tiers and transfer
machinery entirely invisible, and `molhub.prepare(...)` materializes a split
into a molnex-readable block directory. `molhub info` becomes content-first,
with file roles demoted behind `--files`.

## Design

Two new loader modules.

**`streaming.py` — `StreamingSplitDataset`** (satisfies
`molhub.dataset.protocol.IterableDataset`, plus `.take(n)` in HF spelling).

**D7 (revised 2026-08-15 after spec-audit — the original sketch had two
coherence holes: TierStore's accounting was disconnected from where Fetcher
actually lands bytes, and the raw shard never reached CONSUMED so
`evict_until` could never evict anything).** A linear streaming walk does not
need plan-ordered eviction; it needs exactly "delete the previous shard's
bytes after use, refuse the next shard if it would break the budget". So
`TierStore` is **not** in the streaming path — the walk owns a simple bounded
residency rule directly over the real byte locations:

Per shard, in manifest role order:
1. Budget check: `block.size` + bytes of any still-open shard must fit the
   byte budget (keyword `disk_budget`, default the 40 GB constant promoted
   from `src/molhub/cli.py`); a single shard larger than the budget refuses
   with an actionable message.
2. `ShardTransfer.transfer(block)` — digest re-verified, lease taken,
   DOWNLOADING written. The returned path IS the real byte location
   (`$MOLHUB_HOME/files/<coordinate>/<role>`, Fetcher's cache).
3. `ledger.append(block, READY)` — verified local bytes (the raw-shard READY
   semantics established by the conveyor chain).
4. Open the shard (`THEMolShardDataset`), iterate keys in shard order, look up
   the split, yield only matching `Frame`/`Trajectory`.
5. On exhaustion (or early `.take` exit): close the reader handle FIRST, then
   `ledger.append(block, CONSUMED)`, then **unlink the fetched cache file**
   (the rolling-tier delete — re-visiting a shard later re-fetches, by
   design), then `ledger.append(block, REMOTE)` and release the lease. Bytes
   reclaim when the handle is closed; the walk never deletes under an open
   handle.

The ledger is the canonical one: its path is the `<home>/conveyor/ledger.jsonl`
constant currently private to the CLI (`_LEDGER_SEGMENTS`), promoted to a
shared `molhub.conveyor` accessor so the CLI's `cache coverage` and the
streaming walk read/write the same file — two different default paths would
silently desynchronize leases (the ledger's own R1 note). `.take(n)` bounds
the walk; early exit runs step 5 at the point of exit (handle closed before
any delete), so a mid-shard stop is safe. Single-process streaming is the v0
contract (same as the conveyor driver); concurrent readers of a shard being
retried are out of contract and the lease is what prevents them within the
conveyor's own callers.

**`materialize.py` — `BlockExport` + the `prepare` entry** (D8, revised
2026-08-15 after spec-audit — the original "streaming walk → encoder →
PrepareJob" was contradictory on split handling). The resolution has three
legs, each verified against the landed contracts:

- *Type alignment*: after `hf-facade-02`, `THEMolShardDataset` yields
  `Frame`/`Trajectory` and `THEMolUnitEncoder.encode` dispatches on exactly
  those — so the streaming walk's output type IS the encoder's input type.
  (04 depends on 02; this is why the chain is ordered.)
- *Single-split materialization without double routing*: `prepare(name, *,
  split, output_dir)` feeds `PrepareJob` the **split-filtered** walk (only
  records whose identity maps to the target split arrive) together with the
  **full** `split_of` mapping. `PrepareJob` opens writers lazily on the first
  unit of a split, so only the target split's writers ever open, `output_dir`
  contains only that split's roots, and `UnroutableUnitError` still fires for
  an identity genuinely absent from the table (out-of-split identities never
  arrive, so they cannot trip it). No PrepareJob change; no double handling.
- *Fail-closed message (ac-005)*: `BlockExport` — not `MolnexBlockWriter`,
  which stays reuse-unchanged — wraps its default writer-factory resolution in
  `try/except ImportError`, re-raising with a message that names the `prepare`
  extra and the `MOLNEX_SRC` escape hatch, BEFORE any directory is created.
  The bare `ModuleNotFoundError` from a missing torch/molix never reaches the
  user.

`prepare` returns the existing `PreparedBlocks`; the cross-repo seam remains a
block directory on disk; molnex's `BlockDataset.load_from_disk(output_dir)` is
the consuming spelling (a named follow-up in the molnex repo). The writer
factory is injected, so unit tests use a fake and the base install never needs
torch.

**CLI.** `molhub info` prints description, features and splits + counts first
— sourced from `hf-facade-03`'s `DatasetBuilder.info` (the content authority),
not from a second Manifest-only rendering; roles, digests and locators move
behind `--files` (the Manifest view, reusing `_resolve`). The "example record
shape" idea is dropped: producing a real record would require fetching shard
bytes, and `info` staying fetch-free is a feature. [Revised 2026-08-15 after
spec-audit: the original wording had no data source for features/splits and
implied opening data.]

**Reuse decision.**
- `ShardTransfer`, `Ledger`, `BlockRoster`, `BlockId`, `PrepareJob`,
  `MolnexBlockWriter`, `PreparedBlocks`, `THEMolUnitEncoder`, `_SplitTable`,
  `protocol.IterableDataset`, `cli._resolve` — **reuse**, all unchanged.
- The CLI's ledger-path and budget constants — **generalize**: promoted to a
  shared `molhub.conveyor` accessor (`default_ledger_path(home)`) and a shared
  budget constant so the CLI and the streaming walk cannot desynchronize.
- `TierStore` — **not used on the streaming path** (revised): its plan-ordered
  eviction serves the full conveyor driver; a linear walk's residency rule is
  delete-after-consume + budget-check-before-fetch, owned by
  `StreamingSplitDataset` directly over the real cache paths. `cache status`
  keeps reporting TierStore tiers unchanged.
- `StreamingSplitDataset`, `BlockExport` — **new**: nothing today walks shards
  under a bound or exports a split.
- `prepare` free function — **new, sanctioned by the operator override only**,
  a thin delegation to `BlockExport`.

## Files to create or modify

- `src/molhub/loader/streaming.py` (new)
- `src/molhub/loader/materialize.py` (new)
- `src/molhub/loader/__init__.py`
- `src/molhub/loader/builder.py`
- `src/molhub/cli.py`
- `src/molhub/conveyor/__init__.py` (promote default_ledger_path + budget constant)
- `src/molhub/__init__.py`
- `tests/test_loader/test_streaming.py` (new), `tests/test_loader/test_materialize.py` (new)
- `tests/test_cli.py`
- `docs/reference/python.md`, `docs/guides/finding-and-fetching.md`
- `regressions/hf-facade-04-streaming-prepare.py` (new)

## Tasks

- [ ] Write failing unit tests for the streaming walk, split filter, byte bound, the full raw-shard ledger lifecycle, the vocabulary-leak assertions (ac-003) and `.take` incl. mid-shard early exit with handle-closed-before-delete (`tests/test_loader/test_streaming.py` → `TestStreamingSplitDataset`)
- [ ] Implement `StreamingSplitDataset` in `src/molhub/loader/streaming.py` composing `ShardTransfer` and the canonical `Ledger` behind the iterator, with the revised D7 lifecycle (READY after verify, CONSUMED after exhaustion, unlink the real cache file handle-closed-first, REMOTE after delete) and the promoted ledger-path/budget constants
- [ ] Wire `streaming=True` through `load_dataset` and `DatasetBuilder` in `src/molhub/loader/{__init__,builder}.py`
- [ ] Write failing unit tests for `BlockExport` against an injected fake block writer (`tests/test_loader/test_materialize.py` → `TestBlockExport`)
- [ ] Implement `BlockExport` and the `prepare(...)` entry in `src/molhub/loader/materialize.py` over `PrepareJob` and `MolnexBlockWriter` (split-filtered walk + full split_of; try/except ImportError naming the prepare extra and MOLNEX_SRC before any mkdir — the ac-005 wording is BlockExport's responsibility)
- [ ] Write failing CLI tests for the content-first `info` and the `--files` flag (`tests/test_cli.py` → `TestInfo`)
- [ ] Render features, splits and an example record first, and file roles only under `--files`, in `src/molhub/cli.py`
- [ ] Document the HF-shaped surface with executable fences in `docs/reference/python.md` and `docs/guides/finding-and-fetching.md`
- [ ] Add regression example `regressions/hf-facade-04-streaming-prepare.py` (public API only; hard-coded goldens, no third-party runtime)
- [ ] Run full check + test suite

## Testing strategy

- `TestStreamingSplitDataset`: with a fake hub serving two synthetic shards and
  an injected split table, iteration yields exactly the train records in shard
  order (literal ids); `.take(3)` yields three and stops; resident bytes never
  exceed the injected `TierStore` budget (assert after each yield); a shard is
  released before the next is admitted; no `BlockId`, `BlockState` or ledger
  object appears in any yielded value or raised message (assert on the
  exception text).
- `TestBlockExport`: with a fake `BlockWriterFactory`, one export produces one
  sealed root per split fan-out and returns a `PreparedBlocks` whose
  `unit_count`/`frame_count` match literals; missing provenance still raises
  `IncompleteProvenanceError`; a missing molnex still raises `ImportError` with
  the `prepare`-extra message.
- `TestInfo`: `molhub info themol/mbis` prints features and splits and does
  **not** print `shard-000`; `molhub info themol/mbis --files` does.
- Docs fences are executed by the existing `tests/test_docs_examples.py`, so
  every new fence carries an explicit test directive or a stated skip reason.

Regression `regressions/hf-facade-04-streaming-prepare.py` runs a bounded
streaming walk over synthetic shards and one `prepare` into a temporary
directory with a fake writer, asserting hard-coded record ids, counts and
sealed-block metadata.

## Out of scope

- molnex's `BlockDataset.load_from_disk` (named follow-up in the molnex repo).
- Multi-process or prefetching streaming (`PrepareWorkers` / `ByteBoundedQueue`
  stay where they are).
- Resuming an interrupted `prepare` from the ledger.
- Any TypeScript/CLI parity beyond `info`.
