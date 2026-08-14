---
title: Conveyor prepare stage — split-routing, unit-integral block production
status: approved
slug: streaming-data-tiers-03-conveyor-03-prepare
repo: molhub
chain: streaming-data-tiers-03-conveyor
created: 2026-08-14
---

# Conveyor prepare stage — split-routing, unit-integral block production

> **Repo: molhub** (`/home/jicli594/work/molcrafts/molhub`). Third of the four
> `-03-conveyor` sub-specs. `-01-ledger` (block ledger, four states, READY
> record) and `-02-roster` (what to fetch, in what order) are **given
> contracts**: this spec consumes their surfaces and redesigns neither.

## Summary

The prepare stage is the CPU half of the three-stage conveyor
(`.claude/specs/streaming-data-tiers-01-strategy.md` § 4, § 12): it turns one
downloaded raw THEMol shard into one or more sealed, split-pure, unit-aligned
READY blocks in the molnex block format, and reports exactly the evidence a
READY ledger record needs. It lands two new modules under a new
`src/molhub/conveyor/` package — `encoder.py`, which maps the THEMol record
types molhub already parses (`HessianRecord`, `EnergyForceTrajectory`,
`TorsionProfile`) onto numpy `RawUnit`s, and `prepare.py`, which routes each
unit to its molecule-level split and feeds it whole to a `BlockWriterLike`
seam. The binding architectural decision is that molnex enters through an
**optional extra plus a lazy import**: `from molix.store.block import
BlockWriter, SamplingUnit` happens in exactly one place, inside the molnex
adapter, so the base environment stays torch-free, unit tests run against an
injected fake writer, and the only real-writer proof is a `MOLNEX_SRC`-gated
regression leg. This extends the ruling `molix-data-dissolution-05-molhub-reception`
already made for `molhub.dataset.neighbor` (its ac-006) from one delegate method
to a whole package. The spec also closes a live dependency defect: **numpy is
imported by ten modules under `src/molhub/` and declared nowhere**, working only
through h5py's transitive pull.

## Design

### 0. Position in the chain, and what is *not* redesigned here

`-01-ledger` owns the four-state ledger and the READY record; `-02-roster` owns
which shard is fetched next; `-04` (the chain's last sub-spec) owns queue
backpressure, leases and shard deletion (I3/I4/I9). This spec owns exactly the
transformation in the middle: *downloaded shard → sealed blocks + the evidence
that they are READY*. It writes no ledger, deletes no shard, bounds no queue.

**Ledger seam is a value, not a call.** `PrepareJob.run()` returns
`PreparedBlocks`; it does not import or invoke the ledger. `PreparedBlocks` is
the complete payload of one READY record (I5): every sealed root, its split,
unit count, frame count, committed bytes and `block_digest`. Whether
`-01-ledger`'s recorder consumes that object or its fields is `-01`'s call; this
spec binds only that the evidence is complete, and produced in one place.

### 1. Split fan-out ruling (binding)

A raw THEMol shard is **split-MIXED**: `scripts/build_class1_splits.py` splits
at *molecule identity* (blake2b-128 of `mapped_isomeric_smiles`, 8:1:1, seed
20260814), never at shard boundaries, so one shard carries train, val and test
molecules interleaved. I2/I7 and the block format make a block **split-PURE**,
and `BlockWriter` takes `split` once, in the constructor
(`molnex:src/molix/store/block.py:751`). Therefore:

> One prepare job over one downloaded shard opens **up to three writers at
> once** (`train` / `val` / `test`) and seals all of them, plus a **size fan-out**
> whenever a split's share crosses the 1–5 GB block ceiling. Every sealed root
> is named in the **single** READY ledger record for that shard.

Routing is a lookup, never a derivation: `PrepareJob` takes
`split_of: Mapping[str, str]` (identity → `"train" | "val" | "test"`, the
hot-tier `identity_splits.csv.gz` of `class1-universal-splits@1`) and raises
`UnroutableUnitError` naming the identity and the unit key when a molecule is
absent. There is no default split, no "assume train", no re-splitting (I7).
Loading the manifest is the caller's job — this stage performs no IO of its own
beyond the block roots it writes. At 2.4 M identities the mapping costs ≈ 0.5 GB
resident, which is hot-tier budget (strategy § 6), and any compact `Mapping`
implementation satisfies the seam.

Block roots are deterministic: `root / f"{name}-{split}-{seq:03d}"`, where `name`
is the shard's identity (e.g. `themol-torsion-scan-shard-000`) and `seq`
increments **per split** on size fan-out. A writer is opened lazily, on the
first unit that routes to its split, so a split with no members in this shard
produces no directory and `seal()` is never called on an empty block (molnex
rejects that).

### 2. Unit integrality is structural, not checked (I2)

`THEMolShardDataset.__getitem__` (`src/molhub/dataset/themol.py:98`) already
returns **one complete sampling unit** per index — a `HessianRecord`, an
`EnergyForceTrajectory` (one molecule's whole relaxation) or a `TorsionProfile`
(one whole scan, angles and frames together). The conveyor never flattens them:

- `THEMolUnitEncoder.encode(record) -> RawUnit` is one record in, one unit out.
  There is no frame-level encoder method.
- `PrepareJob`'s only ingestion call is `writer.append_unit(unit)`. There is no
  `append_frame` anywhere in the seam, in the adapter, or in molnex
  (`molnex:src/molix/store/block.py:853` is the sole ingestion method).
- The size fan-out check runs **after** `append_unit`, against
  `writer.committed_bytes`. A unit that alone exceeds the ceiling still lands
  whole, in its own block. Cutting a unit to hit a byte target is therefore not
  expressible.

The unit test asserts the consequence (every recorded object is one whole
`RawUnit`, whose `n_frames` equals its source record's frame count, and no key
is appended twice); the guarantee itself comes from the shape.

### 3. Encoder — `src/molhub/conveyor/encoder.py`

`RawUnit` is a frozen value type holding **numpy** arrays:

| field | meaning |
|---|---|
| `key` | unit identity — `molecule_id` for a bundle, `scan_id` for a scan |
| `identity` | blake2b-128 hex of `mapped_isomeric_smiles` — the split key |
| `task` | THEMol subset label (`hessian`, `hessian-relax`, `torsion-scan`, `torsion-relax`) |
| `topology` | molecule-space columns, `{name: np.ndarray}` |
| `frames` | frame-space columns, `{name: np.ndarray}` |

with derived `n_atoms` / `n_frames`. Column names are exactly molnex's route
names (`molnex:src/molix/store/block.py:239-285`), because an unroutable column
cannot enter a block:

| column | space | dtype | unit |
|---|---|---|---|
| `atom_Z` | molecule_atom | `<i2` | — |
| `bond_atomi`, `bond_atomj`, `bond_type` | molecule_term:bond | `<i4` | molecule-local `[0, N)` |
| `mol_target_torsion_atoms` `(1, 4)` | molecule | `<i4` | the scanned dihedral (torsion tasks only) |
| `frame_pos` `(F·N, 3)` | frame_atom | `<f4` | Å |
| `frame_atom_target_forces` `(F·N, 3)` | frame_atom | `<f4` | kcal mol⁻¹ Å⁻¹ |
| `frame_target_energy` `(F,)` | frame | `<f4` | kcal mol⁻¹ |
| `frame_target_torsion_angle` `(F,)` | frame | `<f4` | degrees (torsion tasks only) |

**No unit conversion happens here, by construction.** `THEMOL_UNITS`
(`src/molhub/dataset/themol.py:40-50`) declares Å / kcal mol⁻¹ /
kcal mol⁻¹ Å⁻¹, which is exactly the block-format convention
(`molnex:.claude/specs/streaming-data-tiers-02-block-format.md` § Domain basis). The
encoder's only numeric transformation is the dtype narrowing float64 → float32
that the store refuses to do silently, and `THEMOL_UNITS` is what the caller
puts in `provenance["units"]`. No conversion factor appears in the module.

`encode` is the single public verb, dispatching on record type; `MBISRecord` and
anything else raise `UnsupportedRecordError`. `bond_type` is the integer bond
order carried by the record's `bonds` block (`bond_number`, falling back to an
integral `bond_type`); a record that carries bonds but no integer order column
raises `IncompleteRecordError` — a fabricated zero order would invent chemistry.
A molecule with no bonds is legitimate and yields **empty** bond columns
(`bond_n = 0`), not a missing column, so the block's frozen schema stays
uniform. Frames whose atom count disagrees with the topology raise, since the
`k·N` stride is what makes the two-level layout valid.

**One shard = one task = one frozen schema.** `THEMolUnitEncoder(task=…)` is
constructed per shard, so every unit in a job carries the same task label and
the same column set. That is what makes molnex's freeze-schema-from-the-first-unit
rule safe here without any negotiation.

**Identity rule — one implementation (generalize).** `identity_of` currently
lives only in `scripts/build_class1_splits.py:55-56`. Split *production* and
split *routing* drifting apart would silently mis-route molecules, so the rule is
promoted to `THEMolUnitEncoder.identity(mapped_isomeric_smiles) -> str` and the
script imports it. The uuid trap is inherited verbatim from that script: the
torsion `uuid` is a **scan** identity with zero overlap with hessian/mbis uuids
— never key a split on it.

**Named gap — the Cartesian Hessian is not encoded.** `HessianRecord` yields a
one-frame equilibrium-geometry unit; its `(3N, 3N)` Cartesian Hessian is *not*
stored, because `molix.block/1` has no routable column space for a per-molecule
ragged 2-D payload (the format's only Hessian column is
`internal_target_hessian_diag`, a *projected internal* target, and the projection
needs a B-matrix that is equally unroutable). This is not a silent drop: the
strategy already classifies the Hessian core as **hot tier**, permanently
resident at ≈ 5.8 GB (§ 6), so it does not belong in a rolling block at all. The
encoder docstring states this and names the owner of the eventual
projected-target column (`-04` or a dedicated spec); the unit test pins the
hessian unit's column set so the omission cannot become accidental.

### 4. Prepare — `src/molhub/conveyor/prepare.py`

Two `@runtime_checkable` Protocols mirror the **verified** molnex surface
(`molnex:src/molix/store/block.py`, landed):

```python
class BlockWriterLike(Protocol):
    def append_unit(self, unit: Any) -> int: ...     # :853
    @property
    def committed_bytes(self) -> int: ...            # :843
    @property
    def unit_count(self) -> int: ...                 # :838
    def seal(self) -> None: ...                      # :903

class BlockWriterFactory(Protocol):
    def __call__(self, root: Path, *, split: str,
                 provenance: Mapping[str, Any]) -> BlockWriterLike: ...   # :751
```

`BlockWriterFactory` is **not** a `make_*` wrapper: it is the *constructor* seam,
satisfied by a writer class object itself. It exists because CLAUDE.md's
unit-test iron law forbids booting a sibling's real implementation inside a unit
test.

`PrepareJob(records, *, encoder, split_of, writer_factory, root, name,
provenance, max_block_bytes=2_000_000_000)` — every dependency is an explicit
narrow parameter; there is no context blob. `max_block_bytes` defaults to the
strategy's worked 2 GB example and must be positive; the production range is
1–5 GB, and tests use tiny values to exercise fan-out. `provenance` must carry
molnex's four required keys (`source`, `generator`, `created_at`, `units`) or
`IncompleteProvenanceError` fires **before** any writer is opened, so a
provenance defect cannot surface halfway through a shard in an environment
where molnex is not even importable.

`run()` iterates records → `encode` → route → get-or-open writer → `append_unit`
→ size check → seal, then seals every open writer and returns `PreparedBlocks`.
It is single-shot: a second `run()` raises.

`PreparedBlock` (frozen) carries `root`, `split`, `unit_count`, `frame_count`,
`committed_bytes`, `block_digest`; `PreparedBlocks` (frozen) carries `name` and
the ordered `blocks` tuple. The digest and the READY witness are read from
`<root>/manifest.json` with stdlib `json` after `seal()` — molhub reads exactly
four fields (`format`, `split`, `units`, `sealed`) plus `block_digest`, verifies
`format == "molix.block/1"`, `sealed is True` and `units == writer.unit_count`,
and raises `BlockFormatError` otherwise. molhub does **not** recompute the
digest: recomputation is `BlockReader.verify()`'s job in molnex, and I6 governs
the *fetch* boundary, not this stage. The narrow four-field read is the entire
cross-repo format coupling, and it is deliberately the smallest thing that makes
READY machine-checkable. `frame_count` is summed from the `RawUnit`s, giving
`-04` the per-pass coverage numbers I10 asks for.

### 5. Option A — optional extra + lazy import (binding decision)

`from molix.store.block import BlockWriter, SamplingUnit` happens **inside the
worker only**: `MolnexBlockWriter`, a small adapter class in `prepare.py` whose
`__init__` performs the import, constructs the real `BlockWriter(root,
split=…, provenance=…)`, and whose `append_unit(raw)` converts the numpy columns
to torch tensors and builds a real `SamplingUnit`. It satisfies `BlockWriterLike`
(instances) and `BlockWriterFactory` (the class object) at once, which is why the
worker is a class rather than a `create_writer` function — a bare worker function
returning writers is exactly the factory shape CLAUDE.md forbids. Consequences:

- **Base env stays torch-free.** No module-scope `torch` / `molix` import
  anywhere under `src/molhub/conveyor/`, enforced by a source-level AST guard
  test shaped like `tests/test_sources/test_layering.py`.
- **Unit tests use the injected fake.** The fake records appended units and, on
  `seal()`, writes the five manifest fields molhub reads — so the fake is honest
  about the READY witness rather than stubbing it away.
- **Real-writer parity is the regression's `MOLNEX_SRC`-gated leg**, mirroring
  `tests/test_dataset/test_neighbor.py:85-104`.

Alternatives considered and rejected, recorded so they are not re-litigated:
an **entry-point plugin** (needs molnex-side registration, i.e. a change in the
repo that must stay dataset-agnostic); a **subprocess converter with a
tensor-free wire format** (a third on-disk copy of every block, violating I3);
**seam inversion**, i.e. molnex pulling from molhub (contradicts strategy § 12
ownership, where prepare is molhub's).

`pyproject.toml` gains `prepare = [...]` under `[project.optional-dependencies]`,
mirroring the existing `huggingface` extra, plus the `ty` `unresolved-import`
override that `src/molhub/dataset/neighbor.py` already has. The extra can only
name the publishable half of the requirement: molnex is not on PyPI, so the
comment names the source install / `MOLNEX_SRC` escape hatch explicitly rather
than pretending the extra is sufficient.

### 6. Iron law — undeclared numpy closes here

`numpy` is imported at module scope by **ten** modules under `src/molhub/`
(`dataset/themol.py:18`, `transforms.py:36`, `qm9.py:23`, `revmd17.py:20`,
`threebpa.py:32`, `water_les.py:46`, `molrec.py:39`, `phalkethoh_mm.py:35`,
`zinc_typing.py:33`, `_meta.py:14`) and is declared in **no** dependency group;
it resolves today only through h5py's transitive pull. This spec makes numpy
load-bearing on a new path, so per the no-silent-debt law it is fixed here, not
left: `numpy` joins `[project] dependencies`, and the layering test asserts the
declaration so the regression cannot silently return.

### Reuse decision

No `librarian_report` was supplied with this cross-repo task; verdicts come from
direct inspection of the current trees. A blueprint refresh before `-04` is
advisable — `.claude/notes/architecture.md` still claims `regressions/` does not
exist.

- `molix.store.block.BlockWriter` / `SamplingUnit` (`molnex:src/molix/store/block.py:751`,
  `:853`, `:903`, `:373`) — **reuse** across the repo boundary through
  `MolnexBlockWriter`. molhub forks no block format and reimplements no writer.
- `molhub.dataset.themol` record types + `THEMolShardDataset` + `THEMOL_UNITS`
  (`src/molhub/dataset/themol.py:40`, `:53-79`, `:98`) — **reuse**. The conveyor
  never opens an HDF5 file itself and never re-parses THEMol.
- `scripts/build_class1_splits.py:55-56` `identity_of` — **generalize** into
  `THEMolUnitEncoder.identity`, with the script repointed, so split production
  and split routing cannot drift apart.
- `molhub.dataset.neighbor` lazy-import ruling + `MOLNEX_SRC` test gating
  (`tests/test_dataset/test_neighbor.py:85-104`,
  `.claude/specs/molix-data-dissolution-05-molhub-reception.md` ac-006) —
  **pattern**, extended from one method to a package.
- `tests/test_sources/test_layering.py` AST import guard — **pattern** for the
  no-module-scope-torch guard.
- `molhub.sources.errors` (one type per distinguishable failure) — **pattern**
  for `src/molhub/conveyor/errors.py`.
- `molhub.dataset.hub.ArtifactHub` (single-verb Protocol seam, docstring that
  argues the boundary) — **closest pattern**; `BlockWriterLike` /
  `BlockWriterFactory` read the same way, and new code follows its frozen
  dataclass / keyword-only / typed-exception house style.
- A molhub-side packed writer or block format — **new — rejected**: molnex owns
  the READY-tier format (strategy § 12); a second implementation is exactly the
  fork that boundary exists to prevent.

## Files to create or modify

- `src/molhub/conveyor/__init__.py` (new)
- `src/molhub/conveyor/errors.py` (new)
- `src/molhub/conveyor/encoder.py` (new)
- `src/molhub/conveyor/prepare.py` (new)
- `scripts/build_class1_splits.py`
- `pyproject.toml`
- `tests/test_conveyor/__init__.py` (new)
- `tests/test_conveyor/test_encoder.py` (new)
- `tests/test_conveyor/test_prepare.py` (new)
- `tests/test_conveyor/test_layering.py` (new)
- `regressions/streaming-data-tiers-03-conveyor-03-prepare.py` (new)

## Tasks

- [ ] Write failing unit tests for `THEMolUnitEncoder` in `tests/test_conveyor/test_encoder.py` (plus `tests/test_conveyor/__init__.py`) → `TestTHEMolUnitEncoder`: hard-coded goldens per record type (`HessianRecord` / `EnergyForceTrajectory` / `TorsionProfile`), pinned column sets and dtypes, zero-bond molecule, ragged-frame rejection, blake2b-128 identity hex, `UnsupportedRecordError` on `MBISRecord`
- [ ] Implement `RawUnit` and `THEMolUnitEncoder` in `src/molhub/conveyor/encoder.py` with the typed failures in `src/molhub/conveyor/errors.py` (numpy only, no unit conversion, float64→float32 narrowing, hessian gap documented), and repoint `scripts/build_class1_splits.py` at `THEMolUnitEncoder.identity`
- [ ] Write failing unit tests for `PrepareJob` in `tests/test_conveyor/test_prepare.py` → `TestPrepareJob` against an injected `BlockWriterLike` fake: whole-unit ingestion, split fan-out over a mixed-split fixture, size fan-out that never splits a unit, `UnroutableUnitError`, `IncompleteProvenanceError`, and the `PreparedBlocks` READY evidence
- [ ] Implement `BlockWriterLike` / `BlockWriterFactory` protocols, `PreparedBlock` / `PreparedBlocks` and `PrepareJob.run` in `src/molhub/conveyor/prepare.py`, exporting the package surface from `src/molhub/conveyor/__init__.py`
- [ ] Write `tests/test_conveyor/test_layering.py`: no module-scope `torch` / `molix` import under `src/molhub/conveyor/`, `molhub.dataset` imports no `molhub.conveyor`, and `numpy` declared in `[project].dependencies` (RED on the declaration half)
- [ ] Implement `MolnexBlockWriter` in `src/molhub/conveyor/prepare.py` — the single lazily-imported `from molix.store.block import BlockWriter, SamplingUnit` site plus the numpy→torch `SamplingUnit` conversion
- [ ] Declare `numpy` in `[project] dependencies`, add the `prepare` optional-dependency extra and the `molix` `ty` `unresolved-import` override in `pyproject.toml`
- [ ] Add regression example `regressions/streaming-data-tiers-03-conveyor-03-prepare.py` (public API only; ungated fake-writer goldens plus a `MOLNEX_SRC`-gated real-`BlockWriter` parity leg; hard-coded goldens, no third-party runtime)
- [ ] Run full check + test suite

## Testing strategy

Unit tests live under `tests/test_conveyor/`, mirroring `src/molhub/conveyor/`
(`encoder.py` → `test_encoder.py`, `prepare.py` → `test_prepare.py`), with test
classes mirroring types (`TestTHEMolUnitEncoder`, `TestPrepareJob`). Each test
targets a single method. Fixtures are hand-built `HessianRecord` /
`EnergyForceTrajectory` / `TorsionProfile` instances over hand-built molpy
`Frame`s — no HDF5, no network, no torch, no molnex. Coordinates, energies and
forces are multiples of 0.5 so every value is exact in float32 and **no
floating-point tolerance appears anywhere in this spec**.

- `test_encoder.py` — per record type: column set, per-column dtype (`<i2`
  `atom_Z`, `<i4` valence and `mol_target_torsion_atoms`, `<f4` frame columns),
  shapes (`frame_pos` is `(F·N, 3)`), and **hard-coded expected arrays** equal to
  the fixture values unchanged (Å / kcal mol⁻¹ / kcal mol⁻¹ Å⁻¹). Separate
  single-method tests for `identity` (pinned hex literal), the torsion unit's
  `mol_target_torsion_atoms` and `frame_target_torsion_angle`, and the hessian
  unit's geometry-only column set.
- `test_encoder.py` edge cases — molecule with zero bonds (empty bond columns,
  not missing columns); a trajectory whose second frame has a different atom
  count (`IncompleteRecordError`); bonds present without an integer order column
  (`IncompleteRecordError`); `MBISRecord` (`UnsupportedRecordError`).
- `test_prepare.py` — the fake `BlockWriterLike` records `(split, root)` at
  construction, every `append_unit` argument, and writes the five manifest fields
  molhub reads on `seal()`. Single-method tests: whole-unit ingestion (recorded
  objects are `RawUnit`s, per-unit frame counts equal the source records', no key
  twice); split fan-out (5 records over 3 identities → exactly 3 sealed roots
  with pinned unit counts and one `split=` value each); size fan-out
  (`max_block_bytes=1` → one sealed root per unit, deterministic
  `<name>-<split>-<seq>` names, no unit in two blocks); `UnroutableUnitError` for
  an identity absent from `split_of`; `IncompleteProvenanceError` before any
  writer is opened; `BlockFormatError` when a sealed manifest reports
  `sealed: false`, a foreign `format`, or `units` disagreeing with
  `writer.unit_count`; `PreparedBlocks` naming every sealed root with digest,
  split, unit and frame counts; a second `run()` raising.
- `test_layering.py` — AST assertions over `src/molhub/conveyor/*.py`: no
  module-scope `import torch` / `import molix…`; `molhub.dataset` imports no
  `molhub.conveyor`; `numpy` present in the `[project] dependencies` parsed from
  `pyproject.toml` with `tomllib`.

**Regression example.**
`regressions/streaming-data-tiers-03-conveyor-03-prepare.py` — public API only,
two legs. Its first statement asserts `"torch" not in sys.modules` after
`import molhub.conveyor.prepare`, proving the base import path is torch-free.
Leg A (ungated) drives a mixed-split fake shard through `PrepareJob` with an
in-script fake writer and pins literal goldens: three sealed roots, their names,
per-split unit and frame counts, and the fact that the concatenated appended
units reproduce the input records exactly once each. Leg B is gated exactly like
`tests/test_dataset/test_neighbor.py:85-104` (`MOLNEX_SRC` on `sys.path`, then
`importlib.import_module("molix.store.block")`, printing a clear SKIP line and
exiting 0 when molnex is absent): it re-runs the same shard through
`MolnexBlockWriter` into a `TemporaryDirectory`, then reads the blocks back with
`BlockReader` and asserts the same unit counts, one split per manifest, and
`frame_pos` equal bit-for-bit to the encoder's float32 arrays. Every golden is a
literal in the script; no third-party oracle is imported or subprocessed to
produce a value at run time.

## Out of scope

- **The ledger itself** — record format, four-state transitions, crash recovery,
  idempotent re-run policy for a shard whose root already holds sealed blocks
  (`BlockWriter` refuses a dirty root loudly; deciding to skip or delete is the
  ledger's call). Owned by `-01-ledger`, which also opens the chain's
  `.claude/specs/INDEX.md` entry.
- **What to fetch and in what order** — roster, prefetch, digest-at-the-boundary
  (I6). Owned by `-02-roster`.
- **Queue backpressure, byte budgets, leases, refcounted deletion, shard deletion
  after READY** (I3/I4/I9) — owned by the chain's last sub-spec.
- **The block format** — columns, commit protocol, `seal()` semantics, digests.
  Owned by `molnex:.claude/specs/streaming-data-tiers-02-block-format.md`;
  molhub consumes it and reads five manifest fields.
- **Cartesian Hessian and B-matrix storage** — no routable column space in
  `molix.block/1`; the Hessian core is hot-tier by strategy § 6. Named in the
  encoder docstring with its successor.
- **MBIS records** — `MBISRecord` raises `UnsupportedRecordError`; its
  atom-level electrostatics targets need their own column routes.
- **OMol25 / OPoly26 encoders** — one encoder per source; this spec ships the
  THEMol one only.
- **Split production** — `class1-universal-splits@1` is a hot-tier input;
  streaming never re-splits (I7).
- **Any training run** — nothing here is calibration evidence; the molnex
  production-training checklist remains fully binding.
