"""Lazy, group-preserving adapters for the official THEMol HDF5 shards.

The adapters expose a shard as a map-style collection without flattening a
torsion scan or optimization trajectory into interchangeable frames.  Dataset
definition construction performs no IO; :meth:`load` is the explicit fetch and
index boundary.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar, overload

import numpy as np
from molpy import Block, Element, Frame

from molhub.dataset.definition import dataset
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.protocol import TargetSchema

__all__ = [
    "THEMOL_UNITS",
    "HessianRecord",
    "EnergyForceTrajectory",
    "TorsionProfile",
    "MBISRecord",
    "THEMolShardDataset",
    "THEMolHessian",
    "THEMolHessianRelax",
    "THEMolTorsionScan",
    "THEMolTorsionRelax",
    "THEMolMBIS",
]

THEMOL_UNITS = {
    "coordinates": "angstrom",
    "energy": "kcal/mol",
    "forces": "kcal/mol/angstrom",
    "hessian": "kcal/mol/angstrom^2",
    "charge": "e",
    "dipole": "e*angstrom",
    "quadrupole": "e*angstrom^2",
    "volume": "angstrom^3",
    "inverse_sigma": "angstrom^-1",
}


@dataclass(frozen=True)
class HessianRecord:
    """One equilibrium molecular graph, geometry, and Cartesian Hessian."""

    molecule_id: str
    frame: Frame
    hessian: np.ndarray


@dataclass(frozen=True)
class EnergyForceTrajectory:
    """One molecule's ordered, lazily materialized E/F frames."""

    molecule_id: str
    frames: Sequence[Frame]


@dataclass(frozen=True)
class TorsionProfile:
    """One complete torsion profile, kept intact as the training object."""

    molecule_id: str
    scan_id: str
    torsion_atom_indices: tuple[int, int, int, int]
    angles: Sequence[float]
    frames: Sequence[Frame]
    optimization_steps: tuple[int, ...] | None = None


@dataclass(frozen=True)
class MBISRecord:
    """One geometry with rich MBIS supervision kept outside ``Frame.meta``."""

    molecule_id: str
    frame: Frame
    atomic_volumes: np.ndarray
    atomic_charge: np.ndarray
    atomic_dipole: np.ndarray
    atomic_quadrupole: np.ndarray
    parameters: np.ndarray


RecordT = TypeVar("RecordT")


class THEMolShardDataset(Generic[RecordT]):
    """Lazy map-style view of one immutable THEMol HDF5 shard.

    HDF5 handles are opened lazily per process, so a collection can be safely
    pickled into DataLoader workers.  Only group keys are indexed in memory;
    molecular arrays are read on ``__getitem__``.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        source_id: str,
        reader: Callable[[Any, str, str], RecordT],
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file() or self.path.stat().st_size == 0:
            raise FileNotFoundError(f"THEMol shard is missing or empty: {self.path}")
        self.source_id = source_id
        self._reader = reader
        self._pid: int | None = None
        self._handle: Any | None = None
        with _open_h5(self.path) as handle:
            self._keys = tuple(handle.keys())

    def __len__(self) -> int:
        return len(self._keys)

    @overload
    def __getitem__(self, index: int) -> RecordT: ...

    @overload
    def __getitem__(self, index: slice) -> list[RecordT]: ...

    def __getitem__(self, index: int | slice) -> RecordT | list[RecordT]:
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        key = self._keys[index]
        return self._reader(self._h5(), key, self.source_id)

    def close(self) -> None:
        """Close this process's lazy HDF5 handle, if one was opened."""
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self._pid = None

    def __getstate__(self) -> dict[str, Any]:
        state = dict(self.__dict__)
        state["_handle"] = None
        state["_pid"] = None
        return state

    def _h5(self) -> Any:
        pid = os.getpid()
        if self._handle is None or self._pid != pid:
            self.close()
            self._handle = _open_h5(self.path)
            self._pid = pid
        return self._handle

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def _open_h5(path: Path) -> Any:
    try:
        import h5py
    except ImportError as error:
        raise ImportError(
            "Reading THEMol requires h5py; install molhub with its THEMol dependencies."
        ) from error
    return h5py.File(path, "r")


def _read_string(dataset: Any) -> str:
    value = dataset.asstr()[()]
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _molecule_id(group: Any) -> str:
    mapped_isomeric = _read_string(group["mapped_isomeric_smiles"])
    return uuid.uuid5(uuid.UUID(int=0), mapped_isomeric).hex


def _mapped_topology_frame(
    group: Any,
    record_id: str,
    source_id: str,
    *,
    coords_override: np.ndarray | None = None,
) -> Frame:
    """Build a Frame ordered by atom-map id and validate HDF5 atom ordering."""
    import molpy as mp

    mapped_isomeric = _read_string(group["mapped_isomeric_smiles"])
    mapped_nonisomeric = _read_string(group["mapped_nonisomeric_smiles"])
    topology = mp.io.read_smiles(mapped_isomeric).to_frame()
    topology_atoms = topology["atoms"]
    if "atom_class" not in topology_atoms:
        raise ValueError(f"THEMol mapped SMILES has no atom-map ids: {record_id}")

    atom_map = np.asarray(topology_atoms["atom_class"], dtype=np.int64)
    order = np.argsort(atom_map, kind="stable")
    expected_map = np.arange(1, len(atom_map) + 1, dtype=np.int64)
    if not np.array_equal(atom_map[order], expected_map):
        raise ValueError(
            f"THEMol atom-map ids for {record_id} are not exactly 1..N: {atom_map.tolist()}"
        )

    elements = np.asarray(topology_atoms["element"], dtype=str)[order]
    formal_charge = (
        np.asarray(topology_atoms["formal_charge"], dtype=np.int64)[order]
        if "formal_charge" in topology_atoms
        else np.zeros(len(elements), dtype=np.int64)
    )
    parsed_numbers = np.asarray(
        [Element.get_atomic_number(symbol) for symbol in elements], dtype=np.int64
    )
    stored_numbers = np.asarray(group["atomic_numbers"], dtype=np.int64).reshape(-1)
    if not np.array_equal(parsed_numbers, stored_numbers):
        raise ValueError(
            f"THEMol mapped-SMILES/HDF5 atomic-number mismatch for {record_id}: "
            f"mapped={parsed_numbers.tolist()}, hdf5={stored_numbers.tolist()}"
        )

    coords = np.asarray(
        group["coords"] if coords_override is None else coords_override,
        dtype=np.float64,
    )
    if coords.shape != (len(stored_numbers), 3):
        raise ValueError(
            f"THEMol coords for {record_id} have shape {coords.shape}, expected "
            f"({len(stored_numbers)}, 3)."
        )

    frame = Frame()
    frame["atoms"] = Block(
        {
            "element": elements,
            "number": stored_numbers,
            "atom_map": expected_map,
            "formal_charge": formal_charge,
            "x": coords[:, 0],
            "y": coords[:, 1],
            "z": coords[:, 2],
        }
    )

    if "bonds" in topology:
        bonds = topology["bonds"]
        parsed_i = np.asarray(bonds["atomi"], dtype=np.int64)
        parsed_j = np.asarray(bonds["atomj"], dtype=np.int64)
        bond_columns: dict[str, np.ndarray] = {
            "atomi": atom_map[parsed_i] - 1,
            "atomj": atom_map[parsed_j] - 1,
        }
        for key in ("bond_number", "bond_type"):
            if key in bonds:
                bond_columns[key] = np.asarray(bonds[key])
        frame["bonds"] = Block(bond_columns)

    molecule_id = uuid.uuid5(uuid.UUID(int=0), mapped_isomeric).hex
    frame.meta.update(
        {
            "molecule_id": molecule_id,
            "source_record_id": record_id,
            "mapped_nonisomeric_smiles": mapped_nonisomeric,
            "mapped_isomeric_smiles": mapped_isomeric,
            "source_id": source_id,
            "total_charge": int(formal_charge.sum()),
        }
    )
    return frame


def _frame_with_energy_forces(
    group: Any,
    molecule_id: str,
    source_id: str,
    *,
    coords: np.ndarray,
    energy: float,
    forces: np.ndarray,
    extra_meta: dict[str, int | float | str],
    topology_frame: Frame | None = None,
) -> Frame:
    frame = (
        topology_frame.copy()
        if topology_frame is not None
        else _mapped_topology_frame(
            group, molecule_id, source_id, coords_override=np.asarray(coords)
        )
    )
    atoms = frame["atoms"]
    coords = np.asarray(coords, dtype=np.float64)
    forces = np.asarray(forces, dtype=np.float64)
    n_atoms = int(np.asarray(atoms["number"]).shape[0])
    if coords.shape != (n_atoms, 3) or forces.shape != (n_atoms, 3):
        raise ValueError(
            f"THEMol E/F shape mismatch for {molecule_id}: "
            f"coords={coords.shape}, forces={forces.shape}, atoms={n_atoms}."
        )
    frame["atoms"] = Block(
        {
            **{key: np.asarray(atoms[key]) for key in atoms.keys()},
            "x": coords[:, 0],
            "y": coords[:, 1],
            "z": coords[:, 2],
            "fx": forces[:, 0],
            "fy": forces[:, 1],
            "fz": forces[:, 2],
        }
    )
    frame.meta.update({"energy": float(energy), **extra_meta})
    return frame


def _read_hessian(handle: Any, key: str, source_id: str) -> HessianRecord:
    group = handle[key]
    frame = _mapped_topology_frame(group, key, source_id)
    hessian = np.asarray(group["hessian"], dtype=np.float64)
    expected = 3 * int(np.asarray(frame["atoms"]["number"]).shape[0])
    if hessian.shape != (expected, expected):
        raise ValueError(
            f"THEMol Hessian for {key} has shape {hessian.shape}, expected "
            f"({expected}, {expected})."
        )
    return HessianRecord(str(frame.meta["molecule_id"]), frame, hessian)


def _numbered_keys(group: Any, prefix: str) -> list[str]:
    keys = [key for key in group.keys() if key.startswith(prefix)]
    return sorted(keys, key=lambda key: int(key.split(" ", 1)[1]))


class _LazyFrameSequence(Sequence[Frame]):
    """Process-safe lazy view over configurations in one HDF5 group."""

    def __init__(
        self,
        path: str | Path,
        *,
        source_id: str,
        record_id: str,
        mode: str,
        specs: tuple[tuple[str, int | None], ...],
        torsion_atom_indices: tuple[int, int, int, int] | None = None,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.source_id = source_id
        self.record_id = record_id
        self.mode = mode
        self.specs = specs
        self.torsion_atom_indices = torsion_atom_indices
        self._pid: int | None = None
        self._handle: Any | None = None
        self._topology_frame: Frame | None = None

    def __len__(self) -> int:
        return len(self.specs)

    @overload
    def __getitem__(self, index: int) -> Frame: ...

    @overload
    def __getitem__(self, index: slice) -> list[Frame]: ...

    def __getitem__(self, index: int | slice) -> Frame | list[Frame]:
        if isinstance(index, slice):
            return [self[item] for item in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)

        child_key, step_index = self.specs[index]
        group = self._h5()[self.record_id]
        child = group[child_key]
        child_index = int(child_key.split(" ", 1)[1])
        if self.mode == "hessian-relax":
            coords = np.asarray(child["coords"], dtype=np.float64)
            energy = float(np.asarray(child["energy"]).reshape(-1)[0])
            forces = np.asarray(child["forces"], dtype=np.float64)
            extra_meta: dict[str, int | float | str] = {"step_index": child_index}
        elif self.mode == "torsion-scan":
            coords = np.asarray(child["coords"], dtype=np.float64)
            energy = float(np.asarray(child["energy"]).reshape(-1)[0])
            forces = np.asarray(child["forces"], dtype=np.float64)
            extra_meta = {
                "scan_id": self.record_id,
                "constraint_index": child_index,
                "torsion_angle": self.angle(index),
            }
        elif self.mode == "torsion-relax" and step_index is not None:
            coords = np.asarray(child["coords"][step_index], dtype=np.float64)
            energy = float(np.asarray(child["energy"][step_index]).reshape(-1)[0])
            forces = np.asarray(child["forces"][step_index], dtype=np.float64)
            extra_meta = {
                "scan_id": self.record_id,
                "constraint_index": child_index,
                "step_index": step_index,
                "torsion_angle": self.angle(index),
            }
        else:  # pragma: no cover - construction validates modes/specs
            raise RuntimeError(f"Invalid THEMol lazy-frame mode {self.mode!r}.")

        return _frame_with_energy_forces(
            group,
            self.record_id,
            self.source_id,
            coords=coords,
            energy=energy,
            forces=forces,
            extra_meta=extra_meta,
            topology_frame=self._topology(group, coords),
        )

    def angle(self, index: int) -> float:
        """Compute one torsion angle without materializing its Frame."""
        if self.torsion_atom_indices is None:
            raise TypeError("This trajectory has no torsion angle.")
        child_key, step_index = self.specs[index]
        child = self._h5()[self.record_id][child_key]
        coords = np.asarray(
            child["coords"] if step_index is None else child["coords"][step_index],
            dtype=np.float64,
        )
        return _dihedral_angle(coords, self.torsion_atom_indices)

    def close(self) -> None:
        """Close this process's HDF5 handle and discard its topology cache."""
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self._pid = None
        self._topology_frame = None

    def __getstate__(self) -> dict[str, Any]:
        state = dict(self.__dict__)
        state["_handle"] = None
        state["_pid"] = None
        state["_topology_frame"] = None
        return state

    def _h5(self) -> Any:
        pid = os.getpid()
        if self._handle is None or self._pid != pid:
            self.close()
            self._handle = _open_h5(self.path)
            self._pid = pid
        return self._handle

    def _topology(self, group: Any, coords: np.ndarray) -> Frame:
        if self._topology_frame is None:
            self._topology_frame = _mapped_topology_frame(
                group,
                self.record_id,
                self.source_id,
                coords_override=coords,
            )
        return self._topology_frame

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class _LazyAngles(Sequence[float]):
    """Angle view sharing the corresponding lazy frame sequence."""

    def __init__(self, frames: _LazyFrameSequence) -> None:
        self.frames = frames

    def __len__(self) -> int:
        return len(self.frames)

    @overload
    def __getitem__(self, index: int) -> float: ...

    @overload
    def __getitem__(self, index: slice) -> list[float]: ...

    def __getitem__(self, index: int | slice) -> float | list[float]:
        if isinstance(index, slice):
            return [self.frames.angle(item) for item in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        return self.frames.angle(index)


def _read_hessian_relax(handle: Any, key: str, source_id: str) -> EnergyForceTrajectory:
    group = handle[key]
    specs = tuple((step_key, None) for step_key in _numbered_keys(group, "step "))
    if not specs:
        raise ValueError(f"THEMol Hessian relaxation {key} contains no steps.")
    frames = _LazyFrameSequence(
        handle.filename,
        source_id=source_id,
        record_id=key,
        mode="hessian-relax",
        specs=specs,
    )
    return EnergyForceTrajectory(_molecule_id(group), frames)


def _dihedral_angle(coords: np.ndarray, indices: tuple[int, int, int, int]) -> float:
    p0, p1, p2, p3 = (coords[index] for index in indices)
    b0 = -(p1 - p0)
    b1 = p2 - p1
    b2 = p3 - p2
    norm = float(np.linalg.norm(b1))
    if norm == 0.0:
        raise ValueError("Cannot compute a torsion angle with a zero central bond.")
    b1 = b1 / norm
    v = b0 - np.dot(b0, b1) * b1
    w = b2 - np.dot(b2, b1) * b1
    return float(np.degrees(np.arctan2(np.dot(np.cross(b1, v), w), np.dot(v, w))))


def _read_torsion(handle: Any, key: str, source_id: str) -> TorsionProfile:
    group = handle[key]
    indices = tuple(int(value) for value in np.asarray(group["torsion_atom_indices"]))
    if len(indices) != 4:
        raise ValueError(f"THEMol torsion {key} does not contain four atom indices.")
    typed_indices = (indices[0], indices[1], indices[2], indices[3])
    specs = tuple((constraint_key, None) for constraint_key in _numbered_keys(group, "constraint "))
    if not specs:
        raise ValueError(f"THEMol torsion {key} contains no constraints.")
    frames = _LazyFrameSequence(
        handle.filename,
        source_id=source_id,
        record_id=key,
        mode="torsion-scan",
        specs=specs,
        torsion_atom_indices=typed_indices,
    )
    return TorsionProfile(
        molecule_id=_molecule_id(group),
        scan_id=key,
        torsion_atom_indices=typed_indices,
        angles=_LazyAngles(frames),
        frames=frames,
    )


def _read_torsion_relax(handle: Any, key: str, source_id: str) -> TorsionProfile:
    group = handle[key]
    indices = tuple(int(value) for value in np.asarray(group["torsion_atom_indices"]))
    if len(indices) != 4:
        raise ValueError(f"THEMol torsion relaxation {key} lacks four atom indices.")
    typed_indices = (indices[0], indices[1], indices[2], indices[3])
    specs: list[tuple[str, int | None]] = []
    optimization_steps = []
    for constraint_key in _numbered_keys(group, "constraint "):
        constraint = group[constraint_key]
        n_coords = int(constraint["coords"].shape[0])
        n_energies = int(constraint["energy"].shape[0])
        n_forces = int(constraint["forces"].shape[0])
        if not (n_coords == n_energies == n_forces):
            raise ValueError(f"THEMol torsion relaxation arrays disagree for {key}.")
        for step_index in range(n_coords):
            optimization_steps.append(step_index)
            specs.append((constraint_key, step_index))
    if not specs:
        raise ValueError(f"THEMol torsion relaxation {key} contains no steps.")
    frames = _LazyFrameSequence(
        handle.filename,
        source_id=source_id,
        record_id=key,
        mode="torsion-relax",
        specs=tuple(specs),
        torsion_atom_indices=typed_indices,
    )
    return TorsionProfile(
        molecule_id=_molecule_id(group),
        scan_id=key,
        torsion_atom_indices=typed_indices,
        angles=_LazyAngles(frames),
        frames=frames,
        optimization_steps=tuple(optimization_steps),
    )


def _read_mbis(handle: Any, key: str, source_id: str) -> MBISRecord:
    group = handle[key]
    frame = _mapped_topology_frame(group, key, source_id)
    info = group["mbis_info"]
    return MBISRecord(
        molecule_id=str(frame.meta["molecule_id"]),
        frame=frame,
        atomic_volumes=np.asarray(info["atomic_volumes"], dtype=np.float64),
        atomic_charge=np.asarray(info["atomic_charge"], dtype=np.float64),
        atomic_dipole=np.asarray(info["atomic_dipole"], dtype=np.float64),
        atomic_quadrupole=np.asarray(info["atomic_quadrupole"], dtype=np.float64),
        parameters=np.asarray(group["parameters"], dtype=np.float64),
    )


class _THEMolDefinition(Generic[RecordT]):
    COORDINATE: str
    _READER: Callable[[Any, str, str], RecordT]

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        hub: ArtifactHub | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve() if root is not None else None
        self._hub = hub

    def load(self, role: str = "shard-000") -> THEMolShardDataset[RecordT]:
        """Fetch or locate one immutable shard and return its lazy collection."""
        if not role.startswith("shard-"):
            raise ValueError(f"THEMol load expects a shard role, got {role!r}.")
        path: Path | None = None
        if self.root is not None:
            candidates = (self.root / role, self.root / f"{role}.h5")
            path = next((candidate for candidate in candidates if candidate.is_file()), None)
            if path is None and self.root.is_file():
                path = self.root
        if path is None:
            hub = self._hub
            if hub is None:
                from molhub.molhub import Molhub

                hub = Molhub()
            path = hub.fetch(self.COORDINATE, roles=[role])[role]
        source_id = f"{self.COORDINATE}#role={role}"
        return THEMolShardDataset(path, source_id=source_id, reader=self._READER)


@dataset(
    name="hessian",
    namespace="themol",
    version="1",
    description="THEMol equilibrium geometries and Cartesian Hessians.",
    license="CC-BY-NC-4.0",
    homepage="https://huggingface.co/datasets/ByteDance-Seed/THEMol",
    citation="10.48550/arXiv.2605.14973",
    tags=("equilibrium", "hessian", "class-i"),
)
class THEMolHessian(_THEMolDefinition[HessianRecord]):
    COORDINATE = "dataset:themol/hessian@1"
    TARGET_SCHEMA = TargetSchema(graph_level=frozenset({"hessian"}), atom_level=frozenset())
    _READER = staticmethod(_read_hessian)


@dataset(
    name="hessian-relax",
    namespace="themol",
    version="1",
    description="THEMol Hessian-derived geometry-optimization trajectories.",
    license="CC-BY-NC-4.0",
    homepage="https://huggingface.co/datasets/ByteDance-Seed/THEMol",
    citation="10.48550/arXiv.2605.14973",
    tags=("off-equilibrium", "energy", "forces", "class-i"),
)
class THEMolHessianRelax(_THEMolDefinition[EnergyForceTrajectory]):
    COORDINATE = "dataset:themol/hessian-relax@1"
    TARGET_SCHEMA = TargetSchema(
        graph_level=frozenset({"energy"}), atom_level=frozenset({"forces"})
    )
    _READER = staticmethod(_read_hessian_relax)


@dataset(
    name="torsion-scan",
    namespace="themol",
    version="1",
    description="THEMol complete constrained torsion profiles.",
    license="CC-BY-NC-4.0",
    homepage="https://huggingface.co/datasets/ByteDance-Seed/THEMol",
    citation="10.48550/arXiv.2605.14973",
    tags=("torsion", "profile", "class-i"),
)
class THEMolTorsionScan(_THEMolDefinition[TorsionProfile]):
    COORDINATE = "dataset:themol/torsion-scan@1"
    TARGET_SCHEMA = TargetSchema(
        graph_level=frozenset({"energy", "torsion_angle"}),
        atom_level=frozenset({"forces"}),
    )
    _READER = staticmethod(_read_torsion)


@dataset(
    name="torsion-relax",
    namespace="themol",
    version="1",
    description="THEMol torsion-constrained optimization trajectories.",
    license="CC-BY-NC-4.0",
    homepage="https://huggingface.co/datasets/ByteDance-Seed/THEMol",
    citation="10.48550/arXiv.2605.14973",
    tags=("off-equilibrium", "torsion", "energy", "forces", "class-i"),
)
class THEMolTorsionRelax(_THEMolDefinition[TorsionProfile]):
    COORDINATE = "dataset:themol/torsion-relax@1"
    TARGET_SCHEMA = THEMolTorsionScan.TARGET_SCHEMA
    _READER = staticmethod(_read_torsion_relax)


@dataset(
    name="mbis",
    namespace="themol",
    version="1",
    description="THEMol MBIS atomic electrostatic supervision.",
    license="CC-BY-NC-4.0",
    homepage="https://huggingface.co/datasets/ByteDance-Seed/THEMol",
    citation="10.48550/arXiv.2605.14973",
    tags=("electrostatics", "mbis", "class-i"),
)
class THEMolMBIS(_THEMolDefinition[MBISRecord]):
    COORDINATE = "dataset:themol/mbis@1"
    TARGET_SCHEMA = TargetSchema(
        graph_level=frozenset(),
        atom_level=frozenset(
            {
                "atomic_charge",
                "atomic_dipole",
                "atomic_quadrupole",
                "atomic_volume",
                "mbis_parameters",
            }
        ),
    )
    _READER = staticmethod(_read_mbis)
