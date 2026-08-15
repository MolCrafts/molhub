"""Offline structural tests for grouped THEMol HDF5 adapters."""

from __future__ import annotations

import pickle
from collections.abc import Sequence
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
from molhub.dataset.themol import THEMOL_UNITS

WATER = "[O:2]([H:1])[H:3]"
BUTANE = "[H:1][C:2]([H:5])([H:6])[C:3]([H:7])([H:8])[C:4]([H:9])([H:10])[H:11]"
NEON = "[Ne:1]"


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

    ``parameters`` is one row **per atom**: the shipped default used to be a
    single ``(1, 3)`` row for a three-atom molecule, which the dissolved record
    now refuses (a per-atom target is never broadcast), so the default is a
    ``(N, arity)`` array like every other MBIS array here.
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
            data=np.asarray([[0.0, 1.0], [2.0, 3.0], [4.0, 5.0]])
            if parameters is None
            else parameters,
        )


class TestHessian:
    def test_topology_is_reordered_to_atom_map(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_hessian(path)
        dataset = THEMolHessian(path).load()
        record = dataset[0]
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
        assert np.asarray(restored[0]["hessian"]["value"]).shape == (81,)

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
        trajectory = THEMolHessianRelax(path).load()[0]
        assert len(trajectory.frames) == 2
        assert [frame.meta["step_index"] for frame in trajectory.frames] == [0, 1]
        assert [frame.meta["energy"] for frame in trajectory.frames] == [-10.0, -10.5]
        assert list(trajectory.frames[1]["atoms"]["fx"]) == [2.0, 2.0, 2.0]

    def test_torsion_scan_is_one_complete_profile(self, tmp_path: Path) -> None:
        """The profile is the record: one `Trajectory`, scalars in per-frame meta."""
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
        """The same fixture arrays, now read as `atoms` columns of one `Frame`."""
        path = tmp_path / "shard-000.h5"
        _write_mbis(path)
        atoms = THEMolMBIS(path).load()[0]["atoms"]
        assert np.asarray(atoms["atomic_charge"]).tolist() == pytest.approx([0.4, -0.8, 0.4])
        assert [np.asarray(atoms[name]).shape for name in MBIS_QUADRUPOLE_COLUMNS] == [(3,)] * 9
        assert [
            np.asarray(atoms[name]).tolist() for name in ("dipole_x", "dipole_y", "dipole_z")
        ] == [[1.0] * 3] * 3
        assert [np.asarray(atoms[name]).tolist() for name in MBIS_PARAMETER_COLUMNS] == [
            [0.0, 2.0, 4.0],
            [1.0, 3.0, 5.0],
        ]


# ---------------------------------------------------------------------------
# Goldens for the dissolved records — spec `hf-facade-02-frame-records`, D1.
# A record IS a molpy object: one geometry is a `Frame`, a multi-frame sampling
# unit is a `Trajectory`, and the payload the four dataclasses used to hold
# moves onto blocks / atom columns / per-frame `meta`.
# ---------------------------------------------------------------------------

# The atom columns `_mapped_topology_frame` already writes for every task. The
# MBIS supervision columns are pinned below as the exact difference from this
# set, so a stray extra column is a failure rather than a silent addition.
GEOMETRY_ATOM_COLUMNS = frozenset({"element", "number", "atom_map", "formal_charge", "x", "y", "z"})

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

# The Slater parameters arrive as one unnamed `(N, arity)` array, so the columns
# are numbered by slot. Arity 2 is *this fixture's*, read off its shape and
# pinned as a literal exactly as D1 requires.
MBIS_PARAMETER_COLUMNS = ("mbis_parameter_0", "mbis_parameter_1")

MBIS_ATOM_COLUMNS = frozenset(
    {
        "atomic_charge",
        "atomic_volume",
        "dipole_x",
        "dipole_y",
        "dipole_z",
        *MBIS_QUADRUPOLE_COLUMNS,
        *MBIS_PARAMETER_COLUMNS,
    }
)

# What `THEMolMBIS.TARGET_SCHEMA.atom_level` declares: the fourteen columns whose
# names the *format* fixes, spelled out rather than composed from the tuples
# above, so that editing one of those tuples cannot silently move the schema
# pin with it. The Slater-parameter columns are deliberately absent — their
# arity is the shard's, read off an `(N, arity)` array at load time, and a class
# attribute is built without IO (see the `THEMolMBIS` docstring).
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

# Per-atom Slater parameters, one row per atom and two slots per row.
MBIS_PARAMETERS = np.asarray([[0.5, 1.5], [2.5, 3.5], [4.5, 5.5]], dtype=np.float64)

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
    frame.meta.update(
        {
            "energy": -10.0 - index,
            "torsion_angle": 30.0 * index,
            "scan_id": "scan-record",
            "constraint_index": index,
        }
    )
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

    def test_keys_are_a_tuple_of_strings(self, tmp_path: Path) -> None:
        """A tuple, not a ``KeysView``: an index into it has to mean something."""
        keys = THEMolHessian(self._shard(tmp_path)).load().keys()
        assert isinstance(keys, tuple)
        assert [type(key) for key in keys] == [str, str]

    def test_keys_are_positionally_aligned_with_indexing(self, tmp_path: Path) -> None:
        """``keys()[i]`` names the record ``self[i]`` reads — the join's whole basis."""
        shard = THEMolHessian(self._shard(tmp_path)).load()
        read = [shard[index].meta["source_record_id"] for index in range(len(shard))]
        assert read == ["eq-record-0", "eq-record-1"]
        assert read == list(shard.keys())


class TestTHEMolHessian:
    """One equilibrium record is a `Frame` carrying its Hessian as a COO block."""

    @staticmethod
    def _record(tmp_path: Path) -> Frame:
        path = tmp_path / "shard-000.h5"
        _write_hessian(path)
        return THEMolHessian(path).load()[0]

    def test_a_hessian_record_is_a_molpy_frame(self, tmp_path: Path) -> None:
        """No wrapper object on top of Frame — the record IS the molpy object."""
        assert isinstance(self._record(tmp_path), Frame)

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
        values = np.asarray(THEMolHessian(path).load()[0]["hessian"]["value"])
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
        assert isinstance(record, Frame)
        assert "bonds" not in record
        assert np.asarray(record["hessian"]["value"]).shape == (9,)


class TestTHEMolMBIS:
    """One MBIS record is a `Frame` whose supervision lives in `atoms` columns."""

    @staticmethod
    def _record(tmp_path: Path) -> Frame:
        path = tmp_path / "shard-000.h5"
        _write_mbis(
            path,
            atomic_dipole=MBIS_DIPOLE,
            atomic_quadrupole=MBIS_QUADRUPOLE,
            parameters=MBIS_PARAMETERS,
        )
        return THEMolMBIS(path).load()[0]

    def test_an_mbis_record_is_a_molpy_frame(self, tmp_path: Path) -> None:
        assert isinstance(self._record(tmp_path), Frame)

    def test_the_atoms_block_carries_exactly_the_mbis_columns(self, tmp_path: Path) -> None:
        """Geometry plus MBIS and nothing else — an extra column arrived unrouted."""
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

    def test_the_parameter_columns_follow_the_source_arity(self, tmp_path: Path) -> None:
        """`(N, 2)` in, two numbered columns out — the arity is read, not assumed."""
        atoms = self._record(tmp_path)["atoms"]
        assert np.asarray(atoms["mbis_parameter_0"]).tolist() == pytest.approx(
            [0.5, 2.5, 4.5], abs=1e-10
        )
        assert np.asarray(atoms["mbis_parameter_1"]).tolist() == pytest.approx(
            [1.5, 3.5, 5.5], abs=1e-10
        )

    def test_the_declared_atom_level_schema_is_the_fourteen_fixed_columns(self) -> None:
        """Every declared name is a column a reader will actually find on the frame.

        The grouped names this schema carried before dissolution
        (``atomic_dipole`` / ``atomic_quadrupole`` / ``mbis_parameters``) match
        no column of any sample, so the pin is the post-dissolution set: the two
        scalars, the three dipole axes and the nine unfolded quadrupole
        components.
        """
        schema = THEMolMBIS.TARGET_SCHEMA
        assert isinstance(schema.atom_level, frozenset)
        assert schema.atom_level == MBIS_SCHEMA_ATOM_COLUMNS
        assert len(schema.atom_level) == 14
        assert schema.graph_level == frozenset(), "every MBIS target is per atom"

    def test_the_slater_parameter_columns_are_deliberately_undeclared(self, tmp_path: Path) -> None:
        """Declared columns are format-fixed; the parameter arity is the shard's.

        ``mbis_parameter_<slot>`` exists on the frame — the fixture's arity is 2,
        pinned above — but the schema is a class attribute built without IO, so
        declaring the slots would mean inventing an arity the format does not
        fix. The omission is a decision, and this is what keeps it from decaying
        into an accident.
        """
        declared = THEMolMBIS.TARGET_SCHEMA.atom_level
        assert not [name for name in declared if name.startswith("mbis_parameter")]
        assert MBIS_PARAMETER_COLUMNS  # the fixture's arity, read off its (N, 2) array
        assert frozenset(self._record(tmp_path)["atoms"].keys()) >= frozenset(
            MBIS_PARAMETER_COLUMNS
        ), "the columns the schema declines to name are still on the record"

    def test_an_array_whose_row_count_is_not_n_is_refused(self, tmp_path: Path) -> None:
        """Never broadcast: two charges for three atoms is a defective shard."""
        path = tmp_path / "shard-000.h5"
        _write_mbis(
            path,
            atomic_charge=np.asarray([[0.4], [-0.8]]),
            atomic_dipole=MBIS_DIPOLE,
            atomic_quadrupole=MBIS_QUADRUPOLE,
            parameters=MBIS_PARAMETERS,
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

    def test_a_torsion_scan_record_is_a_trajectory(self, tmp_path: Path) -> None:
        record = self._record(tmp_path)
        assert isinstance(record, Trajectory)
        assert len(record) == 2

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

    def test_a_relaxation_record_is_a_trajectory(self, tmp_path: Path) -> None:
        record = self._record(tmp_path)
        assert isinstance(record, Trajectory)
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


def test_definition_construction_is_io_free(tmp_path: Path) -> None:
    definition = THEMolHessian(tmp_path)
    assert definition.root == tmp_path.resolve()


def test_local_shard_role_is_preserved_in_provenance(tmp_path: Path) -> None:
    path = tmp_path / "shard-123"
    _write_hessian(path)
    record = THEMolHessian(tmp_path).load(role="shard-123")[0]
    assert record.meta["source_id"].endswith("#role=shard-123")


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
