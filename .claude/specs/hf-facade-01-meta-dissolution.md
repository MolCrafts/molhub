---
title: Meta dissolution — delete Targets/MetaCodec/write_meta, everything reads and writes frame.meta
status: approved
grilled: true
slug: hf-facade-01-meta-dissolution
repo: molhub
chain: hf-facade (01-meta-dissolution → 02-frame-records → 03-builder-info → 04-streaming-prepare)
created: 2026-08-15
---

# Meta dissolution — delete Targets/MetaCodec/write_meta, everything reads and writes frame.meta

> First sub-spec of the `hf-facade` chain. Governing basis: the operator
> override recorded in `.claude/notes/notes.md` § "[2026-08-15] User-facing API
> = HuggingFace datasets, records = Frame/Trajectory (operator override)" —
> verbatim complaint (2): 「删除Targets这个东西，不要引入新对象，都基于Frame这个
> 对象」. molpy 0.13's `Frame.meta` is a write-through `MutableMapping`
> returning plain scalars (probed 2026-08-14/15; the molrs stub now declares the
> base, molrs commit 010bd9f), so the wrappers this spec deletes duplicate what
> the platform already provides.

## Summary

`Targets`, `MetaCodec` and `write_meta` are deleted and every producer and
consumer writes `frame.meta` directly, because molpy 0.13's `Frame.meta` is
already the write-through scalar mapping those three wrapped. Nine adapters,
the transforms, the conveyor encoder, one audit script and three regressions
move to `frame.meta.update(...)` / `frame.meta[key]` with **no numeric golden
changing anywhere** — value preservation is the acceptance bar, not a hope.

## Design

No new type. `frame.meta = {...}` (whole replacement, the old `Targets.write`
semantics) and `frame.meta.update({...})` (merge) replace the two write shapes;
`dict(frame.meta)` replaces `Targets.read()` where a detached copy is genuinely
needed (`transforms._with_targets` on a copied frame, `qm9._filter_targets`).

The `MetaCodec` dtype-pinning behaviour is *dropped on purpose*: molpy 0.13
coerces on set, and molhub deciding the stored dtype was the reason the wrapper
survived the 0.12→0.13 migration. The one behaviour worth keeping — rejecting
non-scalars — is now molpy's own (`frame.meta` raises `TypeError` on
unsupported values), and `transforms.MetaScalar` stays as the documented scalar
contract.

**Reuse decision.**
- `frame.meta` (molpy `MutableMapping`) — **reuse**; replaces `Targets` /
  `write_meta` one-for-one.
- `molpy._frame_meta` helpers — **new — not adopted**: not exported from
  `molpy.__init__`, so importing a private module would be a worse coupling
  than the two-line call site.
- Every adapter/transform — **reuse** (call-site edit only).
- `_meta.py`, `meta.py`, `tests/test_dataset/test__meta.py` — **deleted**.

## Files to create or modify

- `src/molhub/dataset/_meta.py` (delete)
- `src/molhub/dataset/meta.py` (delete)
- `src/molhub/dataset/water_les.py`, `threebpa.py`, `revmd17.py`,
  `csv_dataset.py`, `molrec.py`, `zinc_typing.py`, `phalkethoh_mm.py`
- `src/molhub/dataset/qm9.py`, `themol.py`, `transforms.py`
- `src/molhub/dataset/__init__.py`
- `src/molhub/conveyor/encoder.py`
- `src/molhub/dataset/universal_class_i.py` (one docstring word — prose coincidence with the deleted class name)
- `scripts/audit_themol_shards.py`
- `tests/test_dataset/test__meta.py` (delete)
- `tests/test_dataset/test_transforms.py`, `test_qm9.py`, `test_water_les.py`,
  `test_themol.py`, `test_revmd17.py`, `test_threebpa.py`,
  `test_csv_dataset.py`, `test_molrec.py`, `test_phalkethoh_mm.py`,
  `test_zinc_typing.py`
- `tests/test_conveyor/test_encoder.py`, `tests/test_conveyor/test_prepare.py`
- `regressions/molix-data-dissolution-05-molhub-reception.py`,
  `regressions/mm-param-val-01-molhub-contract.py`,
  `regressions/streaming-data-tiers-03-conveyor-03-prepare.py`
- `regressions/hf-facade-01-meta-dissolution.py` (new)

## Tasks

- [ ] Write failing unit tests for direct `frame.meta` read/write on the adapter surface with no `Targets` import (`tests/test_dataset/test_water_les.py` → `TestWaterLESDataset`, `tests/test_dataset/test_qm9.py` → `TestQM9Dataset`, `tests/test_dataset/test_transforms.py` → `TestUnitConvert`)
- [ ] Replace `write_meta(frame, …)` with `frame.meta.update(…)` in `src/molhub/dataset/{water_les,threebpa,revmd17,csv_dataset,molrec,zinc_typing,phalkethoh_mm}.py`
- [ ] Replace `Targets(...).read()/.write()` with `frame.meta` / `dict(frame.meta)` in `src/molhub/dataset/{qm9,themol,transforms}.py` and `src/molhub/conveyor/encoder.py` — NOTE: `qm9._filter_targets`'s write is DROP semantics and must become whole replacement `frame.meta = {...}` (never `.update()`, which would let unfiltered keys survive); its fresh-frame write may use either
- [ ] Delete `src/molhub/dataset/_meta.py` and `src/molhub/dataset/meta.py` and drop `Targets` / `MetaCodec` from `src/molhub/dataset/__init__.py`
- [ ] Delete `tests/test_dataset/test__meta.py` and rewrite the meta assertions in `tests/test_dataset/*.py`, `tests/test_conveyor/test_encoder.py` and `tests/test_conveyor/test_prepare.py`
- [ ] Read `frame.meta` directly in `scripts/audit_themol_shards.py`
- [ ] Re-pin `regressions/molix-data-dissolution-05-molhub-reception.py`, `regressions/mm-param-val-01-molhub-contract.py` and `regressions/streaming-data-tiers-03-conveyor-03-prepare.py` to `frame.meta` with every numeric golden unchanged
- [ ] Add regression example `regressions/hf-facade-01-meta-dissolution.py` (public API only; hard-coded goldens, no third-party runtime)
- [ ] Verify no file under `src/`, `tests/`, `scripts/` or `regressions/` names the identifiers `Targets`, `MetaCodec` or `write_meta` (identifier-boundary-aware: `write_metadata` is an unrelated conveyor API and must not match; exclude `*.egg-info/`), and reword the one prose coincidence `universal_class_i.py:31` ("Targets available from the role" → "Target schemas available from the role")
- [ ] Run full check + test suite

## Testing strategy

Unit tests mirror source, one module per file:
`tests/test_dataset/test_transforms.py::TestAtomicDress` pins the fitted
baselines as literals (unchanged from today's file), `::TestUnitConvert` pins
the hartree→eV factor, `test_water_les.py::TestWaterLESDataset` pins
`frame.meta["energy"]` from a synthetic extxyz fixture,
`test_qm9.py::TestQM9Dataset` pins the filtered-target key set,
`test_themol.py::TestTHEMolShardDataset` pins
`frame.meta["mapped_isomeric_smiles"]` / `["total_charge"]` from the existing
h5py fixture.

Edge cases: a non-scalar meta value must still raise (now from molpy);
`transforms.execute` must still not mutate its input (assert the source frame's
meta after the call).

Regression `regressions/hf-facade-01-meta-dissolution.py` builds a frame,
writes graph scalars, runs `UnitConvert`→`AtomicDress`→`ConstantLabel`, and
asserts the same literals the reception regression uses, proving the wrapper
removal is value-preserving.

## Out of scope

- Record dataclasses (sub-spec 02).
- `TargetSchema` (unchanged).
- Any change to *which* keys an adapter writes — only *how* they are written
  moves.
