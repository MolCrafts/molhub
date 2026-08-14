"""Offline structural tests for grouped THEMol HDF5 adapters."""

from __future__ import annotations

import pickle
from pathlib import Path

import h5py
import numpy as np
import pytest

import molhub.dataset.themol as themol_module
from molhub.dataset import (
    THEMolHessian,
    THEMolHessianRelax,
    THEMolMBIS,
    THEMolTorsionRelax,
    THEMolTorsionScan,
)

WATER = "[O:2]([H:1])[H:3]"
BUTANE = "[H:1][C:2]([H:5])([H:6])[C:3]([H:7])([H:8])[C:4]([H:9])([H:10])[H:11]"


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


def _write_hessian(path: Path) -> None:
    with h5py.File(path, "w") as handle:
        group = handle.create_group("eq-record")
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


def _write_mbis(path: Path) -> None:
    with h5py.File(path, "w") as handle:
        group = handle.create_group("mbis-record")
        _identity(group, WATER, [1, 8, 1])
        group.create_dataset("coords", data=_water_coords())
        info = group.create_group("mbis_info")
        info.create_dataset("atomic_volumes", data=np.ones((3, 1)))
        info.create_dataset("atomic_charge", data=np.asarray([[0.4], [-0.8], [0.4]]))
        info.create_dataset("atomic_dipole", data=np.ones((3, 3)))
        info.create_dataset("atomic_quadrupole", data=np.ones((3, 3, 3)))
        group.create_dataset("parameters", data=np.asarray([[0.0, 1.0, 2.0]]))


class TestHessian:
    def test_topology_is_reordered_to_atom_map(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_hessian(path)
        dataset = THEMolHessian(path).load()
        record = dataset[0]
        assert list(record.frame["atoms"]["number"]) == [1, 8, 1]
        assert list(record.frame["atoms"]["atom_map"]) == [1, 2, 3]
        assert list(record.frame["bonds"]["atomi"]) == [1, 1]
        assert list(record.frame["bonds"]["atomj"]) == [0, 2]
        assert record.hessian.shape == (9, 9)
        assert record.frame.meta["source_record_id"] == "eq-record"
        assert record.frame.meta["total_charge"] == 0

    def test_worker_pickle_does_not_capture_h5_handle(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_hessian(path)
        dataset = THEMolHessian(path).load()
        dataset[0]
        restored = pickle.loads(pickle.dumps(dataset))
        assert restored[0].hessian.shape == (9, 9)

    def test_atomic_number_mismatch_fails_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_hessian(path)
        with h5py.File(path, "r+") as handle:
            handle["eq-record/atomic_numbers"][0, 0] = 6
        with pytest.raises(ValueError, match="atomic-number mismatch"):
            THEMolHessian(path).load()[0]


class TestGroupedTasks:
    def test_relaxation_record_is_lazy_until_frame_access(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "shard-000.h5"
        _write_hessian_relax(path)

        def forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("topology parsing must be lazy")

        monkeypatch.setattr(themol_module, "_mapped_topology_frame", forbidden)
        trajectory = THEMolHessianRelax(path).load()[0]
        assert len(trajectory.frames) == 2
        with pytest.raises(AssertionError, match="topology parsing must be lazy"):
            trajectory.frames[0]

    def test_hessian_relax_preserves_ordered_trajectory(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_hessian_relax(path)
        trajectory = THEMolHessianRelax(path).load()[0]
        assert len(trajectory.frames) == 2
        assert [frame.meta["step_index"] for frame in trajectory.frames] == [0, 1]
        assert [frame.meta["energy"] for frame in trajectory.frames] == [-10.0, -10.5]
        assert list(trajectory.frames[1]["atoms"]["fx"]) == [2.0, 2.0, 2.0]

    def test_torsion_scan_is_one_complete_profile(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_torsion(path, relax=False)
        profile = THEMolTorsionScan(path).load()[0]
        assert profile.scan_id == "scan-record"
        assert profile.torsion_atom_indices == (0, 1, 2, 3)
        assert len(profile.frames) == len(profile.angles) == 2
        assert [frame.meta["constraint_index"] for frame in profile.frames] == [0, 1]
        assert profile.molecule_id != profile.scan_id

    def test_torsion_relax_preserves_constraint_and_step(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_torsion(path, relax=True)
        profile = THEMolTorsionRelax(path).load()[0]
        assert len(profile.frames) == 4
        assert profile.optimization_steps == (0, 1, 0, 1)
        assert [frame.meta["constraint_index"] for frame in profile.frames] == [
            0,
            0,
            1,
            1,
        ]

    def test_mbis_remains_a_rich_separate_record(self, tmp_path: Path) -> None:
        path = tmp_path / "shard-000.h5"
        _write_mbis(path)
        record = THEMolMBIS(path).load()[0]
        assert record.atomic_charge[:, 0].tolist() == pytest.approx([0.4, -0.8, 0.4])
        assert record.atomic_dipole.shape == (3, 3)
        assert record.atomic_quadrupole.shape == (3, 3, 3)
        assert record.parameters.shape == (1, 3)


def test_definition_construction_is_io_free(tmp_path: Path) -> None:
    definition = THEMolHessian(tmp_path)
    assert definition.root == tmp_path.resolve()


def test_local_shard_role_is_preserved_in_provenance(tmp_path: Path) -> None:
    path = tmp_path / "shard-123"
    _write_hessian(path)
    record = THEMolHessian(tmp_path).load(role="shard-123")[0]
    assert record.frame.meta["source_id"].endswith("#role=shard-123")
