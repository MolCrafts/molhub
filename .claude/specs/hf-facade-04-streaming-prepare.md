---
title: Streaming and prepare — bounded-disk IterableDataset over the conveyor, save_to_disk-shaped materialization, content-first CLI info
status: approved
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
`molhub.dataset.protocol.IterableDataset`, plus `.take(n)` in HF spelling),
composing, per shard in manifest role order (D7):
`ShardTransfer.transfer(block)` (digest re-verified, lease taken, ledger
written) → open the shard → iterate keys in shard order → look up the split →
yield only matching `Frame`/`Trajectory` → release the lease →
`TierStore.evict_until` before admitting the next. Disk is bounded by
`TierStore`'s budget, defaulting to the 40 GB already spelled in
`src/molhub/cli.py`. `.take(n)` bounds the walk and releases early.

**`materialize.py` — `BlockExport` + the `prepare` entry** (D8): `prepare(name,
*, split, output_dir, ...)` composes streaming walk → `THEMolUnitEncoder` →
`PrepareJob(writer_factory=MolnexBlockWriter, root=output_dir)` and returns the
existing `PreparedBlocks`. It adds no new orchestration type, keeps
`PrepareJob`'s single-shot and provenance rules untouched, and keeps molnex's
import lazy (Option A ruling). The cross-repo seam remains a block directory on
disk; molnex's `BlockDataset.load_from_disk(output_dir)` is the consuming
spelling (a named follow-up in the molnex repo — this chain only guarantees the
directory it reads). The writer factory is injected, so unit tests use a fake
and the base install never needs torch.

**CLI.** `molhub info` prints description, features, splits + counts and an
example record shape first; roles, digests and locators move behind `--files`,
reusing `_resolve` and the existing `Molhub` construction.

**Reuse decision.**
- `ShardTransfer`, `TierStore`, `Ledger`, `BlockRoster`, `BlockId`,
  `DerivedLayout`, `PrepareJob`, `MolnexBlockWriter`, `PreparedBlocks`,
  `THEMolUnitEncoder`, `_SplitTable`, `protocol.IterableDataset`,
  `cli._resolve`, the CLI's default budget constant — **reuse**, all unchanged.
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
- `src/molhub/__init__.py`
- `tests/test_loader/test_streaming.py` (new), `tests/test_loader/test_materialize.py` (new)
- `tests/test_cli.py`
- `docs/reference/python.md`, `docs/guides/finding-and-fetching.md`
- `regressions/hf-facade-04-streaming-prepare.py` (new)

## Tasks

- [ ] Write failing unit tests for the streaming walk, split filter, byte bound and `.take` (`tests/test_loader/test_streaming.py` → `TestStreamingSplitDataset`)
- [ ] Implement `StreamingSplitDataset` in `src/molhub/loader/streaming.py` composing `ShardTransfer`, `TierStore` and `Ledger` behind the iterator
- [ ] Wire `streaming=True` through `load_dataset` and `DatasetBuilder` in `src/molhub/loader/{__init__,builder}.py`
- [ ] Write failing unit tests for `BlockExport` against an injected fake block writer (`tests/test_loader/test_materialize.py` → `TestBlockExport`)
- [ ] Implement `BlockExport` and the `prepare(...)` entry in `src/molhub/loader/materialize.py` over `PrepareJob` and `MolnexBlockWriter`
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
