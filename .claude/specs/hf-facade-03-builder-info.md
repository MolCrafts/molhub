---
title: Builder and info — HF-shaped name resolution, content-first DatasetInfo, map-style load_dataset(split=...)
status: approved
grilled: true
slug: hf-facade-03-builder-info
repo: molhub
chain: hf-facade (01-meta-dissolution → 02-frame-records → 03-builder-info → 04-streaming-prepare)
created: 2026-08-15
---

# Builder and info — HF-shaped name resolution, content-first DatasetInfo, map-style load_dataset(split=...)

> Third sub-spec of the `hf-facade` chain; depends on `01` + `02` (records are
> `Frame`/`Trajectory`, meta is `frame.meta`). Governing basis: complaints
> (1) 「用户怎么知道shard-000是什么东西」 and (3) 「SplitTable习惯不好，和
> pytorch用法对齐」, under the recorded operator override. **Scope of the
> façade sanction:** `load_dataset` / `load_dataset_builder` are free functions
> permitted ONLY in `src/molhub/loader/` and ONLY as thin delegations to
> constructed types; nothing under `sources/`, `dataset/` or `conveyor/` gains
> a free function, a `make_*`, or a context blob.

## Summary

A new `molhub.loader` package gives molhub the HuggingFace spelling:
`load_dataset_builder("themol/mbis").info` describes content (features,
splits, counts, citation) with no shard role anywhere, and
`load_dataset("themol/mbis", split="train", revision="1")` returns a map-style
dataset whose records are the `Frame`/`Trajectory` of sub-spec 02. Split
becomes an argument; `SplitTable` becomes internal.

## Design

New package `src/molhub/loader/` sits **above** `dataset/` and `conveyor/`
(both of which it imports; neither may import it — enforced by a layering test
following `tests/test_conveyor/test_layering.py`). Five modules, one
responsibility each:

- `naming.py` — `DatasetName` (D4 resolution): `"themol/mbis"` →
  `Coordinate(kind="dataset", namespace="themol", name="mbis",
  version=<revision>)`. `revision` is HF spelling for the coordinate's
  `@version` — **not** a git sha. Default = newest declared version in the
  registry under a numeric-aware natural sort over the version string; if an
  artifact's versions do not order unambiguously, the loader **refuses and
  demands an explicit `revision=`** (a silently-picked version breaks the
  「locator 必须钉版本」 promise). The resolved coordinate is echoed on
  `DatasetInfo.coordinate` so a run can record what it actually read.
- `info.py` — `DatasetInfo`, `SplitInfo`, `Feature` (frozen dataclasses;
  `Feature.level ∈ {atom, meta, block}`; `SplitInfo(name, num_examples,
  provenance)` where provenance is the human sentence derived from
  `_SplitTable.provenance` or the dataset's declared rule).
  **Feature data source (corrected 2026-08-15 after spec-audit —
  `TargetSchema` carries neither units nor a level enum):** `Feature.level`
  derives from which declaration set a name sits in (`atom_level` → `atom`,
  `graph_level` → `meta`, and a NEW optional `blocks` declaration → `block`);
  `Feature.units` comes from a NEW optional `units: Mapping[str, str]` field on
  the `@dataset` declaration (`DatasetManifest` in
  `src/molhub/dataset/definition.py` — a **generalize**, defaulting to empty:
  a dataset that declares no units renders `units=""`). THEMol adapters
  declare from the existing `THEMOL_UNITS` dict; `TargetSchema` itself is
  untouched.
- `builder.py` — `DatasetBuilder(name, *, revision=None, registry=None,
  hub=None)` with `.info` and `.split_view(split)`.
- `mapstyle.py` — `SplitDataset` satisfying `molhub.dataset.protocol.Dataset`;
  `ShardIndex` implementing D6's lazy memoized per-shard index over
  `DerivedLayout`.
- `__init__.py` — the two sanctioned free functions, thin delegations only.

**D5 — `split` is required.** `load_dataset(name, split=...)` takes `split` as
a required keyword. Returning a dict-of-splits when it is omitted would either
introduce a new container type (forbidden by complaint 2) or make `ds[0]` mean
different things depending on an argument. Discovery is
`load_dataset_builder(name).info.splits`.

**D6 — split resolution mechanics (eager vs lazy, costed).** Two split
flavours behind one `DatasetInfo.splits`:

- *declared* (water-les tail slice, 3BPA's four tags, zinc `splits.json`,
  phalkethoh): the dataset class already owns it; the builder delegates to the
  existing constructor. Three of the four take `split=` directly;
  **`ThreeBPADataset` takes `tag=` with a required positional `path`** — the
  builder's delegation table therefore carries a per-dataset adapter entry
  (`split → tag`, path resolved through the hub), not a uniform
  `Ctor(split=split)` dispatch. [Corrected 2026-08-15 after spec-audit.]
  Counts are exact and free.
- *table-backed* (THEMol via `class1-universal-splits@1` at
  `$MOLHUB_HOME/derived/molcrafts/class1-universal-splits/1/`): `len(ds)`
  comes from `_SplitTable.counts()[split]` — one gz CSV load (mbis ≈ 1.5 M
  rows), memoized per process, **zero shard bytes**.

`ds[i]` needs record→shard, which no published artifact states. Decision:
**lazy per-shard index, memoized on disk; never an eager whole-dataset index.**
An eager index would require every shard local (≈150 GB for mbis, 6.5 TB for
THEMol) — precisely invariant I1/I3 of the tiers strategy. The lazy index is
built per shard from `THEMolShardDataset`'s already-listed group keys
(O(records), sub-second once the file is local) and written under
`DerivedLayout` (reused, not re-invented). Consequence, stated to the user in
`DatasetInfo`: *a map-style view fetches the shard owning the row you ask for,
plus every earlier shard not yet indexed* — sequential access walks shards in
order; random access to a late row is expensive. This is HF's own
`load_dataset` semantic (it downloads), just charged honestly.

The index build assumes shard HDF5 group keys live in the uuid tables' key
space. It **asserts** this on the first key and raises `UnknownRecordKey`
naming both key spaces on a miss — no runtime fallback, no guessing. The
declared alternative, selected by the builder's `key_space` declaration rather
than discovered at runtime, is: read each group's `mapped_isomeric_smiles` →
`THEMolUnitEncoder.identity` → `identity_splits.csv.gz` (one tiny string read
per group, ≈50 k per shard, seconds).

**D9 — `SplitTable` internalization.** Renamed `_SplitTable` in
`src/molhub/conveyor/splits.py` and dropped from `molhub.conveyor.__all__`.
Provenance verification, the literal filename table and the two alternate
constructors are unchanged — only the export goes.

**Reuse decision.**
- `Registry` — **generalize**: add `versions(unversioned)`; the sibling-version
  scan already exists privately at `registry.py:131-142` and is promoted rather
  than duplicated.
- `SplitTable` — **generalize**: rename to `_SplitTable`, consumed by loader +
  prepare stage — one table implementation, two callers.
- `Coordinate`, `Molhub.fetch`, `ArtifactHub`, `Datasets`/`@dataset`/
  `DatasetManifest`, `TargetSchema`, `Manifest.targets`, `DerivedLayout`,
  `THEMolShardDataset`, `protocol.Dataset`/`SubsetDataset` — **reuse**.
- `DatasetName` — **new**: `Coordinate.parse` requires `@version`; defaulting
  the revision from the registry is a distinct responsibility that must not be
  smuggled into `Coordinate`.
- `DatasetInfo`/`SplitInfo`/`Feature` — **new**: nothing today describes
  content (`Manifest` describes bytes and roles, `TargetSchema` describes
  target layout; neither answers "what does a record look like and how many
  are there").
- `SplitDataset` / `ShardIndex` — **new**: no existing type answers "the i-th
  record of split X"; each is single-responsibility and constructed, not
  factory-made.

## Files to create or modify

- `src/molhub/loader/__init__.py` (new)
- `src/molhub/loader/naming.py` (new)
- `src/molhub/loader/info.py` (new)
- `src/molhub/loader/builder.py` (new)
- `src/molhub/loader/mapstyle.py` (new)
- `src/molhub/registry.py`
- `src/molhub/dataset/definition.py` (optional `units` + `blocks` declaration fields — generalize)
- `src/molhub/conveyor/splits.py`, `src/molhub/conveyor/roster.py` (imports/annotations follow the rename), `src/molhub/conveyor/__init__.py`
- `src/molhub/__init__.py`
- `tests/test_loader/__init__.py`, `test_naming.py`, `test_info.py`,
  `test_builder.py`, `test_mapstyle.py`, `test_layering.py` (all new)
- `tests/test_registry.py`, `tests/test_conveyor/test_splits.py`
- `docs/reference/python.md`
- `regressions/hf-facade-03-builder-info.py` (new)

## Tasks

- [ ] Write failing unit tests for name and revision resolution (`tests/test_loader/test_naming.py` → `TestDatasetName`): shorthand, explicit revision, newest-by-default, ambiguous-version refusal
- [ ] Implement `DatasetName` in `src/molhub/loader/naming.py` and `Registry.versions` in `src/molhub/registry.py`
- [ ] Write failing unit tests for content-first description (`tests/test_loader/test_info.py` → `TestDatasetInfo`, `TestSplitInfo`) including the assertion that no role name appears in any field
- [ ] Implement `DatasetInfo`, `SplitInfo` and `Feature` in `src/molhub/loader/info.py` from the manifest, the declaration sets (atom_level→atom, graph_level→meta, new blocks→block) and the split source, and add the optional `units` + `blocks` fields to `DatasetManifest` in `src/molhub/dataset/definition.py` with THEMol declaring from `THEMOL_UNITS`
- [ ] Write failing unit tests for map-style split views over a fake `ArtifactHub` and a synthetic split table (`tests/test_loader/test_mapstyle.py` → `TestSplitDataset`, `TestShardIndex`)
- [ ] Implement `DatasetBuilder` in `src/molhub/loader/builder.py` and `SplitDataset` / `ShardIndex` in `src/molhub/loader/mapstyle.py`
- [ ] Expose `load_dataset` and `load_dataset_builder` in `src/molhub/loader/__init__.py` and `src/molhub/__init__.py` (incl. the ac-003 tests: split required keyword → TypeError when omitted; no DatasetDict-like container), with a layering test in `tests/test_loader/test_layering.py`
- [ ] Rename `SplitTable` to `_SplitTable` in `src/molhub/conveyor/splits.py`, drop it from `molhub.conveyor.__all__`, and follow through in `src/molhub/conveyor/roster.py` (import + `splits:` annotation + the prepare.py docstring cross-reference) and `tests/test_conveyor/{test_splits,test_roster}.py` (scripts/build_class1_splits.py imports no SplitTable — verified, nothing to change there)
- [ ] Add regression example `regressions/hf-facade-03-builder-info.py` (public API only; hard-coded goldens, no third-party runtime)
- [ ] Run full check + test suite

## Testing strategy

Unit tests mirror the new package and run green on their own path with fakes
only (`uv run pytest tests/test_loader/test_naming.py -v`).

- `TestDatasetName`: `"themol/mbis"` → `dataset:themol/mbis@1` against a
  two-manifest fake registry; `revision="1"` honoured; a registry holding `1`
  and `2` resolves to `2`; a registry holding `v2` and `beta` raises naming
  both.
- `TestDatasetInfo`: features derived from `TargetSchema` carry level and
  units; `splits` counts come from the injected split table; a literal
  assertion that `"shard-"` occurs in no rendered field.
- `TestSplitDataset`: `len()` equals the injected table's train count without
  any fetch (assert the fake hub recorded zero calls); `ds[0]` returns the
  first train record; a row whose owning shard is not indexed triggers exactly
  one fetch; `UnknownRecordKey` is raised when a group key is outside the
  table's key space.
- `TestShardIndex`: the memoized index is written once under a `tmp_path`
  `DerivedLayout` and reused on a second construction.
- `test_layering.py` asserts no module under `src/molhub/dataset/` or
  `src/molhub/conveyor/` names `molhub.loader`.

Regression `regressions/hf-facade-03-builder-info.py` builds a temporary
registry + fake hub + synthetic shard and split table, then asserts hard-coded
`info.splits` counts, the resolved coordinate string and `ds[0]`'s meta.

## Out of scope

- Streaming and `prepare` (sub-spec 04). CLI changes (04).
- Any change to which datasets exist. Caching decoded records.
- `Dataset.map` / `filter` / `shuffle` / `with_format` — composition is the
  caller's job; only `__len__`/`__getitem__`/`__iter__`/`take` exist.
- No Arrow/parquet, no `datasets`-library dependency, no loading scripts, no
  hub upload, no registry content change, no TS/Web parity.
