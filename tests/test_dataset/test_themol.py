"""Offline structural tests for grouped THEMol HDF5 adapters."""

from __future__ import annotations

import pickle
from collections.abc import Mapping, Sequence
from pathlib import Path

import h5py
import numpy as np
import pytest
from molpy import Block, Frame, Trajectory

from molhub.dataset import (
    THEMolHessian,
    THEMolHessianRelax,
    THEMolMBIS,
    THEMolTorsionRelax,
    THEMolTorsionScan,
)
from molhub.dataset.gaff2 import Gaff2LennardJones
from molhub.dataset.themol import GAFF2_UNITS, THEMOL_UNITS
from molhub.dataset.themol_format import _mapped_topology_frame
from molhub.loader.info import Feature

WATER = "[O:2]([H:1])[H:3]"
BUTANE = "[H:1][C:2]([H:5])([H:6])[C:3]([H:7])([H:8])[C:4]([H:9])([H:10])[H:11]"
NEON = "[Ne:1]"
#: Methyl carbon 1, ring carbons 2-7, methyl hydrogens 8-10, ring hydrogens 11-15.
TOLUENE = (
    "[C:1]([H:8])([H:9])([H:10])[c:2]1[c:3]([H:11])[c:4]([H:12])[c:5]([H:13])"
    "[c:6]([H:14])[c:7]1[H:15]"
)
TOLUENE_NUMBERS = (6,) * 7 + (1,) * 8
AMMONIUM = "[N+:1]([H:2])([H:3])([H:4])[H:5]"
SILANE = "[Si:1]([H:2])([H:3])([H:4])[H:5]"


def _identity(group: h5py.Group, smiles: str, numbers: list[int]) -> None:
    string = h5py.string_dtype("utf-8")
    group.create_dataset("mapped_nonisomeric_smiles", data=smiles, dtype=string)
    group.create_dataset("mapped_isomeric_smiles", data=smiles, dtype=string)
    group.create_dataset("atomic_numbers", data=np.asarray(numbers, dtype=np.int32)[:, None])


def _water_coords() -> np.ndarray:
    # Atom-map order H:1, O:2, H:3, deliberately unlike SMILES parse order.
    return np.asarray(
        [[-0.7, 0.0, 0.0], [0.0, 0.0, 0.0], [0.7, 0.0, 0.0]],
        dtype=np.float64,
    )


def _butane_coords(angle_shift: float = 0.0) -> np.ndarray:
    coords = np.zeros((11, 3), dtype=np.float64)
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


def _write_hessian(
    path: Path,
    *,
    smiles: str = WATER,
    numbers: Sequence[int] = (1, 8, 1),
    coords: np.ndarray | None = None,
    hessian: np.ndarray | None = None,
) -> None:
    """Write one equilibrium record; the defaults are water with an identity Hessian.

    The keyword overrides are additive: called with none of them this writes
    exactly the shard every pre-existing test in this file already reads.
    """
    with h5py.File(path, "w") as handle:
        group = handle.create_group("eq-record")
        _identity(group, smiles, list(numbers))
        group.create_dataset("coords", data=_water_coords() if coords is None else coords)
        group.create_dataset(
            "hessian",
            data=np.eye(3 * len(numbers), dtype=np.float64) if hessian is None else hessian,
        )


def _write_two_record_hessian(path: Path, keys: Sequence[str]) -> None:
    """Write one equilibrium shard holding one water record per key in *keys*.

    ``_write_hessian`` opens the file with mode ``"w"``, so it cannot be called
    twice for two records; this reuses its two building blocks (``_identity``
    and ``_water_coords``) over a caller-named key list instead.
    """
    with h5py.File(path, "w") as handle:
        for key in keys:
            group = handle.create_group(key)
            _identity(group, WATER, [1, 8, 1])
            group.create_dataset("coords", data=_water_coords())
            group.create_dataset("hessian", data=np.eye(9, dtype=np.float64))


def _write_molecule_shard(path: Path, smiles_per_key: Mapping[str, str | None]) -> None:
    """Write one equilibrium record per key, each naming its own molecule.

    ``None`` writes a record with **no** ``mapped_nonisomeric_smiles`` at all,
    which is the only way to reach ``molecule_index``'s refusal.
    """
    with h5py.File(path, "w") as handle:
        for key, smiles in smiles_per_key.items():
            group = handle.create_group(key)
            if smiles is None:
                group.create_dataset("atomic_numbers", data=np.asarray([1, 8, 1], dtype=np.int32))
            else:
                _identity(group, smiles, [1, 8, 1])
            group.create_dataset("coords", data=_water_coords())
            group.create_dataset("hessian", data=np.eye(9, dtype=np.float64))


def _write_hessian_relax(path: Path) -> None:
    with h5py.File(path, "w") as handle:
        group = handle.create_group("relax-record")
        _identity(group, WATER, [1, 8, 1])
        for index, energy in enumerate((-10.0, -10.5)):
            step = group.create_group(f"step {index}")
            step.create_dataset("coords", data=_water_coords() + index * 0.01)
            step.create_dataset("energy", data=np.asarray(energy))
            step.create_dataset("forces", data=np.full((3, 3), index + 1.0))


def _write_torsion(path: Path, *, relax: bool) -> None:
    with h5py.File(path, "w") as handle:
        group = handle.create_group("scan-record")
        _identity(group, BUTANE, [1, 6, 6, 6, 1, 1, 1, 1, 1, 1, 1])
        group.create_dataset("torsion_atom_indices", data=np.arange(4, dtype=np.int32))
        for constraint_index in range(2):
            constraint = group.create_group(f"constraint {constraint_index}")
            if relax:
                coords = np.stack(
                    [_butane_coords(constraint_index + step_index * 0.1) for step_index in range(2)]
                )
                constraint.create_dataset("coords", data=coords)
                constraint.create_dataset(
                    "energy", data=np.asarray([constraint_index + 0.1, constraint_index])
                )
                constraint.create_dataset("forces", data=np.zeros_like(coords))
            else:
                coords = _butane_coords(float(constraint_index))
                constraint.create_dataset("coords", data=coords)
                constraint.create_dataset("energy", data=np.asarray(-constraint_index))
                constraint.create_dataset("forces", data=np.zeros_like(coords))


# ---------------------------------------------------------------------------
# The MBIS Slater shells — what the real `parameters` array actually is.
#
# It is **not** per atom. Probed on 2026-08-15 over 1000 groups of the real
# published THEMol mbis shard-000 (430906 groups in total): `parameters` is
# `(S, 3)` where S is the record's total Slater **shell** count, and the shells
# per atom vary — H carries 1, most heavy atoms 2, a third-period atom can carry
# 3. A 47-atom record has 70 rows, a 40-atom one 57, and only 559 of the 1000
# probed groups happen to satisfy `S == n_atoms + n_heavy`. Reading the array as
# a per-atom `(N, arity)` block refuses every real record: 0 of 43 sampled
# indices were readable.
#
# The three columns, decoded from the same probe:
#
#   col0  atom index — integer-valued, inside `[0, n_atoms)`, the shells of one
#         atom consecutive, and every atom present at least once.
#   col1  shell population, in electrons. `sum(col1) == Z.sum() - charge.sum()`
#         held EXACTLY on every probed group (170 / 132 / 128 for three of them).
#   col2  inverse Slater width, in angstrom^-1 — the unit
#         `THEMOL_UNITS["inverse_sigma"]` already declares. Core shells land at
#         ~24-67, valence shells at ~3-8.
# ---------------------------------------------------------------------------

#: The fixture's water shells as source rows `(atom index, population, inverse
#: width)`. Mapped-atom order is H:1, O:2, H:3, so atom 1 is the oxygen and it is
#: the one carrying two shells (core, then valence) while each H carries one —
#: S = 4 for N = 3, which is the whole point. Every literal is exact in binary
#: floating point, and the populations are picked so the probed sum rule holds on
#: the fixture itself: 0.5 + 2.0 + 6.5 + 1.0 == 10.0 == Z.sum() (1 + 8 + 1) minus
#: this fixture's charge sum (exactly 0.0). How a molecule *divides* that total
#: between its shells is synthetic here — the probe pinned the total, and the two
#: hydrogens are deliberately given different populations so row order is
#: observable at all.
MBIS_SHELL_ROWS = np.asarray(
    [
        [0.0, 0.5, 3.25],
        [1.0, 2.0, 32.0],
        [1.0, 6.5, 6.75],
        [2.0, 1.0, 3.5],
    ],
    dtype=np.float64,
)

#: The same four rows, column by column, as the block goldens.
MBIS_SHELL_ATOMS = (0, 1, 1, 2)
MBIS_SHELL_POPULATIONS = (0.5, 2.0, 6.5, 1.0)
MBIS_SHELL_WIDTHS = (3.25, 32.0, 6.75, 3.5)

#: `Z.sum() - charge.sum()` for the water fixture, which is what its shell
#: populations must add up to. Both sides are exact in binary floating point.
MBIS_ELECTRON_COUNT = 10.0

#: The named block the shells land in, and its three columns.
MBIS_SHELL_BLOCK = "mbis_shells"
MBIS_SHELL_BLOCK_COLUMNS = ("atom", "population", "inverse_width")

# Four defective shell tables, one per refusal. Each has exactly `n_atoms` rows,
# so a reader that still treats `parameters` as a per-atom `(N, arity)` array
# accepts every one of them without a word.
MBIS_SHELLS_WITHOUT_THREE_COLUMNS = np.asarray(
    [[0.0, 0.5], [1.0, 8.5], [2.0, 1.0]], dtype=np.float64
)
MBIS_SHELLS_WITH_A_FRACTIONAL_ATOM_INDEX = np.asarray(
    [[0.0, 0.5, 3.25], [0.5, 8.5, 32.0], [2.0, 1.0, 3.5]], dtype=np.float64
)
MBIS_SHELLS_WITH_AN_OUT_OF_RANGE_ATOM_INDEX = np.asarray(
    [[0.0, 0.5, 3.25], [1.0, 8.5, 32.0], [3.0, 1.0, 3.5]], dtype=np.float64
)
MBIS_SHELLS_LEAVING_AN_ATOM_WITHOUT_A_SHELL = np.asarray(
    [[0.0, 0.5, 3.25], [1.0, 2.0, 32.0], [1.0, 7.5, 6.75]], dtype=np.float64
)


def _write_mbis(
    path: Path,
    *,
    atomic_volumes: np.ndarray | None = None,
    atomic_charge: np.ndarray | None = None,
    atomic_dipole: np.ndarray | None = None,
    atomic_quadrupole: np.ndarray | None = None,
    parameters: np.ndarray | None = None,
) -> None:
    """Write one MBIS record; the defaults are the shard this file already reads.

    Every default is an arbitrary synthetic double, not real-data truth — in
    particular ``atomic_dipole`` / ``atomic_quadrupole`` are ``np.ones``, whose
    components are indistinguishable from one another. The keyword overrides
    exist so a test that needs to tell one component (or one row) from another
    can say so locally instead of changing what the other tests read.

    ``parameters`` is the one array here that is **not** per atom: it is
    :data:`MBIS_SHELL_ROWS`, one row per Slater *shell*, four rows for this
    three-atom molecule. The per-atom ``(N, arity)`` default this builder shipped
    before was a shape no published record has (see the block comment above), and
    it is what made every real record unreadable.
    """
    with h5py.File(path, "w") as handle:
        group = handle.create_group("mbis-record")
        _identity(group, WATER, [1, 8, 1])
        group.create_dataset("coords", data=_water_coords())
        info = group.create_group("mbis_info")
        info.create_dataset(
            "atomic_volumes", data=np.ones((3, 1)) if atomic_volumes is None else atomic_volumes
        )
        info.create_dataset(
            "atomic_charge",
            data=np.asarray([[0.4], [-0.8], [0.4]]) if atomic_charge is None else atomic_charge,
        )
        info.create_dataset(
            "atomic_dipole", data=np.ones((3, 3)) if atomic_dipole is None else atomic_dipole
        )
        info.create_dataset(
            "atomic_quadrupole",
            data=np.ones((3, 3, 3)) if atomic_quadrupole is None else atomic_quadrupole,
        )
        group.create_dataset(
            "parameters",
            data=MBIS_SHELL_ROWS if parameters is None else parameters,
        )


class TestHessian:
    def test_topology_is_reordered_to_atom_map(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_hessian(path)
        dataset = THEMolHessian(path).load()
        record = dataset[0][0]
        assert list(record["atoms"]["number"]) == [1, 8, 1]
        assert list(record["atoms"]["atom_map"]) == [1, 2, 3]
        assert list(record["bonds"]["atomi"]) == [1, 1]
        assert list(record["bonds"]["atomj"]) == [0, 2]
        assert np.asarray(record["hessian"]["value"]).shape == (81,)
        assert record.meta["source_record_id"] == "eq-record"
        assert record.meta["total_charge"] == 0

    def test_worker_pickle_does_not_capture_h5_handle(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_hessian(path)
        dataset = THEMolHessian(path).load()
        dataset[0]
        restored = pickle.loads(pickle.dumps(dataset))
        assert np.asarray(restored[0][0]["hessian"]["value"]).shape == (81,)

    def test_atomic_number_mismatch_fails_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_hessian(path)
        with h5py.File(path, "r+") as handle:
            handle["eq-record/atomic_numbers"][0, 0] = 6
        with pytest.raises(ValueError, match="atomic-number mismatch"):
            THEMolHessian(path).load()[0]


class TestGroupedTasks:
    # `test_relaxation_record_is_lazy_until_frame_access` was deleted by
    # `hf-facade-02-frame-records` (D2): `molpy.Trajectory` materializes on
    # construction, so laziness *within* one record is given up on purpose and a
    # test that pinned the opposite would pin a design that no longer exists.
    # Laziness *between* records — the per-process HDF5 handle — is unchanged and
    # is still covered by `test_worker_pickle_does_not_capture_h5_handle`.

    def test_hessian_relax_preserves_ordered_trajectory(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_hessian_relax(path)
        frames = THEMolHessianRelax(path).load()[0]
        assert len(frames) == 2
        assert [frame.meta["step_index"] for frame in frames] == [0, 1]
        assert [frame.meta["energy"] for frame in frames] == [-10.0, -10.5]
        assert list(frames[1]["atoms"]["fx"]) == [2.0, 2.0, 2.0]

    def test_torsion_scan_is_one_complete_profile(self, tmp_path: Path) -> None:
        """The profile is the record: one FrameCollection, scalars in per-frame meta."""
        path = tmp_path / "shard-000.h5"
        _write_torsion(path, relax=False)
        profile = THEMolTorsionScan(path).load()[0]
        frames = list(profile)
        assert [frame.meta["scan_id"] for frame in frames] == ["scan-record", "scan-record"]
        assert [
            np.asarray(frames[0]["scan"][name]).tolist()
            for name in ("atomi", "atomj", "atomk", "atoml")
        ] == [[0], [1], [2], [3]]
        assert len(profile) == 2
        assert [frame.meta["constraint_index"] for frame in frames] == [0, 1]
        assert [frame.meta["torsion_angle"] for frame in frames] == pytest.approx(
            list(BUTANE_SCAN_ANGLES), abs=1e-9
        )
        assert frames[0].meta["molecule_id"] != frames[0].meta["scan_id"]

    def test_torsion_relax_preserves_constraint_and_step(self, tmp_path: Path) -> None:
        """`optimization_steps` is gone; the step is a per-frame meta scalar."""
        path = tmp_path / "shard-000.h5"
        _write_torsion(path, relax=True)
        profile = THEMolTorsionRelax(path).load()[0]
        frames = list(profile)
        assert len(profile) == 4
        assert [frame.meta["step_index"] for frame in frames] == [0, 1, 0, 1]
        assert [frame.meta["constraint_index"] for frame in frames] == [
            0,
            0,
            1,
            1,
        ]

    def test_mbis_supervision_lands_in_atom_columns(self, tmp_path: Path) -> None:
        """The per-atom fixture arrays, read as `atoms` columns of one `Frame`.

        The Slater shells are *not* among them — they are one row per shell, not
        per atom, so they land in the `mbis_shells` block that `TestTHEMolMBIS`
        pins.
        """
        path = tmp_path / "shard-000.h5"
        _write_mbis(path)
        atoms = THEMolMBIS(path).load()[0][0]["atoms"]
        assert np.asarray(atoms["atomic_charge"]).tolist() == pytest.approx([0.4, -0.8, 0.4])
        assert [np.asarray(atoms[name]).shape for name in MBIS_QUADRUPOLE_COLUMNS] == [(3,)] * 9
        assert [
            np.asarray(atoms[name]).tolist() for name in ("dipole_x", "dipole_y", "dipole_z")
        ] == [[1.0] * 3] * 3


# ---------------------------------------------------------------------------
# Goldens for the dissolved records — spec `hf-facade-02-frame-records`, D1.
# A record IS a molpy object: one geometry is a `Frame`, a multi-frame sampling
# unit is a `Trajectory`, and the payload the four dataclasses used to hold
# moves onto blocks / atom columns / per-frame `meta`.
# ---------------------------------------------------------------------------

# The atom columns `_mapped_topology_frame` already writes for every task:
# identity, geometry, and the per-atom topology facts a Class-I parameter head
# conditions on (`formal_charge`, the two ring columns and the GAFF2
# Lennard-Jones prior). The MBIS supervision columns are pinned below as the
# exact difference from this set, so a stray extra column is a failure rather
# than a silent addition.
GEOMETRY_ATOM_COLUMNS = frozenset(
    {
        "element",
        "number",
        "atom_map",
        "formal_charge",
        "ring_connectivity",
        "min_ring_size",
        "equi_index",
        "gaff2_sigma",
        "gaff2_epsilon",
        "x",
        "y",
        "z",
    }
)

# The Cartesian Hessian as a COO block: *all* (3N)**2 entries, row-major, no
# triangle folding and no sparsity assumption (D1).
HESSIAN_BLOCK_COLUMNS = ("row", "col", "value")

# One column per Cartesian index pair (i, j) of the source's (N, 3, 3)
# quadrupole, in row-major order and unfolded — `quadrupole_yx` is a column, not
# a synonym for `quadrupole_xy`. This applies the same reasoning D1 gives the
# Hessian block ("a discarded lower triangle is a convention every reader must
# then remember") to the rank-2 per-atom tensor, and it means the column count
# is read from the source shape alone, with no symmetry assumed of the data.
MBIS_QUADRUPOLE_COLUMNS = (
    "quadrupole_xx",
    "quadrupole_xy",
    "quadrupole_xz",
    "quadrupole_yx",
    "quadrupole_yy",
    "quadrupole_yz",
    "quadrupole_zx",
    "quadrupole_zy",
    "quadrupole_zz",
)

# The Slater shells are *not* atom columns — `mbis_parameter_<slot>` was read off
# a `(N, arity)` array the published shards do not contain, so those columns are
# gone and the shells are the `mbis_shells` block instead (see the evidence block
# above `_write_mbis`). The prefix stays spelled here so a test can assert its
# absence rather than merely not mentioning it.
MBIS_PARAMETER_PREFIX = "mbis_parameter"

MBIS_ATOM_COLUMNS = frozenset(
    {
        "atomic_charge",
        "atomic_volume",
        "dipole_x",
        "dipole_y",
        "dipole_z",
        *MBIS_QUADRUPOLE_COLUMNS,
    }
)

# What `THEMolMBIS.TARGET_SCHEMA.atom_level` declares: the fourteen columns whose
# names the *format* fixes, spelled out rather than composed from the tuples
# above, so that editing one of those tuples cannot silently move the schema
# pin with it. This set is unchanged by the shell correction: the fourteen
# per-atom columns were always right, and the shells were never among them.
MBIS_SCHEMA_ATOM_COLUMNS = frozenset(
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

# The Cartesian Hessian is a COO block, but `TargetSchema` has only the two
# layout sets, so the reader still declares it graph-level; the `blocks`
# declaration that would say "block, not meta" is `hf-facade-03-builder-info`'s.
HESSIAN_SCHEMA_GRAPH_TARGETS = frozenset({"hessian"})

# Synthetic MBIS doubles with distinguishable components — the shipped fixture's
# `np.ones` cannot tell `dipole_x` from `dipole_z`. Values are exact in binary
# floating point and are **not** real-data truth.
MBIS_DIPOLE = np.asarray(
    [[0.125, 0.25, 0.375], [1.125, 1.25, 1.375], [2.125, 2.25, 2.375]],
    dtype=np.float64,
)

# `source[a, i, j] = 10a + 3i + j + 0.5`, deliberately **asymmetric** so the
# (i, j) -> column mapping is observable at all. A physical MBIS atomic
# quadrupole is symmetric; this is an ordering probe, not chemistry.
MBIS_QUADRUPOLE = (
    np.arange(9, dtype=np.float64).reshape(1, 3, 3)
    + np.asarray([0.0, 10.0, 20.0], dtype=np.float64).reshape(3, 1, 1)
    + 0.5
)

# The two `_write_torsion(relax=False)` geometries' dihedrals about atoms
# (0, 1, 2, 3), in degrees. Provenance: computed once, offline, with
# `molhub.dataset.themol._dihedral_angle(_butane_coords(shift), (0, 1, 2, 3))`
# for shift 0.0 and 1.0 (molpy 0.13.1, numpy 2.x, 2026-08-15) and pinned as
# literals — recomputing them here with the same call would assert nothing.
BUTANE_SCAN_ANGLES = (45.0, 18.43494882292201)


def _meta_and_block_frame(index: int) -> Frame:
    """One frame carrying per-frame ``meta`` scalars and a named non-atoms block."""
    frame = Frame()
    frame["atoms"] = Block(
        {
            "element": np.asarray(["C", "C"], dtype=str),
            "number": np.asarray([6, 6], dtype=np.int64),
            "x": np.asarray([0.0, 1.0 + index], dtype=np.float64),
            "y": np.zeros(2, dtype=np.float64),
            "z": np.zeros(2, dtype=np.float64),
        }
    )
    frame["scan"] = Block(
        {
            "atomi": np.asarray([0], dtype=np.int32),
            "atomj": np.asarray([1], dtype=np.int32),
            "atomk": np.asarray([2], dtype=np.int32),
            "atoml": np.asarray([3], dtype=np.int32),
        }
    )
    frame.meta = {
        "energy": -10.0 - index,
        "torsion_angle": 30.0 * index,
        "scan_id": "scan-record",
        "constraint_index": index,
    }
    return frame


class TestTrajectoryRoundTrip:
    """The D3 gate: `molpy.Trajectory` keeps per-frame meta and non-atoms blocks.

    `molpy.Trajectory` is eager — the Rust container copies each frame into its
    own column store on construction — so "the record IS a Trajectory" is only a
    viable record model if the scalars and the index block survive that copy.
    Probed PASS on 2026-08-15; pinned here permanently, because a molpy
    regression that dropped either would silently empty every THEMol scan.
    """

    @staticmethod
    def _trajectory() -> Trajectory:
        return Trajectory([_meta_and_block_frame(0), _meta_and_block_frame(1)])

    def test_per_frame_meta_scalars_survive_indexing(self) -> None:
        """Each frame keeps *its own* scalars — not the first frame's, twice."""
        trajectory = self._trajectory()
        assert len(trajectory) == 2
        assert [trajectory[index].meta["energy"] for index in range(2)] == [-10.0, -11.0]
        assert [trajectory[index].meta["torsion_angle"] for index in range(2)] == [0.0, 30.0]
        assert [trajectory[index].meta["constraint_index"] for index in range(2)] == [0, 1]
        assert [trajectory[index].meta["scan_id"] for index in range(2)] == [
            "scan-record",
            "scan-record",
        ]

    def test_a_named_non_atoms_block_survives_indexing(self) -> None:
        """The 1-row index block is where a len-4 tuple lives; `meta` rejects it."""
        block = self._trajectory()[1]["scan"]
        assert [
            np.asarray(block[name]).tolist() for name in ("atomi", "atomj", "atomk", "atoml")
        ] == [
            [0],
            [1],
            [2],
            [3],
        ]

    def test_each_frames_own_geometry_survives_indexing(self) -> None:
        """Frames are copied, not aliased: frame 1's coordinates are frame 1's."""
        trajectory = self._trajectory()
        assert [np.asarray(trajectory[index]["atoms"]["x"]).tolist() for index in range(2)] == [
            [0.0, 1.0],
            [0.0, 2.0],
        ]


class TestTHEMolShardDataset:
    """The lazy view over one shard: what its keys are, and what they line up with.

    ``keys()`` is public because a record's HDF5 group key is the only thing
    that joins a shard to a split table keyed by record uuid — that is what
    ``molhub.loader``'s shard index reads. This pins the three properties that
    join relies on: the keys are the file's group keys, they come back as a
    ``tuple[str, ...]``, and index *i* of that tuple is the record ``self[i]``
    returns.

    Two records rather than one: a single-key shard cannot tell "the shard's
    keys, in order" apart from "the one key it has", and it cannot fail the
    alignment test at all.
    """

    #: The fixture's two group keys, ascending — which is both the order they
    #: are created in and the order HDF5 lists them in, so the pin below says
    #: nothing about which of the two ``keys()`` follows.
    KEYS: tuple[str, ...] = ("eq-record-0", "eq-record-1")

    @staticmethod
    def _shard(tmp_path: Path) -> Path:
        """A two-record equilibrium shard built from this file's own builders."""
        path = tmp_path / "shard-000.h5"
        _write_two_record_hessian(path, TestTHEMolShardDataset.KEYS)
        return path

    def test_keys_are_the_shards_group_keys(self, tmp_path: Path) -> None:
        assert THEMolHessian(self._shard(tmp_path)).load().keys() == ("eq-record-0", "eq-record-1")

    def test_the_loaded_shard_carries_its_definitions_manifest(self, tmp_path: Path) -> None:
        """The loaded dataset answers what it publishes, not only its definition.

        A consumer holding the loaded object and unable to ask it must restate
        the units at the call site, and a restated unit drifts from the
        published one: reading a kcal/mol dataset through an eV default scaled
        every label by 23.06, silently, the result still being a plausible
        energy (molnex ``ClassIPrepare``, 2026-09-17).
        """
        loaded = THEMolHessian(self._shard(tmp_path)).load()
        # Non-empty first: a definition that declared nothing would let the
        # identity below hold while pinning no units at all.
        assert THEMolHessian.manifest.units
        assert loaded.manifest is THEMolHessian.manifest

    def test_keys_are_a_tuple_of_strings(self, tmp_path: Path) -> None:
        """A tuple, not a ``KeysView``: an index into it has to mean something."""
        keys = THEMolHessian(self._shard(tmp_path)).load().keys()
        assert isinstance(keys, tuple)
        assert [type(key) for key in keys] == [str, str]

    def test_keys_are_positionally_aligned_with_indexing(self, tmp_path: Path) -> None:
        """``keys()[i]`` names the record ``self[i]`` reads — the join's whole basis."""
        shard = THEMolHessian(self._shard(tmp_path)).load()
        read = [shard[index][0].meta["source_record_id"] for index in range(len(shard))]
        assert read == ["eq-record-0", "eq-record-1"]
        assert read == list(shard.keys())

    def test_keys_are_read_from_the_sidecar_on_a_second_construction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The second construction opens no HDF5 file.

        Listing the group keys is what made constructing this dataset
        expensive — 194 s for the torsion-scan shard's 83 951 keys on a cold
        page cache — and every process paid it again. Denying the second
        construction any HDF5 access is the only way to assert the cache is
        what answered.
        """
        shard = self._shard(tmp_path)
        assert THEMolHessian(shard).load().keys() == self.KEYS

        def _refuse(_path: Path) -> object:
            raise AssertionError("the second construction must not open the shard")

        monkeypatch.setattr("molhub.dataset.themol._open_h5", _refuse)
        assert THEMolHessian(shard).load().keys() == self.KEYS

    def test_getitems_matches_indexing(self, tmp_path: Path) -> None:
        """A batched fetch reads the same records indexing does, in the order asked."""
        shard = THEMolHessian(self._shard(tmp_path)).load()
        order = [1, 0]
        batched = shard.__getitems__(order)
        serial = [shard[i] for i in order]
        assert [item[0].meta["source_record_id"] for item in batched] == [
            item[0].meta["source_record_id"] for item in serial
        ]
        for got, expected in zip(batched, serial, strict=True):
            assert np.array_equal(got[0]["atoms"]["x"], expected[0]["atoms"]["x"])
            assert np.array_equal(got[0]["hessian"]["value"], expected[0]["hessian"]["value"])
            assert (
                got[0].meta["mapped_isomeric_smiles"] == expected[0].meta["mapped_isomeric_smiles"]
            )

    def test_a_second_read_rebuilds_frames_without_opening_the_shard(self, tmp_path: Path) -> None:
        """A cache hit does not open the shard. The miss still does."""
        shard = THEMolHessian(self._shard(tmp_path)).load()
        first = shard[0][0]
        opened: list[int] = []
        snap = shard._h5().snapshot

        def _count(name: str):
            opened.append(1)
            return snap(name)

        shard._h5().snapshot = _count  # type: ignore[method-assign]
        second = shard[0][0]
        assert opened == []
        assert second["hessian"]["row"].dtype == np.dtype(np.int32)
        assert second["hessian"]["col"].dtype == np.dtype(np.int32)
        assert second["hessian"]["value"].dtype == np.dtype(np.float64)
        assert np.array_equal(second["hessian"]["value"], first["hessian"]["value"])
        assert list(second["atoms"]["element"]) == list(first["atoms"]["element"])
        assert second.meta["mapped_isomeric_smiles"] == first.meta["mapped_isomeric_smiles"]
        batched = shard.__getitems__([0, 1])
        assert opened == [1]
        assert batched[0][0].meta["source_record_id"] == first.meta["source_record_id"]
        assert batched[1][0].meta["source_record_id"] == "eq-record-1"

    def test_without_a_cache_every_read_stages(self, tmp_path: Path) -> None:
        shard = THEMolHessian(self._shard(tmp_path)).load()
        shard.cache = None
        staged: list[int] = []
        stage = shard.stage

        def _count(index: int):
            staged.append(int(index))
            return stage(index)

        shard.stage = _count  # type: ignore[method-assign]
        shard[0]
        shard[0]
        assert staged == [0, 0]

    def test_element_mask_sets_one_bit_per_element_the_row_carries(self, tmp_path: Path) -> None:
        """A row's elements, as a bitmask — the cheap input to a coverage check.

        Water is H and O, so bits 1 and 8; butane is H and C, so bits 1 and 6.
        Bit-per-element rather than a list because the only question asked of it
        is "which elements does this *set* of rows use?", which is one OR.
        """
        path = tmp_path / "shard-000.h5"
        _write_molecule_shard(path, {"water": WATER, "butane": BUTANE})
        masks = THEMolHessian(path).load().element_mask()
        assert masks.dtype == np.int64
        assert masks.tolist() == [(1 << 1) | (1 << 8), (1 << 1) | (1 << 8)]

    def test_element_mask_refuses_an_element_too_wide_for_one_integer(self, tmp_path: Path) -> None:
        """Z >= 64 does not fit the bitmask, so it raises instead of truncating.

        A truncated mask reads as "this row has no such element", which is the
        exact false negative a coverage check exists to prevent.
        """
        path = tmp_path / "shard-000.h5"
        with h5py.File(path, "w") as handle:
            group = handle.create_group("heavy")
            _identity(group, WATER, [1, 8, 1])
            group.create_dataset("coords", data=_water_coords())
            group.create_dataset("hessian", data=np.eye(9, dtype=np.float64))
            del group["atomic_numbers"]
            group.create_dataset("atomic_numbers", data=np.asarray([92], dtype=np.int32))
        with pytest.raises(ValueError, match="Z=92"):
            THEMolHessian(path).load().element_mask()

    def test_molecule_index_groups_rows_by_molecule(self, tmp_path: Path) -> None:
        """Rows sharing a molecule share a group, in first-appearance order.

        One row is one scan and a molecule has as many scans as scanned
        dihedrals, so a row-wise split puts the same molecule on both sides.
        The A/B/A order matters: a vector that merely enumerated rows, or
        sorted the molecules, would pass on A/B and fail here.
        """
        path = tmp_path / "shard-000.h5"
        _write_molecule_shard(path, {"r0": WATER, "r1": BUTANE, "r2": WATER})
        index = THEMolHessian(path).load().molecule_index()
        assert index.tolist() == [0, 1, 0]
        assert index.dtype == np.int64

    def test_molecule_index_refuses_a_record_that_names_no_molecule(self, tmp_path: Path) -> None:
        """No SMILES, no grouping — and no quiet fallback to the row number.

        A per-row fallback would look like a valid index and would leak every
        unnamed molecule across the split.
        """
        path = tmp_path / "shard-000.h5"
        _write_molecule_shard(path, {"r0": WATER, "r1": None})
        with pytest.raises(ValueError, match="mapped_nonisomeric_smiles"):
            THEMolHessian(path).load().molecule_index()


class TestTHEMolHessian:
    """One equilibrium record is a `Frame` carrying its Hessian as a COO block."""

    @staticmethod
    def _record(tmp_path: Path) -> Frame:
        path = tmp_path / "shard-000.h5"
        _write_hessian(path)
        return THEMolHessian(path).load()[0][0]

    def test_a_hessian_record_is_a_length_one_collection(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_hessian(path)
        record = THEMolHessian(path).load()[0]
        assert len(record) == 1
        assert isinstance(record[0], Frame)

    def test_the_frame_keeps_its_topology_and_provenance(self, tmp_path: Path) -> None:
        record = self._record(tmp_path)
        assert np.asarray(record["atoms"]["number"]).tolist() == [1, 8, 1]
        assert np.asarray(record["bonds"]["atomi"]).tolist() == [1, 1]
        assert np.asarray(record["bonds"]["atomj"]).tolist() == [0, 2]
        assert record.meta["source_record_id"] == "eq-record"
        assert record.meta["total_charge"] == 0

    def test_the_hessian_block_declares_three_columns(self, tmp_path: Path) -> None:
        assert frozenset(self._record(tmp_path)["hessian"].keys()) == frozenset(
            HESSIAN_BLOCK_COLUMNS
        )

    def test_the_hessian_block_holds_every_entry_row_major(self, tmp_path: Path) -> None:
        """All (3N)**2 = 81 entries, in row-major order: no folding, no sparsity."""
        block = self._record(tmp_path)["hessian"]
        rows = np.asarray(block["row"])
        cols = np.asarray(block["col"])
        assert rows.shape == (81,)
        assert cols.shape == (81,)
        assert rows.tolist() == np.repeat(np.arange(9), 9).tolist()
        assert cols.tolist() == np.tile(np.arange(9), 9).tolist()

    def test_three_identity_entries_are_pinned(self, tmp_path: Path) -> None:
        """The fixture's Hessian is `np.eye(9)`; three of its entries, by literal."""
        block = self._record(tmp_path)["hessian"]
        rows = np.asarray(block["row"])
        cols = np.asarray(block["col"])
        values = np.asarray(block["value"])
        entries = [(int(rows[k]), int(cols[k]), float(values[k])) for k in (0, 1, 10)]
        assert entries == [(0, 0, 1.0), (0, 1, 0.0), (1, 1, 1.0)]

    def test_the_values_reshape_to_the_source_matrix(self, tmp_path: Path) -> None:
        """Row-major is a promise about `value`, so the double is asymmetric.

        `np.arange(81).reshape(9, 9)` is not a physical Hessian — a real one is
        symmetric, which is exactly why it could not tell row-major from
        column-major apart. It is an ordering probe.
        """
        source = np.arange(81, dtype=np.float64).reshape(9, 9)
        path = tmp_path / "shard-000.h5"
        _write_hessian(path, hessian=source)
        values = np.asarray(THEMolHessian(path).load()[0][0]["hessian"]["value"])
        assert values.reshape(9, 9).tolist() == source.tolist()

    def test_the_hessian_block_dtypes_are_int32_int32_float64(self, tmp_path: Path) -> None:
        """Indices narrow to int32; values keep the source's float64 precision."""
        block = self._record(tmp_path)["hessian"]
        assert [np.asarray(block[name]).dtype.str for name in HESSIAN_BLOCK_COLUMNS] == [
            "<i4",
            "<i4",
            "<f8",
        ]

    def test_the_declared_target_schema_names_the_hessian_only(self) -> None:
        """One graph-level target, no atom-level one — read without touching a shard."""
        schema = THEMolHessian.TARGET_SCHEMA
        assert isinstance(schema.graph_level, frozenset)
        assert schema.graph_level == HESSIAN_SCHEMA_GRAPH_TARGETS
        assert schema.atom_level == frozenset()

    def test_a_bondless_molecule_carries_no_bond_block(self, tmp_path: Path) -> None:
        """A bare noble-gas atom is legitimate chemistry with zero bonds."""
        path = tmp_path / "shard-000.h5"
        _write_hessian(path, smiles=NEON, numbers=(10,), coords=np.zeros((1, 3)))
        record = THEMolHessian(path).load()[0]
        assert len(record) == 1
        assert isinstance(record[0], Frame)
        assert "bonds" not in record[0]
        assert np.asarray(record[0]["hessian"]["value"]).shape == (9,)


def _topology_group(smiles: str, numbers: Sequence[int]) -> dict[str, object]:
    """A record's identity arrays, as `_mapped_topology_frame` reads them off a shard."""
    return {
        "mapped_isomeric_smiles": smiles,
        "mapped_nonisomeric_smiles": smiles,
        "atomic_numbers": np.asarray(numbers, dtype=np.int32)[:, None],
        "coords": np.zeros((len(numbers), 3), dtype=np.float64),
    }


class TestMappedTopologyFrame:
    """The topology facts every THEMol frame carries, computed once per record.

    All of them are read off the mapped SMILES, so a plain dict stands in for
    the HDF5 group: the shard-level readers are pinned by the classes above
    and below, and what is pinned here is the chemistry of each column.
    """

    @staticmethod
    def _toluene() -> Frame:
        return _mapped_topology_frame(_topology_group(TOLUENE, TOLUENE_NUMBERS), "tol", "src")

    def test_ring_connectivity_counts_ring_bonds_at_the_atom(self) -> None:
        """Six ring carbons carry two ring bonds each; the methyl carbon and every H none."""
        column = np.asarray(self._toluene()["atoms"]["ring_connectivity"])
        assert column.dtype == np.int64
        assert column.tolist() == [0, 2, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0]

    def test_min_ring_size_is_the_smallest_ring_through_the_atom_or_zero(self) -> None:
        column = np.asarray(self._toluene()["atoms"]["min_ring_size"])
        assert column.dtype == np.int64
        assert column.tolist() == [0, 6, 6, 6, 6, 6, 6, 0, 0, 0, 0, 0, 0, 0, 0]

    def test_min_ring_size_picks_the_smaller_of_two_rings(self) -> None:
        """Cyclopropylbenzene: 3 on the cyclopropyl carbons, 6 on the phenyl ones."""
        smiles = (
            "[C:1]1([H:10])([H:11])[C:2]([H:12])([H:13])[C:3]1([H:14])"
            "[c:4]1[c:5]([H:15])[c:6]([H:16])[c:7]([H:17])[c:8]([H:18])[c:9]1[H:19]"
        )
        group = _topology_group(smiles, (6,) * 9 + (1,) * 10)
        frame = _mapped_topology_frame(group, "cpb", "src")
        carbons = np.asarray(frame["atoms"]["min_ring_size"]).tolist()[:9]
        assert carbons == [3, 3, 3, 6, 6, 6, 6, 6, 6]

    def test_equi_index_names_the_first_atom_of_each_topological_class(self) -> None:
        """Toluene: the two ortho and the two meta positions pair up, H with their carbons."""
        column = np.asarray(self._toluene()["atoms"]["equi_index"])
        assert column.dtype == np.int64
        assert column.tolist() == [0, 1, 2, 3, 4, 3, 2, 7, 7, 7, 10, 11, 12, 11, 10]

    def test_a_carboxylates_oxygens_share_a_class_whatever_the_bond_orders(self) -> None:
        smiles = "[C:1]([H:5])([H:6])([H:7])[C:2](=[O:3])[O-:4]"
        frame = _mapped_topology_frame(_topology_group(smiles, (6, 6, 8, 8, 1, 1, 1)), "ace", "src")
        assert np.asarray(frame["atoms"]["equi_index"]).tolist() == [0, 1, 2, 2, 4, 4, 4]

    def test_every_torsion_of_propyne_turns_about_a_linear_centre(self) -> None:
        smiles = "[C:1]([H:4])([H:5])([H:6])[C:2]#[C:3][H:7]"
        frame = _mapped_topology_frame(_topology_group(smiles, (6, 6, 6, 1, 1, 1, 1)), "pyn", "src")
        propers = frame["propers"]
        assert len(np.asarray(propers["atomi"])) == 4
        assert np.asarray(propers["linear"]).all()

    def test_a_molecule_without_torsions_still_carries_an_empty_propers_block(self) -> None:
        frame = _mapped_topology_frame(_topology_group(WATER, (1, 8, 1)), "water", "src")
        propers = frame["propers"]
        assert sorted(propers.keys()) == ["atomi", "atomj", "atomk", "atoml", "linear"]
        assert len(np.asarray(propers["atomi"])) == 0

    def test_no_torsion_of_toluene_is_linear(self) -> None:
        propers = self._toluene()["propers"]
        rows = np.stack([np.asarray(propers[c]) for c in ("atomi", "atomj", "atomk", "atoml")], 1)
        assert len(rows) > 0 and not np.asarray(propers["linear"]).any()
        assert (rows[:, 1] < rows[:, 2]).all()

    def test_the_graph_is_read_off_the_stereo_free_string(self) -> None:
        """A contradictory isomeric string (two marks on one side of C1=C2) still builds."""
        group = _topology_group("[C:1]([F:3])([Cl:4])=[C:2]([F:5])[H:6]", (6, 6, 9, 17, 9, 1))
        group["mapped_isomeric_smiles"] = "[C:1](/[F:3])(/[Cl:4])=[C:2](/[F:5])[H:6]"
        frame = _mapped_topology_frame(group, "conflict", "src")
        assert np.asarray(frame["atoms"]["number"]).tolist() == [6, 6, 9, 17, 9, 1]
        assert len(np.asarray(frame["bonds"]["atomi"])) == 5

    def test_a_ring_larger_than_eight_atoms_is_no_ring(self) -> None:
        """Cyclononane: ByteFF counts rings of at most eight atoms, so none here."""
        smiles = "".join(f"[C:{k}]" + ("1" if k in (1, 9) else "") for k in range(1, 10))
        frame = _mapped_topology_frame(_topology_group(smiles, (6,) * 9), "c9", "src")
        assert not np.asarray(frame["bonds"]["in_ring"]).any()
        assert not np.asarray(frame["atoms"]["ring_connectivity"]).any()
        assert not np.asarray(frame["atoms"]["min_ring_size"]).any()

    def test_in_ring_marks_exactly_the_bonds_between_ring_neighbours(self) -> None:
        """A bond is a ring bond iff its two atoms are adjacent in some SSSR ring."""
        bonds = self._toluene()["bonds"]
        in_ring = np.asarray(bonds["in_ring"])
        assert in_ring.dtype == np.int64
        ring_atoms = set(range(1, 7))
        expected = [
            int(i in ring_atoms and j in ring_atoms)
            for i, j in zip(np.asarray(bonds["atomi"]), np.asarray(bonds["atomj"]), strict=True)
        ]
        assert in_ring.tolist() == expected
        assert int(in_ring.sum()) == 6

    def test_the_gaff2_prior_is_the_tables_well_for_the_antechamber_type(self) -> None:
        """c3 on the methyl carbon, ca on the ring, hc on methyl H, ha on ring H."""
        table = Gaff2LennardJones()
        atoms = self._toluene()["atoms"]
        sigma = np.asarray(atoms["gaff2_sigma"])
        epsilon = np.asarray(atoms["gaff2_epsilon"])
        assert sigma.dtype == np.float64 and epsilon.dtype == np.float64
        expected_types = ["c3"] + ["ca"] * 6 + ["hc"] * 3 + ["ha"] * 5
        assert sigma.tolist() == pytest.approx([table.sigma(t) for t in expected_types], rel=1e-12)
        assert epsilon.tolist() == pytest.approx(
            [table.epsilon(t) for t in expected_types], rel=1e-12
        )

    def test_a_charged_species_keeps_its_formal_charge_and_types_as_such(self) -> None:
        frame = _mapped_topology_frame(_topology_group(AMMONIUM, (7, 1, 1, 1, 1)), "amm", "src")
        assert np.asarray(frame["atoms"]["formal_charge"]).tolist() == [1, 0, 0, 0, 0]
        assert frame.meta["total_charge"] == 1
        nitrogen_epsilon = float(np.asarray(frame["atoms"]["gaff2_epsilon"])[0])
        assert nitrogen_epsilon == Gaff2LennardJones().epsilon("n+")

    def test_an_element_gaff2_cannot_type_gets_nan_not_zero(self) -> None:
        """Silicon has no GAFF2 row: the prior is absent, and absent is NaN."""
        frame = _mapped_topology_frame(_topology_group(SILANE, (14, 1, 1, 1, 1)), "sil", "src")
        sigma = np.asarray(frame["atoms"]["gaff2_sigma"])
        epsilon = np.asarray(frame["atoms"]["gaff2_epsilon"])
        assert np.isnan(sigma[0]) and np.isnan(epsilon[0])
        assert np.isfinite(sigma[1:]).all() and np.isfinite(epsilon[1:]).all()

    def test_a_bondless_atom_has_zero_ring_columns_and_no_bond_block(self) -> None:
        frame = _mapped_topology_frame(_topology_group(NEON, (10,)), "ne", "src")
        assert "bonds" not in frame
        assert np.asarray(frame["atoms"]["ring_connectivity"]).tolist() == [0]
        assert np.asarray(frame["atoms"]["min_ring_size"]).tolist() == [0]

    def test_the_columns_follow_atom_map_order_not_parse_order(self) -> None:
        """Water is parsed O first and mapped H:1 O:2 H:3; the ring columns ride along."""
        smiles = (
            "[c:3]1([H:1])[c:2]([H:4])[c:5]([H:6])[c:7]([H:8])[c:9]([H:10])[c:11]1"
            "[C:12]([H:13])([H:14])[H:15]"
        )
        numbers = [1, 6, 6, 1, 6, 1, 6, 1, 6, 1, 6, 6, 1, 1, 1]
        frame = _mapped_topology_frame(_topology_group(smiles, numbers), "tol2", "src")
        atoms = frame["atoms"]
        is_ring_carbon = [n == 6 and k != 11 for k, n in enumerate(numbers)]
        assert np.asarray(atoms["ring_connectivity"]).tolist() == [
            2 if ring else 0 for ring in is_ring_carbon
        ]
        assert np.asarray(atoms["min_ring_size"]).tolist() == [
            6 if ring else 0 for ring in is_ring_carbon
        ]
        methyl_epsilon = float(np.asarray(atoms["gaff2_epsilon"])[11])
        assert methyl_epsilon == Gaff2LennardJones().epsilon("c3")

    def test_nan_priors_survive_the_record_cache(self, tmp_path: Path) -> None:
        """The second read comes from the LMDB cache; a NaN must not become a number."""
        path = tmp_path / "shard-000.h5"
        _write_hessian(path, smiles=SILANE, numbers=(14, 1, 1, 1, 1), coords=np.zeros((5, 3)))
        shard = THEMolHessian(path).load()
        first = np.asarray(shard[0][0]["atoms"]["gaff2_sigma"])
        second = np.asarray(shard[0][0]["atoms"]["gaff2_sigma"])
        assert np.isnan(first[0]) and np.isnan(second[0])
        assert second.dtype == np.float64
        assert np.asarray(shard[0][0]["atoms"]["min_ring_size"]).dtype == np.int64


class TestTHEMolMBIS:
    """One MBIS record: per-atom supervision in `atoms`, Slater shells in a block.

    The fourteen per-atom columns are unchanged. What changed is ``parameters``:
    the reader used to emit it as ``mbis_parameter_<slot>`` atom columns, which
    is a shape no published record has (the evidence block above ``_write_mbis``
    records the 2026-08-15 probe), so it is now the ``mbis_shells`` block —
    ``atom`` / ``population`` / ``inverse_width``, one row per Slater shell, in
    source order.
    """

    @staticmethod
    def _record(tmp_path: Path) -> Frame:
        path = tmp_path / "shard-000.h5"
        _write_mbis(
            path,
            atomic_dipole=MBIS_DIPOLE,
            atomic_quadrupole=MBIS_QUADRUPOLE,
        )
        return THEMolMBIS(path).load()[0][0]

    @staticmethod
    def _refused(tmp_path: Path, parameters: np.ndarray) -> Path:
        """One shard whose only defect is its shell table."""
        path = tmp_path / "shard-000.h5"
        _write_mbis(
            path,
            atomic_dipole=MBIS_DIPOLE,
            atomic_quadrupole=MBIS_QUADRUPOLE,
            parameters=parameters,
        )
        return path

    def test_an_mbis_record_is_a_length_one_collection(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_mbis(
            path,
            atomic_dipole=MBIS_DIPOLE,
            atomic_quadrupole=MBIS_QUADRUPOLE,
        )
        record = THEMolMBIS(path).load()[0]
        assert len(record) == 1
        assert isinstance(record[0], Frame)

    def test_the_atoms_block_carries_exactly_the_mbis_columns(self, tmp_path: Path) -> None:
        """Geometry plus the fourteen per-atom columns, and nothing else.

        An extra column here arrived unrouted — which is exactly how the Slater
        shells used to get in, one `mbis_parameter_<slot>` per source column.
        """
        atoms = self._record(tmp_path)["atoms"]
        assert frozenset(atoms.keys()) == GEOMETRY_ATOM_COLUMNS | MBIS_ATOM_COLUMNS

    def test_the_atomic_charges_are_one_column_of_n(self, tmp_path: Path) -> None:
        """The source is `(N, 1)`; the column is `(N,)`, with the oxygen pinned."""
        charges = np.asarray(self._record(tmp_path)["atoms"]["atomic_charge"])
        assert charges.shape == (3,)
        assert float(charges[1]) == pytest.approx(-0.8, abs=1e-10)
        assert charges.tolist() == pytest.approx([0.4, -0.8, 0.4], abs=1e-10)

    def test_the_atomic_volumes_are_one_column_of_n(self, tmp_path: Path) -> None:
        volumes = np.asarray(self._record(tmp_path)["atoms"]["atomic_volume"])
        assert volumes.shape == (3,)
        assert volumes.tolist() == pytest.approx([1.0, 1.0, 1.0], abs=1e-10)

    def test_the_dipole_components_are_named_by_axis(self, tmp_path: Path) -> None:
        atoms = self._record(tmp_path)["atoms"]
        assert np.asarray(atoms["dipole_x"]).tolist() == pytest.approx(
            [0.125, 1.125, 2.125], abs=1e-10
        )
        assert np.asarray(atoms["dipole_y"]).tolist() == pytest.approx(
            [0.25, 1.25, 2.25], abs=1e-10
        )
        assert np.asarray(atoms["dipole_z"]).tolist() == pytest.approx(
            [0.375, 1.375, 2.375], abs=1e-10
        )

    def test_the_quadrupole_components_are_named_by_cartesian_index_pair(
        self, tmp_path: Path
    ) -> None:
        """Nine columns, `quadrupole_ij == source[:, i, j]`; `yx` is not `xy`."""
        atoms = self._record(tmp_path)["atoms"]
        assert np.asarray(atoms["quadrupole_xx"]).tolist() == pytest.approx(
            [0.5, 10.5, 20.5], abs=1e-10
        )
        assert np.asarray(atoms["quadrupole_xy"]).tolist() == pytest.approx(
            [1.5, 11.5, 21.5], abs=1e-10
        )
        assert np.asarray(atoms["quadrupole_yx"]).tolist() == pytest.approx(
            [3.5, 13.5, 23.5], abs=1e-10
        )
        assert np.asarray(atoms["quadrupole_zz"]).tolist() == pytest.approx(
            [8.5, 18.5, 28.5], abs=1e-10
        )

    def test_no_per_atom_slater_parameter_column_survives(self, tmp_path: Path) -> None:
        """`mbis_parameter_<slot>` promised a per-atom row the source never had.

        The array it was built from is one row per Slater *shell*, so every
        column it produced mis-assigned a shell to whichever atom shared its row
        index. The columns are gone, not renamed.
        """
        atoms = self._record(tmp_path)["atoms"]
        assert [name for name in atoms.keys() if name.startswith(MBIS_PARAMETER_PREFIX)] == []

    def test_the_slater_shells_are_a_named_block_of_three_columns(self, tmp_path: Path) -> None:
        """Shell-major data cannot be an `atoms` column, so it is its own block."""
        record = self._record(tmp_path)
        assert MBIS_SHELL_BLOCK in record
        assert frozenset(record[MBIS_SHELL_BLOCK].keys()) == frozenset(MBIS_SHELL_BLOCK_COLUMNS)

    def test_the_shell_block_has_one_row_per_shell_not_per_atom(self, tmp_path: Path) -> None:
        """Four shells for three atoms — the oxygen carries two, each H one."""
        block = self._record(tmp_path)[MBIS_SHELL_BLOCK]
        assert [np.asarray(block[name]).shape for name in MBIS_SHELL_BLOCK_COLUMNS] == [(4,)] * 3
        assert np.asarray(self._record(tmp_path)["atoms"]["number"]).shape == (3,)

    def test_the_shell_atom_column_says_which_atom_each_shell_belongs_to(
        self, tmp_path: Path
    ) -> None:
        """Column 0 of the source, as integers: the oxygen's two shells are rows 1-2."""
        block = self._record(tmp_path)[MBIS_SHELL_BLOCK]
        assert np.asarray(block["atom"]).tolist() == list(MBIS_SHELL_ATOMS)

    def test_the_shell_populations_and_widths_keep_their_source_order(self, tmp_path: Path) -> None:
        """Columns 1 and 2, row by row: nothing is sorted, grouped or summed."""
        block = self._record(tmp_path)[MBIS_SHELL_BLOCK]
        assert np.asarray(block["population"]).tolist() == pytest.approx(
            list(MBIS_SHELL_POPULATIONS), abs=1e-10
        )
        assert np.asarray(block["inverse_width"]).tolist() == pytest.approx(
            list(MBIS_SHELL_WIDTHS), abs=1e-10
        )

    def test_the_shell_populations_sum_to_the_records_electron_count(self, tmp_path: Path) -> None:
        """The probed identity, embedded in the fixture: sum == Z.sum() - charge.sum().

        This is the evidence that column 1 is a *population* in electrons rather
        than a second width or an amplitude — it held exactly on every group of
        the 2026-08-15 probe, and it holds on this fixture by construction.
        """
        record = self._record(tmp_path)
        numbers = np.asarray(record["atoms"]["number"], dtype=np.float64)
        charges = np.asarray(record["atoms"]["atomic_charge"], dtype=np.float64)
        populations = np.asarray(record[MBIS_SHELL_BLOCK]["population"], dtype=np.float64)
        assert float(populations.sum()) == pytest.approx(MBIS_ELECTRON_COUNT, abs=1e-10)
        assert float(populations.sum()) == pytest.approx(
            float(numbers.sum() - charges.sum()), abs=1e-10
        )

    def test_the_shell_block_dtypes_are_int32_float64_float64(self, tmp_path: Path) -> None:
        """An atom index is an index; a population and a width keep float64."""
        block = self._record(tmp_path)[MBIS_SHELL_BLOCK]
        assert [np.asarray(block[name]).dtype.str for name in MBIS_SHELL_BLOCK_COLUMNS] == [
            "<i4",
            "<f8",
            "<f8",
        ]

    def test_a_shell_table_without_three_columns_is_refused(self, tmp_path: Path) -> None:
        """A shell row is `(atom, population, inverse_width)`; two of those is not a row."""
        path = self._refused(tmp_path, MBIS_SHELLS_WITHOUT_THREE_COLUMNS)
        with pytest.raises(ValueError, match=r"three columns") as error:
            THEMolMBIS(path).load()[0]
        assert "mbis-record" in str(error.value), "the refusal names the record it read"

    def test_a_fractional_shell_atom_index_is_refused(self, tmp_path: Path) -> None:
        """Column 0 is an atom index; 0.5 addresses no atom, so it is never rounded."""
        path = self._refused(tmp_path, MBIS_SHELLS_WITH_A_FRACTIONAL_ATOM_INDEX)
        with pytest.raises(ValueError, match=r"not integer-valued") as error:
            THEMolMBIS(path).load()[0]
        assert "mbis-record" in str(error.value)

    def test_a_shell_pointing_past_the_last_atom_is_refused(self, tmp_path: Path) -> None:
        """Atom 3 of a three-atom molecule is a defect, not a shell to drop."""
        path = self._refused(tmp_path, MBIS_SHELLS_WITH_AN_OUT_OF_RANGE_ATOM_INDEX)
        with pytest.raises(ValueError, match=r"outside \[0, 3\)") as error:
            THEMolMBIS(path).load()[0]
        assert "mbis-record" in str(error.value)

    def test_an_atom_left_without_any_shell_is_refused(self, tmp_path: Path) -> None:
        """Every atom has at least one shell, so a missing index means a lost row."""
        path = self._refused(tmp_path, MBIS_SHELLS_LEAVING_AN_ATOM_WITHOUT_A_SHELL)
        with pytest.raises(ValueError, match=r"no shell") as error:
            THEMolMBIS(path).load()[0]
        assert "mbis-record" in str(error.value)

    def test_the_declared_atom_level_schema_is_the_fourteen_fixed_columns(self) -> None:
        """Every declared name is a column a reader will actually find on the frame.

        The grouped names this schema carried before dissolution
        (``atomic_dipole`` / ``atomic_quadrupole`` / ``mbis_parameters``) match
        no column of any sample, so the pin is the post-dissolution set: the two
        scalars, the three dipole axes and the nine unfolded quadrupole
        components. The shell correction leaves it exactly as it was — the
        shells were never per-atom columns, so none of them was ever in here.
        """
        schema = THEMolMBIS.TARGET_SCHEMA
        assert isinstance(schema.atom_level, frozenset)
        assert schema.atom_level == MBIS_SCHEMA_ATOM_COLUMNS
        assert len(schema.atom_level) == 14
        assert schema.graph_level == frozenset(), "every MBIS target is per atom"

    def test_no_declared_target_names_a_slater_parameter_slot(self) -> None:
        """The slot names are not merely undeclared now — they do not exist."""
        declared = THEMolMBIS.TARGET_SCHEMA.atom_level
        assert not [name for name in declared if name.startswith(MBIS_PARAMETER_PREFIX)]

    def test_the_shell_block_is_the_datasets_one_declared_block(self) -> None:
        """`blocks` is where a reader is told to look somewhere other than `meta`."""
        assert THEMolMBIS.manifest.blocks == (MBIS_SHELL_BLOCK,)

    def test_the_shell_block_renders_as_a_block_level_feature(self) -> None:
        """The consequence of that declaration, read the way a user reads it.

        The derivation rule itself (``blocks`` outranks ``atom_level`` outranks
        ``graph_level``) is ``tests/test_loader/test_info.py``'s; what is pinned
        here is that *this* dataset's shipped declaration makes ``mbis_shells``
        come out as a block, which is only true if ``blocks`` names it.
        """
        feature = Feature.declared(
            MBIS_SHELL_BLOCK, schema=THEMolMBIS.TARGET_SCHEMA, manifest=THEMolMBIS.manifest
        )
        assert (feature.name, feature.level) == (MBIS_SHELL_BLOCK, "block")

    def test_the_shell_block_declares_no_single_unit_string(self) -> None:
        """One `Feature` carries one unit, and the block's columns disagree.

        ``population`` is in ``e`` and ``inverse_width`` in ``angstrom^-1``, so
        any single string here would be wrong for one of the two columns. The
        empty string says "not one quantity" honestly; the per-column units are
        the block's own documentation, pinned by the test below.
        """
        assert MBIS_SHELL_BLOCK not in THEMolMBIS.manifest.units
        feature = Feature.declared(
            MBIS_SHELL_BLOCK, schema=THEMolMBIS.TARGET_SCHEMA, manifest=THEMolMBIS.manifest
        )
        assert feature.units == ""

    def test_the_shell_columns_two_units_are_declared_quantities(self) -> None:
        """`population` is a charge-like electron count; `inverse_width` is the
        ``inverse_sigma`` THEMol already declares. Literals, not lookups: a unit
        is a scientific claim, so restating the dict would assert nothing.
        """
        assert THEMOL_UNITS["charge"] == "e"
        assert THEMOL_UNITS["inverse_sigma"] == "angstrom^-1"

    def test_the_units_declaration_still_covers_the_fourteen_atom_columns(self) -> None:
        """The shell block is added *beside* the per-atom units, not instead of them."""
        assert frozenset(THEMolMBIS.manifest.units) == MBIS_SCHEMA_ATOM_COLUMNS

    def test_an_array_whose_row_count_is_not_n_is_refused(self, tmp_path: Path) -> None:
        """Never broadcast: two charges for three atoms is a defective shard."""
        path = tmp_path / "shard-000.h5"
        _write_mbis(
            path,
            atomic_charge=np.asarray([[0.4], [-0.8]]),
            atomic_dipole=MBIS_DIPOLE,
            atomic_quadrupole=MBIS_QUADRUPOLE,
        )
        with pytest.raises(ValueError, match="atomic_charge"):
            THEMolMBIS(path).load()[0]


class TestTHEMolTorsionScan:
    """One complete torsion profile is a `Trajectory`, scalars in per-frame meta."""

    @staticmethod
    def _record(tmp_path: Path) -> Trajectory:
        path = tmp_path / "shard-000.h5"
        _write_torsion(path, relax=False)
        return THEMolTorsionScan(path).load()[0]

    def test_a_torsion_scan_record_is_a_frame_collection(self, tmp_path: Path) -> None:
        record = self._record(tmp_path)
        assert isinstance(record, Sequence)
        assert all(isinstance(frame, Frame) for frame in record)
        assert len(record) == 2

    def test_a_second_read_of_a_scan_matches_the_first(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_torsion(path, relax=False)
        dataset = THEMolTorsionScan(path).load()
        first = dataset[0]
        opened: list[int] = []
        snap = dataset._h5().snapshot

        def _count(name: str):
            opened.append(1)
            return snap(name)

        dataset._h5().snapshot = _count  # type: ignore[method-assign]
        second = dataset[0]
        assert opened == []
        assert [frame.meta["energy"] for frame in second] == [0.0, -1.0]
        assert [frame.meta["constraint_index"] for frame in second] == [0, 1]
        assert [frame.meta["torsion_angle"] for frame in second] == pytest.approx(
            [frame.meta["torsion_angle"] for frame in first]
        )
        assert [np.asarray(frame["atoms"]["x"]).tolist() for frame in second] == [
            np.asarray(frame["atoms"]["x"]).tolist() for frame in first
        ]

    def test_each_frame_carries_its_scan_scalars(self, tmp_path: Path) -> None:
        record = self._record(tmp_path)
        assert [record[index].meta["scan_id"] for index in range(2)] == [
            "scan-record",
            "scan-record",
        ]
        assert [record[index].meta["constraint_index"] for index in range(2)] == [0, 1]
        assert [record[index].meta["energy"] for index in range(2)] == [0.0, -1.0]

    def test_each_frame_carries_its_torsion_angle(self, tmp_path: Path) -> None:
        """Degrees; the two literals above, computed offline once."""
        record = self._record(tmp_path)
        angles = [record[index].meta["torsion_angle"] for index in range(2)]
        assert angles == pytest.approx(list(BUTANE_SCAN_ANGLES), abs=1e-9)

    def test_the_scanned_dihedral_is_a_one_row_scan_block(self, tmp_path: Path) -> None:
        """`frame.meta` rejects a len-4 sequence, so the tuple is a 1-row block."""
        block = self._record(tmp_path)[0]["scan"]
        assert frozenset(block.keys()) == frozenset({"atomi", "atomj", "atomk", "atoml"})
        assert [
            np.asarray(block[name]).tolist() for name in ("atomi", "atomj", "atomk", "atoml")
        ] == [[0], [1], [2], [3]]

    def test_every_frame_of_a_scan_carries_the_same_scan_block(self, tmp_path: Path) -> None:
        """The encoder inspects frame 0 only; this is what makes that sound."""
        record = self._record(tmp_path)
        names = ("atomi", "atomj", "atomk", "atoml")
        assert [np.asarray(record[0]["scan"][name]).tolist() for name in names] == [
            np.asarray(record[1]["scan"][name]).tolist() for name in names
        ]

    def test_a_zero_central_bond_scan_is_refused(self, tmp_path: Path) -> None:
        """An undefined dihedral is refused, never reported as some default angle."""
        path = tmp_path / "shard-000.h5"
        _write_torsion(path, relax=False)
        with h5py.File(path, "r+") as handle:
            coords = handle["scan-record/constraint 0/coords"]
            coords[2] = coords[1]
        with pytest.raises(ValueError, match="zero central bond"):
            THEMolTorsionScan(path).load()[0]


class TestTHEMolHessianRelax:
    """One relaxation is a `Trajectory` ordered by its per-frame `step_index`."""

    @staticmethod
    def _record(tmp_path: Path) -> Trajectory:
        path = tmp_path / "shard-000.h5"
        _write_hessian_relax(path)
        return THEMolHessianRelax(path).load()[0]

    def test_a_relaxation_record_is_a_frame_collection(self, tmp_path: Path) -> None:
        record = self._record(tmp_path)
        assert isinstance(record, Sequence)
        assert all(isinstance(frame, Frame) for frame in record)
        assert len(record) == 2

    def test_step_index_orders_the_frames(self, tmp_path: Path) -> None:
        """`optimization_steps` is gone; the step is a per-frame meta scalar."""
        record = self._record(tmp_path)
        assert [record[index].meta["step_index"] for index in range(2)] == [0, 1]

    def test_each_frame_carries_its_energy_and_forces(self, tmp_path: Path) -> None:
        record = self._record(tmp_path)
        assert [record[index].meta["energy"] for index in range(2)] == [-10.0, -10.5]
        assert np.asarray(record[1]["atoms"]["fx"]).tolist() == [2.0, 2.0, 2.0]

    def test_a_frame_disagreeing_with_the_topology_is_refused(self, tmp_path: Path) -> None:
        """Materializing eagerly means a ragged step fails at read, not at use."""
        path = tmp_path / "shard-000.h5"
        _write_hessian_relax(path)
        with h5py.File(path, "r+") as handle:
            del handle["relax-record/step 1/coords"]
            handle["relax-record/step 1"].create_dataset("coords", data=np.zeros((4, 3)))
        with pytest.raises(ValueError, match="shape"):
            THEMolHessianRelax(path).load()[0]


class TestTHEMolShardDatasetSplit:
    """``split`` is the record as a molrec system plus per-frame state."""

    def test_a_relaxation_splits_into_identity_and_state(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_hessian_relax(path)
        system, frames, steps = THEMolHessianRelax(path).load().split(0)
        assert sorted(system["atoms"].keys()) == [
            "atom_map",
            "atomic_number",
            "element",
            "equi_index",
            "formal_charge",
            "gaff2_epsilon",
            "gaff2_sigma",
            "min_ring_size",
            "ring_connectivity",
        ]
        assert np.asarray(system["atoms"]["atomic_number"]).dtype == np.uint64
        assert "bonds" in system.keys()
        assert {"molecule_id", "mapped_smiles", "total_charge"} <= set(system.meta)
        assert sorted(frames[1]["atoms"].keys()) == ["fx", "fy", "fz", "x", "y", "z"]
        assert [frame.meta["pe"] for frame in frames] == [-10.0, -10.5]
        assert steps == [0, 1]

    def test_a_torsion_scan_steps_by_constraint_and_keeps_its_scan_block(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "shard-000.h5"
        _write_torsion(path, relax=False)
        system, frames, steps = THEMolTorsionScan(path).load().split(0)
        assert "scan" in system.keys() and all("scan" not in f.keys() for f in frames)
        assert steps == [0, 1]
        assert set(frames[0].meta) == {"pe", "constraint_index", "torsion_angle"}


def test_definition_construction_is_io_free(tmp_path: Path) -> None:
    definition = THEMolHessian(tmp_path)
    assert definition.root == tmp_path.resolve()


def test_local_shard_role_is_preserved_in_provenance(tmp_path: Path) -> None:
    path = tmp_path / "shard-123"
    _write_hessian(path)
    record = THEMolHessian(tmp_path).load(role="shard-123")[0]
    source_id = getattr(record[0].meta["source_id"], "value", record[0].meta["source_id"])
    assert source_id.endswith("#role=shard-123")


def test_the_scanned_dihedral_is_declared_in_degrees() -> None:
    """`torsion_angle` is the one unit `hf-facade-03` added to the public dict.

    Written as a literal rather than read back out of `THEMOL_UNITS`: the point
    of the pin is that editing that dict is a decision somebody has to make
    twice.
    """
    assert THEMOL_UNITS["torsion_angle"] == "degree"


def test_themol_units_declares_exactly_these_quantities() -> None:
    """The public constant's key set — the nine that predate `hf-facade-03`, plus one.

    `THEMOL_UNITS` is exported in `molhub.dataset.themol.__all__` and every
    `@dataset` unit declaration in that module reads from it, so a dropped or
    renamed key silently empties a rendered `Feature.units`. Pinning the whole
    set makes that arrive here first.
    """
    assert set(THEMOL_UNITS) == {
        "coordinates",
        "energy",
        "forces",
        "hessian",
        "charge",
        "dipole",
        "quadrupole",
        "volume",
        "inverse_sigma",
        "torsion_angle",
    }


def test_the_gaff2_prior_declares_its_two_units() -> None:
    """Literals, like `torsion_angle` above: a unit is a claim, not a lookup."""
    assert GAFF2_UNITS == {"gaff2_sigma": "angstrom", "gaff2_epsilon": "kcal/mol"}


def test_the_gaff2_units_are_the_shipped_tables() -> None:
    """The declaration and the asset it describes cannot drift apart."""
    units = Gaff2LennardJones().units
    assert GAFF2_UNITS["gaff2_sigma"] == units["sigma"]
    assert GAFF2_UNITS["gaff2_epsilon"] == units["epsilon"]
