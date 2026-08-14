---
title: MolHub reception of the MolNex ETL layer — tombstone, then re-express
status: approved
slug: molix-data-dissolution-05-molhub-reception
repo: molhub
created: 2026-08-14
---

# MolHub reception of the MolNex ETL layer — tombstone, then re-express

> **Repo: molhub** (`/home/jicli594/work/molcrafts/molhub`). Nothing in this
> spec is implemented in molnex. Prerequisite: molnex phase 04 has landed, so
> the deleted sources have a stable git SHA to cite.

## Summary

MolNex phases 01–04 delete its data-acquisition layer: `DataSource`,
`PipelineSpec`/`Node`/`DAGCache`, the `Task` hierarchy, the transforms
(`AtomicDress`, `UnitConvert`, `ConstantLabel`) and five dataset adapters
(QM9, RevMD17, ThreeBPA, WaterLES, MolRec). This spec is MolHub's side of that
boundary. **The recommendation is tombstone-and-reimplement, not a straight
port** — and the reason is not taste: MolHub already has an approved,
incompatible design for the same responsibility, and the orchestration half is
already scheduled for replacement. The work MolHub actually owes is narrow:
re-express the *parsers and their unit/target conventions*, and the *transform
semantics*, on MolHub's own dataset protocol — with the same hard-coded goldens.

## Design

No new physics; the physical content is dataset unit conventions and per-element
baselines, which must survive re-expression numerically unchanged.

**Verified state of the receiving repo (re-verified 2026-08-14).**
`src/molhub/dataset/` already carries the `@dataset` + `load()` protocol
(`protocol.py`, `definition.py`, `meta.py`) and eleven adapters on it —
`qm9.py`, `revmd17.py`, `threebpa.py`, `csv_dataset.py`, `phalkethoh_mm.py`,
`zinc_typing.py`, `themol.py`, `universal_class_i.py` among them — matching the
approved six-spec chain `python-native-dataset-protocol-01..06` in
`.claude/specs/INDEX.md`. QM9 / RevMD17 / ThreeBPA are therefore **already
re-expressed** on MolHub's own protocol; porting molnex's
`DataSource[i] -> flat sample dict` shapes beside it would install a second,
competing dataset interface.

**Verdict — straight port vs tombstone.** Recommend **tombstone-and-reimplement**:

1. *A straight port would install a competing protocol.* Porting `QM9Source`
   with its `__getitem__`/`source_id`/`TARGET_SCHEMA` shape into the same
   package that `python-native-dataset-protocol-03` is landing gives MolHub two
   dataset interfaces at once — precisely the "second way to do it" that the
   approved chain exists to eliminate.
2. *The orchestration half is already superseded.* `PipelineSpec`/`DatasetTask`
   materialise `PackedCache` files eagerly; `streaming-data-tiers` assigns block
   format to **molnex -02** and the conveyor's prefetch/prepare/ledger to
   **molhub -03**, and pins `PackedCache` v1's run-scoped charter to molnex.
   Porting the eager DAG would import a design with a scheduled demolition date.
3. *What is genuinely irreplaceable is small and testable.* The per-dataset
   parsing rules (file layout, unit conversions, which observables are
   graph-level vs atom-level) and the transform semantics (`AtomicDress`'s
   least-squares per-element baseline fit + `state_dict` round-trip,
   `UnitConvert`'s factors, `ConstantLabel`'s default) carry real information and
   are pinned by molnex tests that are being deleted. These are ported —
   as behaviour plus goldens, re-expressed on MolHub's protocol.

**Scope of this spec, therefore:**

- **Tombstone record** — a note under `.claude/notes/` naming the molnex
  deletion commit SHA, the deleted file list, and, per module, the verdict
  (`re-expressed in <spec>` / `superseded by streaming-data-tiers-03` /
  `dropped`). Without this, the reference implementation is unfindable in a
  year, and "we ported it somewhere" becomes folklore.
- **WaterLES + MolRec** — the two adapters the approved chain does **not**
  cover — re-expressed on the `@dataset` + `load()` protocol, with the target
  schemas and unit conventions carried over verbatim and pinned by hard-coded
  values lifted from the deleted molnex tests.
- **Transform semantics** — `AtomicDress`, `UnitConvert`, `ConstantLabel`
  re-expressed as prepare-stage transforms in MolHub's dataset layer, each with
  a hard-coded numerical golden (notably: the per-element baseline fit and its
  state round-trip).
- **NeighborList wrapper** — MolHub's pipeline decides cacheability by
  `isinstance(task, (SampleTask, DatasetTask))`. A thin MolHub `SampleTask`
  subclass delegates to `molix.batch.NeighborList` (dependency direction
  molhub → molnex, which is the legal one). The kernel-output normalisation
  (pbc, NaN strip, symmetry expansion, edge-sign) is **never** duplicated.
- **Explicitly not ported:** `DataSource`, `InMemorySource`, `SubsetSource`,
  `Node`, `Edge`, `DAGCache`, `PipelineSpec`, `Pipeline`, `Task`/`SampleTask`/
  `DatasetTask`/`Runnable` as molnex defined them, and `QM9Source`/
  `RevMD17Source`/`ThreeBPASource` (owned by
  `python-native-dataset-protocol-03/-04`).

**Sequencing.** The `@dataset` + `load()` protocol and its reference
adapters are already in-tree, so the two new adapters are implementable
immediately after molnex phase 04 lands (the tombstone needs the deletion SHA).
The tombstone note is written first in any case — deferring the port is
acceptable; losing the record of what was deleted is not. This spec must not be
closed by asserting the port "will happen in -03-conveyor" without either the
note or the criteria below being satisfied.

### Reuse decision

No `librarian_report` supplied (cross-repo task); resolved from a direct read of
`/home/jicli594/work/molcrafts/molhub/src/molhub/dataset/` and molhub's spec index.

- `molhub.dataset.hub.ArtifactHub` / `molhub.dataset.cache.DownloadCache` —
  **reuse**: new adapters fetch through the existing coordinate/URL cache seams;
  no new download path.
- `@dataset` + `DatasetManifest` + `load()` (python-native-dataset-protocol
  01–03) — **reuse**: WaterLES and MolRec are declared on it, not beside it.
- `molix.batch.NeighborList` — **reuse** across the repo boundary via a thin
  `SampleTask` delegate; **never** reimplemented in molhub.
- `molix.store.PackedCache` — **reuse** (molnex-owned, run-scoped); molhub does
  not fork a second packed format.
- molnex `PipelineSpec` / `DAGCache` — **new — not adopted**: superseded by
  `streaming-data-tiers-03-conveyor`, which owns prepare/prefetch/ledger.
- Closest pattern: `molhub/dataset/hub.py` — Protocol-first, one-verb seams,
  docstrings that argue the boundary. New modules read the same way.

## Files to create or modify

> Paths are relative to `/home/jicli594/work/molcrafts/molhub`. Exact module
> filenames under `src/molhub/dataset/` follow whatever
> `python-native-dataset-protocol-01/-03` established at implementation time;
> the two adapters and the transforms module are new files in that package.

- `.claude/notes/molnex-etl-tombstone.md` (new)
- `.claude/notes/streaming-data-tiers.md` (repoint the two stale molnex paths: `molnex:src/molix/data/sampler.py` → `molnex:src/molix/batch/sampler.py`, `molnex:src/molix/data/cache.py` → `molnex:src/molix/store/cache.py`)
- `.claude/specs/INDEX.md` (register this spec)
- `src/molhub/dataset/water_les.py` (new)
- `src/molhub/dataset/molrec.py` (new)
- `src/molhub/dataset/transforms.py` (new — `AtomicDress`, `UnitConvert`, `ConstantLabel` re-expressed)
- `src/molhub/dataset/neighbor.py` (new — `SampleTask` delegate over `molix.batch.NeighborList`)
- `src/molhub/dataset/__init__.py`
- `tests/test_dataset/test_water_les.py` (new)
- `tests/test_dataset/test_molrec.py` (new)
- `tests/test_dataset/test_transforms.py` (new)
- `tests/test_dataset/test_neighbor.py` (new)
- `regressions/molix-data-dissolution-05-molhub-reception.py` (new)

## Tasks

- [ ] Write the tombstone note `.claude/notes/molnex-etl-tombstone.md` recording the molnex deletion SHA, the deleted file list, and the per-module verdict (re-expressed here / superseded by streaming-data-tiers-03 / dropped)
- [ ] Write failing tests for the two new adapters (`tests/test_dataset/test_water_les.py`, `test_molrec.py`) pinning target schemas, units and per-sample shapes with values lifted from the deleted molnex tests (RED)
- [ ] Write failing `tests/test_dataset/test_transforms.py` pinning the `AtomicDress` per-element baseline fit, its state round-trip, `UnitConvert` factors and `ConstantLabel` default (RED)
- [ ] Implement `WaterLESSource` equivalent in `src/molhub/dataset/water_les.py` on the `@dataset` + `load()` protocol
- [ ] Implement `MolRecSource` equivalent in `src/molhub/dataset/molrec.py` on the same protocol
- [ ] Implement `AtomicDress`, `UnitConvert` and `ConstantLabel` in `src/molhub/dataset/transforms.py`
- [ ] Implement the `SampleTask` delegate in `src/molhub/dataset/neighbor.py` that wraps `molix.batch.NeighborList` without duplicating its normalisation, with `tests/test_dataset/test_neighbor.py`
- [ ] Repoint the two stale `molnex:src/molix/data/...` paths in `.claude/notes/streaming-data-tiers.md` and register this spec in `.claude/specs/INDEX.md`
- [ ] Add regression example `regressions/molix-data-dissolution-05-molhub-reception.py` (public API only; hard-coded goldens, no third-party runtime)
- [ ] Run full check + test suite

## Testing strategy

Unit tests only under `tests/`, mirroring `src/molhub/dataset/`; one function or
method per test.

- `test_water_les.py` → per-method: frame parsing, target schema
  (graph-level vs atom-level split), unit conversion, sample count and per-sample
  tensor shapes. Values are the literals from the deleted molnex
  `tests/test_molix/test_datasets/test_water_les.py` and `test_units_contract.py`.
- `test_molrec.py` → per-method: record → sample mapping, per-instance target
  schema derivation from present observables, `source_id` stability (cache
  invalidation depends on it).
- `test_transforms.py` → `AtomicDress.fit` on a hand-built 3-element set with a
  **hard-coded** expected baseline vector and residual; `state_dict` /
  `load_state_dict` round-trip; `UnitConvert` exact factor application;
  `ConstantLabel` default write.
- `test_neighbor.py` → the delegate produces exactly what
  `molix.batch.NeighborList` produces on a 3-atom chain (identity of output, not
  a re-derivation), and is recognised as cacheable by the pipeline's task check.
- Edge cases: an empty observable set (MolRec), a single-frame file (WaterLES),
  an unfitted `AtomicDress` raising rather than silently returning zeros.

Regression example:
`regressions/molix-data-dissolution-05-molhub-reception.py` — public API only.
It loads one small bundled fixture through each new adapter and pins literal
expected values (atom counts, first/last positions, target values in stated
units), applies `AtomicDress` fitted on that fixture and pins the literal
baseline, and runs the neighbour delegate on a hard-coded 3-atom chain pinning
`edge_index` / `edge_diff` / `edge_dist`. Any value that originally came from an
external tool is embedded as a literal with a comment naming the tool, version,
command and date; no third-party oracle runs at test time.

## Out of scope

- Re-porting QM9 / RevMD17 / ThreeBPA — owned by
  `python-native-dataset-protocol-03-load` and `-04-migrate`.
- The conveyor itself (prefetch / prepare / block ledger / leases) —
  `streaming-data-tiers-03-conveyor`.
- The block store format — `streaming-data-tiers-02` (repo: molnex).
- Reproducing `PipelineSpec` / `DAGCache` / `DataSource` in any form.
- Any change to molnex; that repo's side is complete at phase 04.
