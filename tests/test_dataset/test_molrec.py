"""Tests for the MolRec source — a molpy ``MolRec`` (.zarr) record as a dataset.

A *labeled-configuration record* stores conformers in the record's trajectory
and teacher labels in the flat ``observables`` map, keyed ``"<teacher>.<name>"``.
One record may carry several teachers; a :class:`MolRecDataset` is pinned to
exactly one at construction and exposes that teacher's observables as targets
with the prefix stripped.

The behaviour pinned here is lifted from the deleted molnex
``tests/test_molix/test_datasets/test_molrec.py`` and its conftest fixtures
(molnex commit ``6d425f7^``): record → sample mapping, per-instance target-schema
derivation (scalar → graph-level, vector → atom-level), teacher isolation, and
identity stability. The fixture values are re-expressed as hand-built, exactly
representable literals (molnex seeded ``numpy.random.default_rng``), so every
expected number in this file is a literal, not a draw.

Everything is offline: the ``.zarr`` archives are written into ``tmp_path`` by
the fixtures below.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from molpy import Block, Box, Frame, MolRec, Trajectory

from molhub.dataset import Dataset
from molhub.dataset.molrec import MolRecDataset
from molhub.dataset.protocol import TargetSchema

# ---------------------------------------------------------------------------
# Fixture values — hand-built, all exactly representable in binary
# ---------------------------------------------------------------------------

#: Three molecules with different atom counts, so ragged frames are exercised.
_CH4_ELEMENTS = ("C", "H", "H", "H", "H")
_CH4_Z = [6, 1, 1, 1, 1]
_CH4_POS = np.array(
    [
        [0.0, 0.0, 0.0],
        [0.5, 0.5, 0.5],
        [-0.5, -0.5, 0.5],
        [0.5, -0.5, -0.5],
        [-0.5, 0.5, -0.5],
    ]
)

_H2O_ELEMENTS = ("O", "H", "H")
_H2O_Z = [8, 1, 1]
_H2O_POS = np.array([[0.0, 0.0, 0.0], [0.75, 0.5, 0.0], [-0.75, 0.5, 0.0]])

_NH3_ELEMENTS = ("N", "H", "H", "H")
_NH3_Z = [7, 1, 1, 1]
_NH3_POS = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.25], [-0.5, 0.75, 0.25], [-0.5, -0.75, 0.25]])

#: ``teacherA`` scalar labels on the 3-conformer record.
_U0 = (-40.5, -76.25, -56.0)
_GAP = (0.25, 0.5, 0.75)

#: The 4-frame, 3-atom, two-teacher record.
_DIMER_ELEMENTS = ("H", "H", "O")
_DIMER_Z = [1, 1, 8]
_ENERGY_A = (-10.0, -8.5, -7.0, -5.5)
_ENERGY_B = (3.5, 1.25, -1.0, -3.25)
#: ``(n_frames, n_atoms, 3)`` — frame f, atom a, component c holds
#: ``0.25 * f + 0.5 * a + 0.125 * c``.
_FORCES_A = np.array(
    [
        [[0.0, 0.125, 0.25], [0.5, 0.625, 0.75], [1.0, 1.125, 1.25]],
        [[0.25, 0.375, 0.5], [0.75, 0.875, 1.0], [1.25, 1.375, 1.5]],
        [[0.5, 0.625, 0.75], [1.0, 1.125, 1.25], [1.5, 1.625, 1.75]],
        [[0.75, 0.875, 1.0], [1.25, 1.375, 1.5], [1.75, 1.875, 2.0]],
    ]
)

_BOX_EDGE = 20.0


@dataclass(frozen=True)
class MolRecFixture:
    """A written ``.zarr`` archive and the number of frames it holds.

    The values that went into it are the module-level literals above, so a test
    compares against those rather than against whatever came back off disk.
    """

    path: Path
    n_frames: int


def _frame(elements: tuple[str, ...], xyz: np.ndarray) -> Frame:
    frame = Frame()
    block = Block()
    block.insert("element", np.array(elements, dtype=np.str_))
    block.insert("x", np.ascontiguousarray(xyz[:, 0], dtype=np.float64))
    block.insert("y", np.ascontiguousarray(xyz[:, 1], dtype=np.float64))
    block.insert("z", np.ascontiguousarray(xyz[:, 2], dtype=np.float64))
    frame["atoms"] = block
    frame.box = Box(np.eye(3) * _BOX_EDGE)
    return frame


def _record(frames: list[Frame]) -> MolRec:
    record = MolRec()
    record.set_trajectory(Trajectory.from_frames(frames))
    # molpy >= 0.12 wants the fixed topology the series is a series *of*.
    record.set_system(frames[0])
    return record


def _add_scalar(record: MolRec, key: str, values: tuple[float, ...]) -> None:
    record.observables.add_scalar(
        key,
        np.asarray(values, dtype=np.float64),
        unit="eV",
        axes=["timestep"],
        time_dependent=True,
        domain="trajectory",
    )


@pytest.fixture
def conformer_record(tmp_path) -> MolRecFixture:
    """Three heterogeneous molecules, ``teacherA`` scalars only (no forces)."""
    frames = [
        _frame(_CH4_ELEMENTS, _CH4_POS),
        _frame(_H2O_ELEMENTS, _H2O_POS),
        _frame(_NH3_ELEMENTS, _NH3_POS),
    ]
    record = _record(frames)
    _add_scalar(record, "teacherA.U0", _U0)
    _add_scalar(record, "teacherA.gap", _GAP)
    record.method = {"teacherA": {"theory_level": "DFT/PBE", "model_id": "toy"}}

    path = tmp_path / "qm9_rec.zarr"
    record.write_zarr(str(path))
    return MolRecFixture(path=path, n_frames=len(frames))


@pytest.fixture
def force_record(tmp_path) -> MolRecFixture:
    """Four frames of one 3-atom system, two teachers, forces on ``teacherA``."""
    frames = [_frame(_DIMER_ELEMENTS, _H2O_POS + 0.25 * i) for i in range(len(_ENERGY_A))]
    record = _record(frames)
    _add_scalar(record, "teacherA.energy", _ENERGY_A)
    record.observables.add_vector(
        "teacherA.forces",
        _FORCES_A,
        unit="eV/Angstrom",
        axes=["timestep", "atom", "component"],
        time_dependent=True,
        domain="trajectory",
    )
    _add_scalar(record, "teacherB.energy", _ENERGY_B)
    record.method = {
        "teacherA": {"theory_level": "DFT/PBE", "model_id": "toyA"},
        "teacherB": {"theory_level": "DFT/B3LYP", "model_id": "toyB"},
    }

    path = tmp_path / "force_rec.zarr"
    record.write_zarr(str(path))
    return MolRecFixture(path=path, n_frames=len(_ENERGY_A))


@pytest.fixture
def empty_record(tmp_path) -> MolRecFixture:
    """A record with a trajectory but no observables at all."""
    record = _record([_frame(_H2O_ELEMENTS, _H2O_POS)])
    path = tmp_path / "empty_rec.zarr"
    record.write_zarr(str(path))
    return MolRecFixture(path=path, n_frames=1)


# ---------------------------------------------------------------------------
# Record -> sample mapping
# ---------------------------------------------------------------------------


class TestMolRecRecordToSample:
    def test_frame_count(self, conformer_record):
        frames = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()
        assert len(frames) == 3

    def test_loaded_collection_is_a_map_dataset(self, conformer_record):
        frames = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()
        assert isinstance(frames, Dataset)

    def test_sample_is_a_molpy_frame(self, conformer_record):
        frames = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()
        assert isinstance(frames[0], Frame)

    def test_atoms_block_columns(self, conformer_record):
        atoms = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()[0]["atoms"]
        for column in ("element", "x", "y", "z", "number"):
            assert column in atoms

    def test_heterogeneous_atom_counts_are_preserved(self, conformer_record):
        frames = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()
        assert [frames[i]["atoms"].nrows for i in range(len(frames))] == [5, 3, 4]

    def test_atomic_numbers_are_mapped_from_symbols(self, conformer_record):
        frames = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()
        assert list(frames[0]["atoms"]["number"]) == _CH4_Z
        assert list(frames[1]["atoms"]["number"]) == _H2O_Z
        assert list(frames[2]["atoms"]["number"]) == _NH3_Z

    def test_positions_round_trip_losslessly(self, conformer_record):
        """Position tolerance 1e-12; the write→read path must not perturb them."""
        atoms = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()[1]["atoms"]
        assert np.allclose(np.asarray(atoms["x"]), _H2O_POS[:, 0], atol=1e-12)
        assert np.allclose(np.asarray(atoms["y"]), _H2O_POS[:, 1], atol=1e-12)
        assert np.allclose(np.asarray(atoms["z"]), _H2O_POS[:, 2], atol=1e-12)

    def test_box_is_carried_onto_the_frame(self, conformer_record):
        frame = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()[0]
        assert np.allclose(np.asarray(frame.box.matrix), np.eye(3) * _BOX_EDGE, atol=1e-12)

    def test_scalar_observables_become_graph_level_targets(self, conformer_record):
        frame = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()[0]
        assert set(frame.meta) == {"U0", "gap"}

    def test_target_names_strip_the_teacher_prefix(self, conformer_record):
        frame = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()[0]
        assert not any(key.startswith("teacherA.") for key in frame.meta)

    def test_scalar_target_values_are_per_frame(self, conformer_record):
        """Energy tolerance 1e-10 — the write→read path is expected to be exact."""
        frames = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()
        got = [float(frames[i].meta["U0"]) for i in range(len(frames))]
        for value, want in zip(got, _U0):
            assert value == pytest.approx(want, abs=1e-10)

    def test_second_scalar_target_is_not_mixed_with_the_first(self, conformer_record):
        frames = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()
        got = [float(frames[i].meta["gap"]) for i in range(len(frames))]
        for value, want in zip(got, _GAP):
            assert value == pytest.approx(want, abs=1e-10)

    def test_scalar_target_is_a_plain_float(self, conformer_record):
        frame = MolRecDataset(conformer_record.path, teacher_id="teacherA").load()[0]
        assert isinstance(frame.meta["U0"], float)

    def test_repeated_topology_atomic_numbers(self, force_record):
        frames = MolRecDataset(force_record.path, teacher_id="teacherA").load()
        assert list(frames[0]["atoms"]["number"]) == _DIMER_Z

    def test_vector_observable_becomes_atom_level_columns(self, force_record):
        atoms = MolRecDataset(force_record.path, teacher_id="teacherA").load()[0]["atoms"]
        for column in ("fx", "fy", "fz"):
            assert column in atoms

    def test_force_columns_have_one_row_per_atom(self, force_record):
        atoms = MolRecDataset(force_record.path, teacher_id="teacherA").load()[0]["atoms"]
        assert np.asarray(atoms["fx"]).shape == (3,)

    def test_force_values_round_trip_losslessly(self, force_record):
        """Force tolerance 1e-8; the fixture values are binary-exact."""
        frames = MolRecDataset(force_record.path, teacher_id="teacherA").load()
        for i in range(len(frames)):
            atoms = frames[i]["atoms"]
            assert np.allclose(np.asarray(atoms["fx"]), _FORCES_A[i, :, 0], atol=1e-8)
            assert np.allclose(np.asarray(atoms["fy"]), _FORCES_A[i, :, 1], atol=1e-8)
            assert np.allclose(np.asarray(atoms["fz"]), _FORCES_A[i, :, 2], atol=1e-8)


# ---------------------------------------------------------------------------
# Per-instance target schema
# ---------------------------------------------------------------------------


class TestMolRecTargetSchema:
    def test_there_is_no_class_level_schema(self):
        """Unlike QM9 / 3BPA, the schema depends on the record, not the class."""
        assert "TARGET_SCHEMA" not in vars(MolRecDataset)

    def test_schema_is_a_target_schema(self, conformer_record):
        src = MolRecDataset(conformer_record.path, teacher_id="teacherA")
        assert isinstance(src.target_schema, TargetSchema)

    def test_scalars_land_in_graph_level(self, conformer_record):
        src = MolRecDataset(conformer_record.path, teacher_id="teacherA")
        assert src.target_schema.graph_level == frozenset({"U0", "gap"})

    def test_a_scalar_only_record_has_no_atom_level_targets(self, conformer_record):
        src = MolRecDataset(conformer_record.path, teacher_id="teacherA")
        assert src.target_schema.atom_level == frozenset()

    def test_vectors_land_in_atom_level(self, force_record):
        src = MolRecDataset(force_record.path, teacher_id="teacherA")
        assert src.target_schema.atom_level == frozenset({"forces"})

    def test_energy_stays_graph_level_when_forces_are_present(self, force_record):
        src = MolRecDataset(force_record.path, teacher_id="teacherA")
        assert src.target_schema.graph_level == frozenset({"energy"})

    def test_schema_follows_the_selected_teacher(self, force_record):
        """teacherB carries no forces, so its schema has no atom-level target."""
        src = MolRecDataset(force_record.path, teacher_id="teacherB")
        assert src.target_schema.atom_level == frozenset()


# ---------------------------------------------------------------------------
# Teacher isolation
# ---------------------------------------------------------------------------


class TestMolRecTeacherIsolation:
    def test_a_teacher_view_sees_only_its_own_targets(self, force_record):
        frame = MolRecDataset(force_record.path, teacher_id="teacherB").load()[0]
        assert set(frame.meta) == {"energy"}

    def test_teacher_a_energies(self, force_record):
        frames = MolRecDataset(force_record.path, teacher_id="teacherA").load()
        got = [float(frames[i].meta["energy"]) for i in range(len(frames))]
        for value, want in zip(got, _ENERGY_A):
            assert value == pytest.approx(want, abs=1e-10)

    def test_teacher_b_energies(self, force_record):
        frames = MolRecDataset(force_record.path, teacher_id="teacherB").load()
        got = [float(frames[i].meta["energy"]) for i in range(len(frames))]
        for value, want in zip(got, _ENERGY_B):
            assert value == pytest.approx(want, abs=1e-10)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestMolRecSourceId:
    def test_source_id_literal(self, conformer_record):
        """Cache invalidation hangs off this string; it is pinned verbatim."""
        src = MolRecDataset(conformer_record.path, teacher_id="teacherA")
        assert src.source_id == "molrec:qm9_rec#teacher=teacherA"

    def test_source_id_is_deterministic(self, force_record):
        a = MolRecDataset(force_record.path, teacher_id="teacherA").source_id
        b = MolRecDataset(force_record.path, teacher_id="teacherA").source_id
        assert a == b

    def test_source_id_differs_per_teacher(self, force_record):
        a = MolRecDataset(force_record.path, teacher_id="teacherA").source_id
        b = MolRecDataset(force_record.path, teacher_id="teacherB").source_id
        assert a != b

    def test_subset_view_source_id_literal(self, conformer_record):
        src = MolRecDataset(conformer_record.path, teacher_id="teacherA", total=2)
        assert src.source_id == "molrec:qm9_rec#teacher=teacherA,total=2"

    def test_source_id_carries_no_local_details(self, conformer_record):
        """molnex folded byte size and frame count in; molhub does not."""
        source_id = MolRecDataset(conformer_record.path, teacher_id="teacherA").source_id
        assert "size=" not in source_id
        assert "n=" not in source_id


class TestMolRecSubset:
    def test_total_truncates_the_trajectory(self, conformer_record):
        frames = MolRecDataset(conformer_record.path, teacher_id="teacherA", total=2).load()
        assert len(frames) == 2

    def test_total_keeps_the_leading_frames(self, conformer_record):
        frames = MolRecDataset(conformer_record.path, teacher_id="teacherA", total=2).load()
        assert [frames[i]["atoms"].nrows for i in range(len(frames))] == [5, 3]

    def test_total_larger_than_the_record_is_a_no_op(self, conformer_record):
        frames = MolRecDataset(conformer_record.path, teacher_id="teacherA", total=99).load()
        assert len(frames) == 3


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TestMolRecErrors:
    def test_missing_record_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            MolRecDataset(tmp_path / "absent.zarr", teacher_id="teacherA")

    def test_unknown_teacher_raises(self, force_record):
        with pytest.raises(ValueError):
            MolRecDataset(force_record.path, teacher_id="teacherZ")

    def test_unknown_teacher_lists_the_available_prefixes(self, force_record):
        with pytest.raises(ValueError, match="teacherA"):
            MolRecDataset(force_record.path, teacher_id="teacherZ")

    def test_unknown_teacher_lists_every_available_prefix(self, force_record):
        with pytest.raises(ValueError, match="teacherB"):
            MolRecDataset(force_record.path, teacher_id="teacherZ")

    def test_record_without_observables_raises(self, empty_record):
        """An empty observable set is malformed for a labelled record."""
        with pytest.raises(ValueError):
            MolRecDataset(empty_record.path, teacher_id="teacherA")
