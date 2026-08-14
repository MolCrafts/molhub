---
title: Frame records — dissolve the THEMol record dataclasses into molpy Frame/Trajectory
status: approved
slug: hf-facade-02-frame-records
repo: molhub
chain: hf-facade (01-meta-dissolution → 02-frame-records → 03-builder-info → 04-streaming-prepare)
created: 2026-08-15
---

# Frame records — dissolve the THEMol record dataclasses into molpy Frame/Trajectory

> Second sub-spec of the `hf-facade` chain; depends on `01-meta-dissolution`.
> Governing basis: the 2026-08-15 operator override — "Records ARE molpy
> objects. One geometry = `Frame` ...; multi-frame sampling unit =
> `Trajectory`. ... the record dataclasses
> (HessianRecord/EnergyForceTrajectory/TorsionProfile/MBISRecord) are deleted —
> no wrapper objects on top of Frame."

## Summary

The four THEMol record dataclasses are dissolved into `molpy.Frame` and
`molpy.Trajectory`, so a THEMol sample is the same object type as every other
molhub sample. The Cartesian Hessian becomes a COO block on the frame, MBIS
supervision becomes `atoms` columns, and trajectories/scans become
`Trajectory`s whose per-frame `meta` carries the scalars. `THEMolUnitEncoder`
stops dispatching on record classes and dispatches on (record type + its
declared task), with no change to any column it emits.

## Domain basis — probed platform facts (molpy 0.13.1)

| Fact | Evidence |
|---|---|
| `Frame` accepts arbitrary named `Block`s with arbitrary float columns (COO `{row,col,value}` works) | probe 2026-08-15 |
| `Trajectory` holds frames; **eager** (the Rust container copies each into its column store on construction) | `molpy/core/trajectory.py:25-64` |
| **`Trajectory` round-trips per-frame `meta` and non-`atoms` blocks** (the D3 gate) | probe 2026-08-15: 3-frame trajectory with per-frame meta scalars + a 1-row `scan` block indexed back intact — PASS. The characterization test in this spec pins it permanently. |
| `Trajectory` has no trajectory-level meta; it carries a pass-through `topology` slot and optional `step`/`time` arrays | `molpy/core/trajectory.py:66-79` |
| `frame.meta` rejects len-4 sequences → index 4-tuples go in a 1-row valence-style block | probe 2026-08-14 |

**D1 — record dissolution mapping (binding).**
- `hessian` → one `Frame`: existing `atoms`/`bonds` blocks unchanged, plus a
  `hessian` block with columns `row:int32`, `col:int32`, `value:float64`
  holding **all** `(3N)²` entries in row-major order (no triangle folding, no
  sparsity assumption — a DFT Hessian is dense, and a discarded lower triangle
  is a convention every reader must then remember; row-major order is
  guaranteed so a consumer may `value.reshape(3N, 3N)` directly). Cost:
  16 B/entry vs 8 B dense → **2× the dense payload**; the tiers strategy's
  hot-tier Hessian core moves from ≈5.8 GB to ≈11.6 GB, which exceeds the
  `streaming-data-tiers-01-strategy.md` §6 budget — if the implementer measures
  this as binding, drop `row`/`col` to `int16` (3N ≤ 32767 covers every
  drug-like molecule) → 12 B/entry ≈ 8.7 GB, and record the choice. Either way
  the block-format encoder still does not encode the Hessian (the named gap in
  `conveyor/encoder.py`'s docstring stands).
- `mbis` → one `Frame` with per-atom `atoms` columns: `atomic_charge`,
  `atomic_volume`, `dipole_x/y/z`, one column per independent quadrupole
  component named by its Cartesian indices, and the per-atom Slater parameters.
  The exact component count and parameter arity are **read from the source
  array shapes and pinned as literals in a test**; an array whose row count is
  not N is refused loudly, never broadcast.
- `hessian-relax` → `Trajectory`; per-frame `meta` carries `energy`,
  `step_index`.
- `torsion-scan` / `torsion-relax` → `Trajectory`; per-frame `meta` carries
  `energy`, `torsion_angle`, `scan_id`, `constraint_index` (+`step_index` for
  relax); the four dihedral atom indices go in a 1-row block
  `frame["scan"]{atomi,atomj,atomk,atoml}`.

**D2 — laziness within a record is deliberately given up.** `molpy.Trajectory`
materializes on construction, so `_LazyFrameSequence` and `_LazyAngles`
(`src/molhub/dataset/themol.py:342-498`) are deleted. Byte accounting: the
largest unit is a torsion-relax scan, ≈24 constraints × ≈10 steps × 40 atoms ×
3 × 8 B ≈ 230 kB — three orders below the block ceiling. Laziness *between*
records (the per-process HDF5 handle in `THEMolShardDataset`) is unchanged and
is still the thing that matters.

**D10 — `Sample` widens, which touches a "never change casually" bullet.** The
CLAUDE.md sample bullet is amended in the same change (docs-typed criterion),
citing the operator note.

## Design

`_read_hessian` / `_read_mbis` return `Frame`; `_read_hessian_relax` /
`_read_torsion` / `_read_torsion_relax` return `Trajectory` per D1.
`_LazyFrameSequence` / `_LazyAngles` are deleted per D2; `_dihedral_angle`
stays and is called once per frame at read time. `THEMolShardDataset` is
unchanged apart from its `reader` return type. `Sample` widens to
`Frame | Trajectory` (D10).

In `conveyor/encoder.py`, `encode` becomes: `Frame` → one-frame unit;
`Trajectory` → multi-frame unit; torsion columns emitted when the record
carries the `scan` block. The MBIS refusal moves from
`isinstance(record, MBISRecord)` to **construction time** —
`THEMolUnitEncoder(task="mbis")` raises `UnsupportedRecordError` — because
after dissolution an MBIS frame and a Hessian frame are the same type and one
shard is one task, so refusing per record would be both later and weaker. The
named Hessian gap and the dropped `optimization_steps` (now
`meta["step_index"]`) stay documented in the module docstring.

**Reuse decision.**
- `molpy.Frame` / `molpy.Trajectory` — **reuse**: the record types.
- `THEMolShardDataset` — **reuse**: stays the per-shard lazy map; only its
  `reader` return type changes.
- `_mapped_topology_frame`, `_frame_with_energy_forces`, `_dihedral_angle`,
  `_numbered_keys` — **reuse** (return type / call order change only).
- `THEMolUnitEncoder.identity` — **reuse**: the one identity implementation.
- `RawUnit` — **reuse** unchanged.
- The four dataclasses, `_LazyFrameSequence`, `_LazyAngles` — **deleted**.
- No new type is introduced by this sub-spec.

## Files to create or modify

- `src/molhub/dataset/themol.py`
- `src/molhub/dataset/protocol.py`
- `src/molhub/dataset/__init__.py`
- `src/molhub/conveyor/encoder.py`
- `src/molhub/conveyor/errors.py`
- `src/molhub/conveyor/prepare.py` (docstring/type references only)
- `scripts/audit_themol_shards.py`
- `tests/test_dataset/test_themol.py`, `tests/test_dataset/test_protocol.py`
- `tests/test_conveyor/test_encoder.py`, `tests/test_conveyor/test_prepare.py`
- `regressions/streaming-data-tiers-03-conveyor-03-prepare.py`
- `regressions/hf-facade-02-frame-records.py` (new)
- `CLAUDE.md` (the `Sample` bullet, per D10)

## Tasks

- [ ] Write failing characterization test for `molpy.Trajectory` round-tripping per-frame `meta` and a non-`atoms` block (`tests/test_dataset/test_themol.py` → `TestTrajectoryRoundTrip`)
- [ ] Write failing unit tests for the dissolved records (`tests/test_dataset/test_themol.py` → `TestTHEMolHessian`, `TestTHEMolMBIS`, `TestTHEMolTorsionScan`, `TestTHEMolHessianRelax`)
- [ ] Emit a `Frame` carrying the COO `hessian` block from `_read_hessian` and per-atom MBIS columns from `_read_mbis` in `src/molhub/dataset/themol.py`
- [ ] Emit a `molpy.Trajectory` from `_read_hessian_relax`, `_read_torsion` and `_read_torsion_relax`, with the dihedral indices in a 1-row `scan` block
- [ ] Delete `HessianRecord`, `EnergyForceTrajectory`, `TorsionProfile`, `MBISRecord`, `_LazyFrameSequence` and `_LazyAngles`, widen `Sample` in `src/molhub/dataset/protocol.py`, and update `src/molhub/dataset/__init__.py` and the CLAUDE.md sample bullet
- [ ] Write failing unit tests for the encoder's `(Frame | Trajectory, task)` dispatch and its construction-time `task="mbis"` refusal (`tests/test_conveyor/test_encoder.py` → `TestTHEMolUnitEncoder`)
- [ ] Re-dispatch `THEMolUnitEncoder.encode` on `Frame`/`Trajectory` and move the MBIS refusal into `__init__` in `src/molhub/conveyor/encoder.py`
- [ ] Re-pin the record constructors in `regressions/streaming-data-tiers-03-conveyor-03-prepare.py` with every RawUnit column, dtype and sealed-manifest golden unchanged
- [ ] Add regression example `regressions/hf-facade-02-frame-records.py` (public API only; hard-coded goldens, no third-party runtime)
- [ ] Run full check + test suite

## Testing strategy

`tests/test_dataset/test_themol.py` keeps its synthetic h5py fixtures and
gains: `TestTrajectoryRoundTrip` (meta + custom block survive `Trajectory`
construction and indexing — the D3 gate, run first; already probed PASS on
2026-08-15, the test pins it permanently); `TestTHEMolHessian` pinning the
`hessian` block's row count `(3N)²`, its row-major ordering and three literal
entries of the identity fixture; `TestTHEMolMBIS` pinning the exact per-atom
column names and one literal charge; `TestTHEMolTorsionScan` pinning
`len(traj)`, per-frame `meta["torsion_angle"]` literals (recomputed from the
same `_dihedral_angle` maths as today's test) and the `scan` block's four
indices; `TestTHEMolHessianRelax` pinning `meta["step_index"]` ordering.

Edge cases: a scan with a zero central bond still raises; a frame whose atom
count disagrees with the topology still raises; a bondless molecule still
yields three empty bond columns.

`tests/test_conveyor/test_encoder.py` pins that the emitted `RawUnit.topology`
/ `.frames` key sets and dtypes are **identical** to the pre-dissolution
literals, and that `THEMolUnitEncoder(task="mbis")` raises at construction.

Regression `regressions/hf-facade-02-frame-records.py` reads a synthetic shard
through `THEMolShardDataset`, asserts the record types and the same encoder
column goldens, offline.

## Out of scope

- Encoding the Cartesian Hessian into `molix.block/1` (the named gap stands).
- Adding a hessian or MBIS column route to molnex.
- Any loader surface (03/04).
