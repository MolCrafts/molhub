#!/usr/bin/env python
r"""Regression: a THEMol record IS a molpy object, and no encoded column moved.

``hf-facade-02-frame-records`` deleted the four THEMol record dataclasses
(``HessianRecord`` / ``EnergyForceTrajectory`` / ``TorsionProfile`` /
``MBISRecord``) and made the record itself the molpy object: one geometry is a
:class:`molpy.Frame`, one multi-frame sampling unit is a
:class:`molpy.Trajectory`. This script drives that claim through the public
surface only — three synthetic HDF5 shards read back through
:class:`~molhub.dataset.themol.THEMolShardDataset`, then encoded with
:class:`~molhub.conveyor.encoder.THEMolUnitEncoder` — and pins both halves:

* **Records.** A hessian record is a ``Frame`` whose Cartesian Hessian is the
  COO ``hessian{row,col,value}`` block, all ``(3N)**2`` entries in row-major
  order (D1); a torsion scan is a ``Trajectory`` whose per-frame ``meta``
  carries ``energy`` / ``torsion_angle`` / ``scan_id`` / ``constraint_index``
  and whose scanned dihedral is the 1-row ``scan`` block; an MBIS record is a
  ``Frame`` whose fourteen per-atom targets are ``atoms`` columns and whose
  Slater shells — one row per shell, *not* per atom — are the ``mbis_shells``
  block.
* **Encoded columns.** Dissolution changed the record's *container*, never a
  byte the conveyor emits, so the ``RawUnit`` key sets, dtypes and values below
  are the pre-dissolution literals of ``tests/test_conveyor/test_encoder.py``,
  and ``THEMolUnitEncoder(task="mbis")`` is refused at construction.

Determinism: no network, no clock, no environment lookup, no torch and no
molnex (asserted below, right after the imports). The only files touched are
the HDF5 shards this script writes into a :class:`tempfile.TemporaryDirectory`.

Provenance of the goldens (hard-coded literals; nothing is recomputed here):

* Molecular identities (blake2b-128 hex of the mapped isomeric SMILES) and
  ``molecule_id`` values (``uuid5(UUID(int=0), smiles).hex``) were computed once
  offline with the stdlib and pinned. The water identity is the same literal
  ``tests/test_conveyor/test_encoder.py`` and
  ``regressions/streaming-data-tiers-03-conveyor-03-prepare.py`` pin.
  command: ``python -c "import hashlib, uuid; s='[O:2]([H:1])[H:3]';
  print(hashlib.blake2b(s.encode(), digest_size=16).hexdigest(),
  uuid.uuid5(uuid.UUID(int=0), s).hex)"``; CPython 3.12, stdlib only; 2026-08-15.
* The two butane dihedrals ``45.0`` and ``18.43494882292201`` (degrees, about
  atoms ``(0, 1, 2, 3)``) were computed once offline with
  ``molhub.dataset.themol._dihedral_angle`` over the same two geometries this
  script writes, and are the literals ``tests/test_dataset/test_themol.py``
  pins as ``BUTANE_SCAN_ANGLES`` (molpy 0.13.1, numpy 2.x; 2026-08-15).
  Recomputing them here with the same call would assert nothing.
* The MBIS ``parameters`` **shape and column meanings** — ``(S, 3)`` of
  ``(atom index, shell population in e, inverse Slater width in angstrom^-1)``,
  with a variable shell count per atom — come from a one-off offline probe of
  1000 groups of the real published THEMol mbis ``shard-000`` (430906 groups),
  read with h5py; date 2026-08-15. The identity ``sum(population) == Z.sum() -
  charge.sum()`` held exactly on every probed group. Nothing here reads that
  shard: the fixture below is synthetic and hand-picked to satisfy the same
  identity, and the probe is quoted, not repeated.
* Every other number — atom counts, ``(3N)**2`` entry counts, Hessian entries,
  coordinates, energies, charges, dipole and quadrupole components, shell rows —
  is hand-derived from the fixture recipe in this file. All of them are exact in
  binary floating point, so only the arctangent-derived angle needs a
  tolerance.

tool: python
command: python regressions/hf-facade-02-frame-records.py
date: 2026-08-15
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from molhub.dataset import (  # noqa: E402
    THEMolHessian,
    THEMolMBIS,
    THEMolShardDataset,
    THEMolTorsionScan,
)

# ac-007's "no molnex import", made observable rather than asserted in prose:
# the dataset layer speaks molpy and numpy, and the conveyor's encoder is
# torch-free by construction, so a base install with neither torch nor molnex
# can read a shard and encode it.
assert "torch" not in sys.modules, "importing molhub.dataset pulled torch into sys.modules"
assert "molix" not in sys.modules, "importing molhub.dataset pulled molix into sys.modules"

import h5py  # noqa: E402
import numpy as np  # noqa: E402
from molpy import Block, Frame, Trajectory  # noqa: E402

from molhub.conveyor.encoder import RawUnit, THEMolUnitEncoder  # noqa: E402
from molhub.conveyor.errors import UnsupportedRecordError  # noqa: E402

assert "torch" not in sys.modules, "importing molhub.conveyor.encoder pulled torch in"
assert "molix" not in sys.modules, "importing molhub.conveyor.encoder pulled molix in"

# ---------------------------------------------------------------------------
# Species. Three molecules, three identities, one bondless case.
# ---------------------------------------------------------------------------

WATER_SMILES = "[O:2]([H:1])[H:3]"
NEON_SMILES = "[Ne:1]"
BUTANE_SMILES = "[H:1][C:2]([H:5])([H:6])[C:3]([H:7])([H:8])[C:4]([H:9])([H:10])[H:11]"

#: blake2b-128 hex of the mapped isomeric SMILES — the molecular identity a
#: split table is keyed by. See the module docstring for provenance.
WATER_IDENTITY = "810eef0a316c3ae716b15724bd6a8779"
NEON_IDENTITY = "7a8a2304bb79b7d3459719ef0c416aef"
BUTANE_IDENTITY = "5a60b1231fe7559bf5c0f02a7f6dff40"

#: ``uuid5(UUID(int=0), mapped_isomeric_smiles).hex`` — what the reader writes
#: to ``frame.meta["molecule_id"]``, and what a non-scan unit is keyed by.
WATER_MOLECULE_ID = "7164234ff61f524e828d817795c1e285"
NEON_MOLECULE_ID = "ebae5464da5a51439469338db0020df6"

WATER_Z = (1, 8, 1)
#: Atom-map order H:1, O:2, H:3 — deliberately unlike SMILES parse order.
WATER_BOND_ATOMI = (1, 1)
WATER_BOND_ATOMJ = (0, 2)
WATER_BOND_ORDER = (1, 1)
#: Multiples of 0.5, exact in float32, so no positional assertion needs a tolerance.
WATER_POS = ((-0.5, 0.0, 0.0), (0.0, 0.0, 0.0), (0.5, 0.0, 0.0))

BUTANE_N_ATOMS = 11
#: The four scanned atoms of the butane torsion fixture, and the first four
#: coordinates of each of its two geometries (integers — exact in float32).
BUTANE_TORSION_ATOMS = (0, 1, 2, 3)
BUTANE_HEAD_POS = {
    0.0: ((-1.0, 1.0, 0.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 1.0, 1.0)),
    1.0: ((-1.0, 1.0, 1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 1.0, 2.0)),
}

# ---------------------------------------------------------------------------
# Record goldens
# ---------------------------------------------------------------------------

#: The record keys of the hessian shard, in the order h5py yields them.
HESSIAN_RECORD_KEYS = ("record-0-water", "record-1-neon")

#: ``(3N)**2`` COO entries per record: 81 for water (N=3), 9 for neon (N=1).
#: No triangle folding and no sparsity assumption — a DFT Hessian is dense (D1).
HESSIAN_ENTRIES = {"record-0-water": 81, "record-1-neon": 9}

HESSIAN_BLOCK_COLUMNS = frozenset({"row", "col", "value"})

#: The water record's stored Hessian is ``H[i, j] = 0.5 * (9 * i + j)`` —
#: deliberately **asymmetric**, because a symmetric matrix (a physical Hessian,
#: or the identity) cannot tell row-major from column-major apart. These four
#: ``(row, col, value)`` entries at flat positions 0, 1, 9 and 80 are what pins
#: the row-major promise: entry 1 is ``H[0, 1] = 0.5`` while entry 9 is
#: ``H[1, 0] = 4.5``. Every value is a multiple of 0.5, exact in binary.
HESSIAN_SPOT_CHECK = ((0, 0, 0.0), (0, 1, 0.5), (1, 0, 4.5), (8, 8, 40.0))
HESSIAN_SPOT_POSITIONS = (0, 1, 9, 80)

#: A torsion scan is one whole `Trajectory`; this fixture writes two constraints.
SCAN_RECORD_KEY = "scan-record"
SCAN_N_FRAMES = 2
SCAN_ENERGIES = (0.0, -1.0)
SCAN_CONSTRAINT_INDICES = (0, 1)

#: Degrees, about atoms (0, 1, 2, 3). Offline literals — see the module docstring.
BUTANE_SCAN_ANGLES = (45.0, 18.43494882292201)

#: `frame.meta` rejects a len-4 sequence, so the scanned dihedral is a 1-row block.
SCAN_BLOCK_COLUMNS = ("atomi", "atomj", "atomk", "atoml")
SCAN_BLOCK_ROWS = ([0], [1], [2], [3])

#: The atom columns `_mapped_topology_frame` writes for every task. The MBIS
#: supervision columns are pinned as the exact *difference* from this set, so a
#: stray extra column is a failure rather than a silent addition.
GEOMETRY_ATOM_COLUMNS = frozenset({"element", "number", "atom_map", "formal_charge", "x", "y", "z"})

#: The 14 MBIS column names the format fixes — the same set
#: `THEMolMBIS.TARGET_SCHEMA.atom_level` declares. `quadrupole_yx` is a column
#: of its own, not a synonym for `quadrupole_xy`: the lower triangle is unfolded
#: for the same reason the Hessian's is (D1).
MBIS_DECLARED_COLUMNS = frozenset(
    {
        "atomic_charge",
        "atomic_volume",
        "dipole_x",
        "dipole_y",
        "dipole_z",
        "quadrupole_xx",
        "quadrupole_xy",
        "quadrupole_xz",
        "quadrupole_yx",
        "quadrupole_yy",
        "quadrupole_yz",
        "quadrupole_zx",
        "quadrupole_zy",
        "quadrupole_zz",
    }
)

#: The Slater shells are **not** per-atom columns. The source ``parameters``
#: array is ``(S, 3)`` — one row per Slater *shell*, ``(atom index, population,
#: inverse width)`` — with a variable number of shells per atom, so it lands in
#: its own ``mbis_shells`` block and no ``mbis_parameter_<slot>`` column exists.
#: Provenance of the shape and the column meanings: probe of 1000 groups of the
#: real published THEMol mbis shard-000 (430906 groups), 2026-08-15; recorded in
#: full above ``_write_mbis`` in ``tests/test_dataset/test_themol.py``.
MBIS_SHELL_BLOCK = "mbis_shells"
MBIS_SHELL_BLOCK_COLUMNS = ("atom", "population", "inverse_width")
MBIS_PARAMETER_PREFIX = "mbis_parameter"

#: Charges sum to zero and every component is exact in binary floating point;
#: they are synthetic doubles, not real-data truth. The oxygen's ``-0.5`` is the
#: literal charge pinned below.
MBIS_CHARGES = (0.25, -0.5, 0.25)
MBIS_VOLUMES = (2.0, 4.0, 2.0)
MBIS_DIPOLE = (
    (0.125, 0.25, 0.375),
    (1.125, 1.25, 1.375),
    (2.125, 2.25, 2.375),
)
#: ``source[a, i, j] = 10 * a + 3 * i + j + 0.5``, deliberately asymmetric so the
#: ``(i, j) -> column`` mapping is observable at all.
MBIS_QUADRUPOLE_XX = (0.5, 10.5, 20.5)
MBIS_QUADRUPOLE_XY = (1.5, 11.5, 21.5)
MBIS_QUADRUPOLE_YX = (3.5, 13.5, 23.5)
MBIS_QUADRUPOLE_ZZ = (8.5, 18.5, 28.5)

#: The water record's four Slater shells as source rows ``(atom index,
#: population, inverse width)``. Atom-map order is H:1, O:2, H:3, so atom 1 is
#: the oxygen and it is the one carrying two shells (core, then valence) while
#: each hydrogen carries one — four rows for three atoms, which is the shape a
#: per-atom reader cannot represent. Every literal is exact in binary floating
#: point, and the populations are chosen so the probed identity holds on the
#: fixture: ``sum(population) == Z.sum() - charge.sum()`` == 10.0 - 0.0 == 10.0.
#: The per-shell split is synthetic; the total is the probed fact.
MBIS_SHELL_ROWS = ((0.0, 0.5, 3.25), (1.0, 2.0, 32.0), (1.0, 6.5, 6.75), (2.0, 1.0, 3.5))
MBIS_SHELL_ATOMS = (0, 1, 1, 2)
MBIS_SHELL_POPULATIONS = (0.5, 2.0, 6.5, 1.0)
MBIS_SHELL_WIDTHS = (3.25, 32.0, 6.75, 3.5)
MBIS_ELECTRON_COUNT = 10.0

# ---------------------------------------------------------------------------
# Encoder goldens — copied literal for literal from the pre-dissolution
# assertions in `tests/test_conveyor/test_encoder.py`.
# ---------------------------------------------------------------------------

#: The four columns a bonded molecule declares; a bondless one declares the same
#: four, empty, because a block freezes its schema on its first unit.
TOPOLOGY_COLUMNS = frozenset({"Z", "bond_atomi", "bond_atomj", "bond_type"})
HESSIAN_UNIT_FRAME_COLUMNS = frozenset({"pos"})
SCAN_UNIT_TOPOLOGY_COLUMNS = TOPOLOGY_COLUMNS | {"torsion_atoms"}
SCAN_UNIT_FRAME_COLUMNS = frozenset({"pos", "energy", "forces", "torsion_angle"})

#: float32 rounding of the arctangent-derived angle: |f32(18.43494882292201) -
#: 18.43494882292201| is about 9e-7. Everything else in this script is exact.
_ANGLE_F32_ATOL = 1e-5


# ---------------------------------------------------------------------------
# Fixture construction — synthetic THEMol HDF5 shards, one role each
# ---------------------------------------------------------------------------


def _identity(group: h5py.Group, smiles: str, numbers: Sequence[int]) -> None:
    """Write the three identity datasets every THEMol record group carries."""
    string = h5py.string_dtype("utf-8")
    group.create_dataset("mapped_nonisomeric_smiles", data=smiles, dtype=string)
    group.create_dataset("mapped_isomeric_smiles", data=smiles, dtype=string)
    group.create_dataset("atomic_numbers", data=np.asarray(numbers, dtype=np.int32)[:, None])


def _butane_coords(angle_shift: float) -> np.ndarray:
    """The torsion fixture's geometry, dihedral(0, 1, 2, 3) set by *angle_shift*.

    Atoms 0-3 are the scanned dihedral; the remaining seven are inert filler far
    from it, so the angle depends on *angle_shift* alone.
    """
    coords = np.zeros((BUTANE_N_ATOMS, 3), dtype=np.float64)
    coords[:4] = np.asarray(
        [
            [-1.0, 1.0, angle_shift],
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 1.0, 1.0 + angle_shift],
        ]
    )
    coords[4:] = np.arange(21, dtype=np.float64).reshape(7, 3) * 0.01 + 3.0
    return coords


def _hessian_dataset(root: Path) -> THEMolShardDataset[Frame]:
    """A two-record hessian shard: bonded water, then a bondless neon atom."""
    root.mkdir(parents=True, exist_ok=True)
    with h5py.File(root / "shard-000.h5", "w") as handle:
        water = handle.create_group(HESSIAN_RECORD_KEYS[0])
        _identity(water, WATER_SMILES, WATER_Z)
        water.create_dataset("coords", data=np.asarray(WATER_POS, dtype=np.float64))
        # H[i, j] = 0.5 * (9 * i + j): asymmetric, so row-major is observable.
        water.create_dataset("hessian", data=(np.arange(81, dtype=np.float64) * 0.5).reshape(9, 9))

        neon = handle.create_group(HESSIAN_RECORD_KEYS[1])
        _identity(neon, NEON_SMILES, (10,))
        neon.create_dataset("coords", data=np.zeros((1, 3), dtype=np.float64))
        neon.create_dataset("hessian", data=np.eye(3, dtype=np.float64))
    return THEMolHessian(root).load()


def _torsion_dataset(root: Path) -> THEMolShardDataset[Trajectory]:
    """A one-record torsion-scan shard: one whole two-constraint butane profile."""
    root.mkdir(parents=True, exist_ok=True)
    with h5py.File(root / "shard-000.h5", "w") as handle:
        group = handle.create_group(SCAN_RECORD_KEY)
        _identity(group, BUTANE_SMILES, (1, 6, 6, 6, 1, 1, 1, 1, 1, 1, 1))
        group.create_dataset(
            "torsion_atom_indices", data=np.asarray(BUTANE_TORSION_ATOMS, dtype=np.int32)
        )
        for index, shift in enumerate(BUTANE_HEAD_POS):
            constraint = group.create_group(f"constraint {index}")
            coords = _butane_coords(shift)
            constraint.create_dataset("coords", data=coords)
            constraint.create_dataset("energy", data=np.asarray(SCAN_ENERGIES[index]))
            constraint.create_dataset("forces", data=np.zeros_like(coords))
    return THEMolTorsionScan(root).load()


def _mbis_dataset(root: Path) -> THEMolShardDataset[Frame]:
    """A one-record MBIS shard: water, with per-atom electrostatics supervision."""
    root.mkdir(parents=True, exist_ok=True)
    quadrupole = (
        np.arange(9, dtype=np.float64).reshape(1, 3, 3)
        + np.asarray([0.0, 10.0, 20.0], dtype=np.float64).reshape(3, 1, 1)
        + 0.5
    )
    with h5py.File(root / "shard-000.h5", "w") as handle:
        group = handle.create_group("mbis-record")
        _identity(group, WATER_SMILES, WATER_Z)
        group.create_dataset("coords", data=np.asarray(WATER_POS, dtype=np.float64))
        info = group.create_group("mbis_info")
        info.create_dataset("atomic_charge", data=np.asarray(MBIS_CHARGES)[:, None])
        info.create_dataset("atomic_volumes", data=np.asarray(MBIS_VOLUMES)[:, None])
        info.create_dataset("atomic_dipole", data=np.asarray(MBIS_DIPOLE, dtype=np.float64))
        info.create_dataset("atomic_quadrupole", data=quadrupole)
        group.create_dataset("parameters", data=np.asarray(MBIS_SHELL_ROWS, dtype=np.float64))
    return THEMolMBIS(root).load()


def _column(block: Block, name: str) -> np.ndarray:
    """One block column as a numpy array — the only shape adapter this file needs."""
    return np.asarray(block[name])


# ---------------------------------------------------------------------------
# Leg 1 — one geometry is a `molpy.Frame` carrying a COO `hessian` block
# ---------------------------------------------------------------------------


def check_hessian_records(dataset: THEMolShardDataset[Frame]) -> None:
    """A hessian record IS a Frame; its Hessian is all ``(3N)**2`` entries, row-major."""
    assert isinstance(dataset, THEMolShardDataset)
    assert len(dataset) == 2, f"expected two records in the shard, got {len(dataset)}"

    water, neon = dataset[0], dataset[1]
    assert isinstance(water, Frame), f"a hessian record is a molpy Frame, got {type(water)}"
    assert isinstance(neon, Frame)

    # -- the frame keeps its topology and provenance -------------------------
    assert _column(water["atoms"], "number").tolist() == list(WATER_Z)
    assert _column(water["atoms"], "atom_map").tolist() == [1, 2, 3]
    assert _column(water["bonds"], "atomi").tolist() == list(WATER_BOND_ATOMI)
    assert _column(water["bonds"], "atomj").tolist() == list(WATER_BOND_ATOMJ)
    assert water.meta["molecule_id"] == WATER_MOLECULE_ID
    assert water.meta["source_record_id"] == HESSIAN_RECORD_KEYS[0]
    assert water.meta["mapped_isomeric_smiles"] == WATER_SMILES
    assert water.meta["total_charge"] == 0
    assert neon.meta["molecule_id"] == NEON_MOLECULE_ID
    assert "bonds" not in neon, "a bare noble-gas atom has zero bonds, and no bond block"

    # -- the Hessian is a block, not a meta scalar ---------------------------
    block = water["hessian"]
    assert frozenset(block.keys()) == HESSIAN_BLOCK_COLUMNS
    rows = _column(block, "row")
    cols = _column(block, "col")
    values = _column(block, "value")
    count = HESSIAN_ENTRIES[HESSIAN_RECORD_KEYS[0]]
    assert (rows.shape, cols.shape, values.shape) == ((count,), (count,), (count,))
    assert [rows.dtype.str, cols.dtype.str, values.dtype.str] == ["<i4", "<i4", "<f8"]
    assert _column(neon["hessian"], "value").shape == (HESSIAN_ENTRIES[HESSIAN_RECORD_KEYS[1]],)

    # -- row-major, pinned entry by entry ------------------------------------
    entries = [
        (int(rows[position]), int(cols[position]), float(values[position]))
        for position in HESSIAN_SPOT_POSITIONS
    ]
    assert entries == list(HESSIAN_SPOT_CHECK), f"the Hessian block is not row-major: {entries}"

    print(
        f"  Records/hessian: {len(dataset)} molpy Frames, entries "
        f"{ {key: HESSIAN_ENTRIES[key] for key in HESSIAN_RECORD_KEYS} } = (3N)**2, "
        f"row-major spot check {entries}, bondless neon carries no bond block"
    )


# ---------------------------------------------------------------------------
# Leg 2 — one whole scan is a `molpy.Trajectory`, scalars in per-frame `meta`
# ---------------------------------------------------------------------------


def check_torsion_records(dataset: THEMolShardDataset[Trajectory]) -> None:
    """A torsion profile IS a Trajectory; its dihedral is the 1-row ``scan`` block."""
    assert len(dataset) == 1
    record = dataset[0]
    assert isinstance(record, Trajectory), (
        f"a torsion scan is a molpy Trajectory, got {type(record)}"
    )
    assert len(record) == SCAN_N_FRAMES

    frames = [record[index] for index in range(SCAN_N_FRAMES)]
    assert [frame.meta["scan_id"] for frame in frames] == [SCAN_RECORD_KEY] * SCAN_N_FRAMES
    assert [frame.meta["constraint_index"] for frame in frames] == list(SCAN_CONSTRAINT_INDICES)
    assert [frame.meta["energy"] for frame in frames] == list(SCAN_ENERGIES)
    assert frames[0].meta["molecule_id"] != frames[0].meta["scan_id"], (
        "a scan id is not a molecular identity"
    )

    angles: list[float] = []
    for frame in frames:
        angle = frame.meta["torsion_angle"]
        assert isinstance(angle, float), f"molpy hands back a plain float, got {type(angle)}"
        angles.append(angle)
    assert [abs(got - want) <= 1e-9 for got, want in zip(angles, BUTANE_SCAN_ANGLES)] == [
        True,
        True,
    ], f"the per-frame torsion angles drifted: {angles}"

    for frame in frames:
        block = frame["scan"]
        assert frozenset(block.keys()) == frozenset(SCAN_BLOCK_COLUMNS)
        assert [_column(block, name).tolist() for name in SCAN_BLOCK_COLUMNS] == [
            list(row) for row in SCAN_BLOCK_ROWS
        ], "every frame of a scan carries the same 1-row scan block"

    # Each frame keeps *its own* geometry through the eager Trajectory copy.
    for frame, shift in zip(frames, BUTANE_HEAD_POS):
        head = np.column_stack([_column(frame["atoms"], name) for name in ("x", "y", "z")])[:4]
        assert head.tolist() == [list(row) for row in BUTANE_HEAD_POS[shift]]

    print(
        f"  Records/torsion-scan: one molpy Trajectory of {len(record)} frames, angles "
        f"{angles} deg (atol 1e-9), energies {list(SCAN_ENERGIES)}, scan block "
        f"{SCAN_BLOCK_COLUMNS} = {[list(row) for row in SCAN_BLOCK_ROWS]}"
    )


# ---------------------------------------------------------------------------
# Leg 3 — MBIS supervision is `atoms` columns of one `molpy.Frame`
# ---------------------------------------------------------------------------


def check_mbis_records(dataset: THEMolShardDataset[Frame]) -> None:
    """An MBIS record IS a Frame: per-atom targets in ``atoms``, shells in a block."""
    assert len(dataset) == 1
    record = dataset[0]
    assert isinstance(record, Frame), f"an MBIS record is a molpy Frame, got {type(record)}"

    atoms = record["atoms"]
    columns = frozenset(atoms.keys())
    assert columns == GEOMETRY_ATOM_COLUMNS | MBIS_DECLARED_COLUMNS, (
        f"the MBIS atom columns drifted: {sorted(columns)}"
    )
    assert not [name for name in columns if name.startswith(MBIS_PARAMETER_PREFIX)], (
        "a per-atom Slater parameter column is back; the source array is per shell"
    )
    assert MBIS_DECLARED_COLUMNS == THEMolMBIS.TARGET_SCHEMA.atom_level, (
        "the frame's fixed MBIS columns and the declared schema disagree"
    )

    charges = _column(atoms, "atomic_charge")
    assert charges.shape == (3,), "the (N, 1) source becomes one (N,) column"
    assert float(charges[1]) == -0.5, "the oxygen's pinned MBIS charge"
    assert charges.tolist() == list(MBIS_CHARGES)
    assert _column(atoms, "atomic_volume").tolist() == list(MBIS_VOLUMES)

    assert [_column(atoms, name).tolist() for name in ("dipole_x", "dipole_y", "dipole_z")] == [
        list(component) for component in zip(*MBIS_DIPOLE)
    ]

    # `quadrupole_yx` is its own column: the lower triangle is unfolded, not folded.
    assert _column(atoms, "quadrupole_xx").tolist() == list(MBIS_QUADRUPOLE_XX)
    assert _column(atoms, "quadrupole_xy").tolist() == list(MBIS_QUADRUPOLE_XY)
    assert _column(atoms, "quadrupole_yx").tolist() == list(MBIS_QUADRUPOLE_YX)
    assert _column(atoms, "quadrupole_zz").tolist() == list(MBIS_QUADRUPOLE_ZZ)

    # -- the Slater shells are a block of their own, one row per shell ---------
    shells = record[MBIS_SHELL_BLOCK]
    assert frozenset(shells.keys()) == frozenset(MBIS_SHELL_BLOCK_COLUMNS)
    assert [_column(shells, name).shape for name in MBIS_SHELL_BLOCK_COLUMNS] == [
        (len(MBIS_SHELL_ROWS),)
    ] * 3, "four shells for three atoms: the block is per shell, not per atom"
    assert [_column(shells, name).dtype.str for name in MBIS_SHELL_BLOCK_COLUMNS] == [
        "<i4",
        "<f8",
        "<f8",
    ]
    assert _column(shells, "atom").tolist() == list(MBIS_SHELL_ATOMS), (
        "the shell atom index column is not the source's, in source order"
    )
    assert _column(shells, "population").tolist() == list(MBIS_SHELL_POPULATIONS)
    assert _column(shells, "inverse_width").tolist() == list(MBIS_SHELL_WIDTHS)

    # The probed identity, embedded in the fixture: the shell populations are
    # electrons, so they add up to the record's electron count.
    populations = _column(shells, "population").astype(np.float64)
    electrons = float(_column(atoms, "number").sum()) - float(charges.sum())
    assert float(populations.sum()) == MBIS_ELECTRON_COUNT
    assert float(populations.sum()) == electrons, (
        f"shell populations {populations.tolist()} do not sum to Z.sum() - charge.sum() "
        f"= {electrons}"
    )

    # The block is declared as one, so a reader is told where to look for it.
    assert THEMolMBIS.manifest.blocks == (MBIS_SHELL_BLOCK,), (
        f"the MBIS block declaration drifted: {THEMolMBIS.manifest.blocks}"
    )

    print(
        f"  Records/mbis: one molpy Frame, {len(MBIS_DECLARED_COLUMNS)} declared atom columns "
        f"and no mbis_parameter_* column, oxygen charge {float(charges[1])} e, quadrupole_yx "
        f"{list(MBIS_QUADRUPOLE_YX)} != quadrupole_xy {list(MBIS_QUADRUPOLE_XY)}; "
        f"{MBIS_SHELL_BLOCK} block {MBIS_SHELL_BLOCK_COLUMNS} = {len(MBIS_SHELL_ROWS)} shells "
        f"over 3 atoms, atoms {list(MBIS_SHELL_ATOMS)}, populations "
        f"{list(MBIS_SHELL_POPULATIONS)} summing to {MBIS_ELECTRON_COUNT} electrons"
    )


# ---------------------------------------------------------------------------
# Leg 4 — the encoder over the same records: not one column moved
# ---------------------------------------------------------------------------


def check_encoded_columns(
    hessian: THEMolShardDataset[Frame], torsion: THEMolShardDataset[Trajectory]
) -> None:
    """The pre-dissolution ``RawUnit`` goldens, over records that are now molpy objects."""
    water = THEMolUnitEncoder(task="hessian").encode(hessian[0])
    neon = THEMolUnitEncoder(task="hessian").encode(hessian[1])
    scan = THEMolUnitEncoder(task="torsion-scan").encode(torsion[0])
    assert all(isinstance(unit, RawUnit) for unit in (water, neon, scan))

    # -- a Frame record: one unit, keyed by molecule_id, geometry columns only
    assert water.key == WATER_MOLECULE_ID
    assert water.identity == WATER_IDENTITY
    assert water.task == "hessian"
    assert frozenset(water.topology) == TOPOLOGY_COLUMNS, (
        "the frame's hessian block is offered and deliberately dropped"
    )
    assert frozenset(water.frames) == HESSIAN_UNIT_FRAME_COLUMNS
    assert (water.n_atoms, water.n_frames) == (3, 1)
    assert water.topology["Z"].dtype.str == "<i2"
    assert water.topology["Z"].tolist() == list(WATER_Z)
    assert [
        water.topology[name].dtype.str for name in ("bond_atomi", "bond_atomj", "bond_type")
    ] == ["<i4", "<i4", "<i4"]
    assert water.topology["bond_atomi"].tolist() == list(WATER_BOND_ATOMI)
    assert water.topology["bond_atomj"].tolist() == list(WATER_BOND_ATOMJ)
    assert water.topology["bond_type"].tolist() == list(WATER_BOND_ORDER)
    assert water.frames["pos"].dtype.str == "<f4"
    assert water.frames["pos"].tolist() == [list(row) for row in WATER_POS]

    # -- a bondless molecule declares the same four columns, empty ------------
    assert neon.identity == NEON_IDENTITY
    assert frozenset(neon.topology) == TOPOLOGY_COLUMNS
    assert (neon.n_atoms, neon.n_frames) == (1, 1)
    assert neon.topology["Z"].tolist() == [10]
    for name in ("bond_atomi", "bond_atomj", "bond_type"):
        assert neon.topology[name].shape == (0,)
        assert neon.topology[name].dtype.str == "<i4"

    # -- a Trajectory record: one whole scan, keyed by scan_id ----------------
    assert scan.key == SCAN_RECORD_KEY
    assert scan.identity == BUTANE_IDENTITY, "a scan's identity is its molecule, not its scan"
    assert scan.identity != THEMolUnitEncoder.identity(SCAN_RECORD_KEY)
    assert scan.task == "torsion-scan"
    assert frozenset(scan.topology) == SCAN_UNIT_TOPOLOGY_COLUMNS
    assert frozenset(scan.frames) == SCAN_UNIT_FRAME_COLUMNS
    assert (scan.n_atoms, scan.n_frames) == (BUTANE_N_ATOMS, SCAN_N_FRAMES)

    torsion_atoms = scan.topology["torsion_atoms"]
    assert torsion_atoms.dtype.str == "<i4"
    assert torsion_atoms.shape == (1, 4)
    assert torsion_atoms.tolist() == [list(BUTANE_TORSION_ATOMS)]

    positions = scan.frames["pos"]
    assert positions.dtype.str == "<f4"
    assert positions.shape == (BUTANE_N_ATOMS * SCAN_N_FRAMES, 3)
    for index, shift in enumerate(BUTANE_HEAD_POS):
        head = positions[index * BUTANE_N_ATOMS : index * BUTANE_N_ATOMS + 4]
        assert head.tolist() == [list(row) for row in BUTANE_HEAD_POS[shift]]

    forces = scan.frames["forces"]
    assert forces.dtype.str == "<f4"
    assert forces.shape == (BUTANE_N_ATOMS * SCAN_N_FRAMES, 3)
    assert not forces.any(), "the fixture's forces are exactly zero"

    energies = scan.frames["energy"]
    assert energies.dtype.str == "<f4"
    assert energies.tolist() == list(SCAN_ENERGIES)

    angles = scan.frames["torsion_angle"]
    assert angles.dtype.str == "<f4"
    assert [
        abs(float(got) - want) <= _ANGLE_F32_ATOL for got, want in zip(angles, BUTANE_SCAN_ANGLES)
    ] == [True, True], f"the encoded torsion angles drifted: {angles.tolist()}"

    print(
        f"  Encoder: topology {sorted(TOPOLOGY_COLUMNS)} / frames "
        f"{sorted(HESSIAN_UNIT_FRAME_COLUMNS)} for a Frame record, topology "
        f"{sorted(SCAN_UNIT_TOPOLOGY_COLUMNS)} / frames {sorted(SCAN_UNIT_FRAME_COLUMNS)} for a "
        f"Trajectory scan, keys {(water.key, scan.key)}, identities "
        f"{(water.identity, scan.identity)}"
    )


def check_mbis_encoding_is_refused_at_construction() -> None:
    """One shard is one task, so the unroutable subset is refused where it is named.

    After dissolution an MBIS frame and a hessian frame are the same type, so a
    per-record refusal would be both later (a writer is already open) and weaker.
    """
    try:
        THEMolUnitEncoder(task="mbis")
    except UnsupportedRecordError as error:
        message = str(error)
        assert "molix.block/1" in message, "the refusal must name the missing column routes"
    else:  # pragma: no cover - the refusal is the point of this leg
        raise AssertionError("THEMolUnitEncoder(task='mbis') was constructed; it must be refused")

    # The routable tasks still construct, so the refusal is about MBIS and not
    # about construction having become impossible.
    for task in ("hessian", "hessian-relax", "torsion-scan", "torsion-relax"):
        assert THEMolUnitEncoder(task=task) is not None

    print(
        "  Encoder/mbis: THEMolUnitEncoder(task='mbis') raises UnsupportedRecordError at "
        "construction, naming molix.block/1; the four routable tasks still construct"
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="molhub-hf-facade-02-") as workdir:
        root = Path(workdir)
        hessian = _hessian_dataset(root / "hessian")
        torsion = _torsion_dataset(root / "torsion-scan")
        mbis = _mbis_dataset(root / "mbis")

        check_hessian_records(hessian)
        check_torsion_records(torsion)
        check_mbis_records(mbis)
        check_encoded_columns(hessian, torsion)
        check_mbis_encoding_is_refused_at_construction()

        for dataset in (hessian, torsion, mbis):
            dataset.close()

    print("hf-facade-02-frame-records: OK")


if __name__ == "__main__":
    main()
