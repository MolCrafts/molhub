"""Group-preserving adapters for the official THEMol HDF5 shards.

The adapters expose a shard as a map-style collection without flattening a
torsion scan or optimization trajectory into interchangeable frames.  Dataset
definition construction performs no IO; :meth:`load` is the explicit fetch and
index boundary.

**A record IS a molpy object.** One geometry is a :class:`molpy.Frame` — the
Cartesian Hessian is a COO ``hessian`` block, MBIS supervision is per-atom
``atoms`` columns, scalars are ``frame.meta`` entries — and a multi-frame
sampling unit (a relaxation, a torsion profile) is a :class:`molpy.Trajectory`
whose per-frame ``meta`` carries that frame's scalars. There is no wrapper
object on top of ``Frame``; the four record dataclasses that used to be one
were deleted by ``hf-facade-02-frame-records`` (D1), per the 2026-08-15
operator note in ``.claude/notes/notes.md``.

Laziness *between* records — the per-process HDF5 handle in
:class:`THEMolShardDataset` — is what bounds memory and is unchanged. Laziness
*within* one record is deliberately given up (D2): ``molpy.Trajectory``
materializes on construction, and the largest unit (a torsion-relax scan,
≈24 constraints × ≈10 steps × 40 atoms × 3 × 8 B ≈ 230 kB) is three orders
below the block ceiling.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar, overload

import numpy as np
from molpy import Block, Element, Frame, Trajectory

from molhub.dataset.definition import dataset
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.protocol import TargetSchema

__all__ = [
    "THEMOL_UNITS",
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
    # The scanned dihedral a torsion record reports per frame. Added by
    # `hf-facade-03-builder-info` so the `@dataset` unit declarations below can
    # reference this dict for every name they declare, rather than restating a
    # unit literal beside it.
    "torsion_angle": "degree",
}

# The scanned dihedral's four atoms. ``frame.meta`` rejects a len-4 sequence, so
# the index tuple lives in a 1-row valence-style block named ``scan`` — the same
# shape molpy already uses for bonds and angles.
_SCAN_COLUMNS = ("atomi", "atomj", "atomk", "atoml")

# The Cartesian axes the per-atom MBIS tensors are named by. A dipole is one
# column per axis; a quadrupole is one column per *ordered* index pair, in
# row-major order — ``quadrupole_yx`` is a column of its own, not a synonym for
# ``quadrupole_xy``. Unfolding the lower triangle applies D1's Hessian
# reasoning ("a discarded lower triangle is a convention every reader must then
# remember") to the rank-2 per-atom tensor: the column count follows the source
# shape and assumes no symmetry of the data.
_CARTESIAN_AXES = ("x", "y", "z")
_DIPOLE_COLUMNS = tuple(f"dipole_{axis}" for axis in _CARTESIAN_AXES)
_QUADRUPOLE_COLUMNS = tuple(
    f"quadrupole_{first}{second}" for first in _CARTESIAN_AXES for second in _CARTESIAN_AXES
)

# The per-atom Slater parameters arrive as one unnamed ``(N, arity)`` array, so
# their columns are numbered by slot. The arity is a property of the shard, read
# off that shape at load time — never assumed, and never declared statically
# (see :class:`THEMolMBIS`).
_PARAMETER_PREFIX = "mbis_parameter_"

# The MBIS ``atoms`` columns whose names the format fixes, and therefore the
# whole of what :attr:`THEMolMBIS.TARGET_SCHEMA` can honestly declare.
_MBIS_ATOM_COLUMNS = (
    "atomic_charge",
    "atomic_volume",
    *_DIPOLE_COLUMNS,
    *_QUADRUPOLE_COLUMNS,
)

# What each of those columns is measured in, keyed by the column name a reader
# actually finds on the frame and valued out of :data:`THEMOL_UNITS`. Derived
# from the column tuples above rather than written out, so a component name and
# its unit cannot drift apart, and quoting no literal here keeps THEMOL_UNITS
# the single place a THEMol unit string is spelled.
# The `mbis_parameter_<slot>` columns are deliberately absent: their arity is
# the shard's, read at load time (see :class:`THEMolMBIS`), so a static
# declaration would have to invent one.
_MBIS_UNITS: dict[str, str] = {
    "atomic_charge": THEMOL_UNITS["charge"],
    "atomic_volume": THEMOL_UNITS["volume"],
    **{name: THEMOL_UNITS["dipole"] for name in _DIPOLE_COLUMNS},
    **{name: THEMOL_UNITS["quadrupole"] for name in _QUADRUPOLE_COLUMNS},
}

# The energy/force pair every off-equilibrium THEMol adapter declares.
_ENERGY_FORCE_UNITS: dict[str, str] = {
    "energy": THEMOL_UNITS["energy"],
    "forces": THEMOL_UNITS["forces"],
}

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

    def keys(self) -> tuple[str, ...]:
        """The shard's HDF5 group keys, in the order the file lists them.

        Indexed once at construction, so this costs no read. It is public
        because a record's key is the only thing that joins a shard to a split
        table keyed by record uuid, and a caller that had to reach for
        ``_keys`` would be depending on the same fact less honestly.

        Returns:
            One key per record, positionally aligned with ``self[i]``.
        """
        return self._keys

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


def _read_hessian(handle: Any, key: str, source_id: str) -> Frame:
    """Read one equilibrium record as a Frame carrying a COO ``hessian`` block.

    Args:
        handle: Open HDF5 file of the shard.
        key: The record's group key.
        source_id: Provenance string written to ``frame.meta``.

    Returns:
        The topology/geometry :class:`~molpy.Frame` plus a ``hessian`` block of
        ``row``/``col``/``value`` holding **all** ``(3N)**2`` entries in
        row-major order — no triangle folding and no sparsity assumption, so a
        consumer may ``value.reshape(3N, 3N)`` directly (D1).

    Raises:
        ValueError: The stored Hessian is not ``(3N, 3N)``.
    """
    group = handle[key]
    frame = _mapped_topology_frame(group, key, source_id)
    hessian = np.asarray(group["hessian"], dtype=np.float64)
    expected = 3 * int(np.asarray(frame["atoms"]["number"]).shape[0])
    if hessian.shape != (expected, expected):
        raise ValueError(
            f"THEMol Hessian for {key} has shape {hessian.shape}, expected "
            f"({expected}, {expected})."
        )
    row, col = np.divmod(np.arange(expected * expected, dtype=np.int64), expected)
    frame["hessian"] = Block(
        {
            "row": row.astype(np.int32),
            "col": col.astype(np.int32),
            "value": hessian.reshape(-1),
        }
    )
    return frame


def _per_atom(key: str, name: str, values: Any, n_atoms: int) -> np.ndarray:
    """One MBIS array as float64, refusing a row count that is not the atom count.

    Args:
        key: The record's group key, for the message.
        name: The source array's HDF5 name, so the message names the defect.
        values: The HDF5 dataset or array to read.
        n_atoms: Atoms the record's topology declares.

    Returns:
        The array as ``float64``, first axis unchanged.

    Raises:
        ValueError: The array's row count is not *n_atoms*. MBIS supervision is
            per atom; broadcasting a shorter array would invent supervision for
            the atoms it does not cover.
    """
    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 0 or array.shape[0] != n_atoms:
        raise ValueError(
            f"THEMol {name} for {key} has shape {array.shape}, expected {n_atoms} rows — "
            "one per atom. A per-atom target is never broadcast."
        )
    return array


def _scalar_column(key: str, name: str, array: np.ndarray) -> np.ndarray:
    """One ``(N,)`` atom column from a ``(N,)`` or ``(N, 1)`` source array."""
    if array.ndim == 1:
        return array
    if array.ndim == 2 and array.shape[1] == 1:
        return np.ascontiguousarray(array[:, 0])
    raise ValueError(
        f"THEMol {name} for {key} has shape {array.shape}; a per-atom scalar is (N,) or (N, 1)."
    )


def _read_mbis(handle: Any, key: str, source_id: str) -> Frame:
    """Read one MBIS record as a Frame whose supervision is ``atoms`` columns.

    Args:
        handle: Open HDF5 file of the shard.
        key: The record's group key.
        source_id: Provenance string written to ``frame.meta``.

    Returns:
        The geometry :class:`~molpy.Frame` whose ``atoms`` block also carries
        ``atomic_charge``, ``atomic_volume`` (from the source's plural
        ``atomic_volumes``), :data:`_DIPOLE_COLUMNS`, :data:`_QUADRUPOLE_COLUMNS`
        and one ``mbis_parameter_<slot>`` column per Slater parameter slot.

    Raises:
        ValueError: An array's row count is not the atom count, a dipole is not
            ``(N, 3)``, a quadrupole is not ``(N, 3, 3)`` — the component names
            are Cartesian index pairs, so any other shape has no names — or the
            parameters are not a two-dimensional ``(N, arity)`` array.
    """
    group = handle[key]
    frame = _mapped_topology_frame(group, key, source_id)
    atoms = frame["atoms"]
    n_atoms = int(np.asarray(atoms["number"]).shape[0])
    info = group["mbis_info"]

    charge = _per_atom(key, "atomic_charge", info["atomic_charge"], n_atoms)
    volume = _per_atom(key, "atomic_volumes", info["atomic_volumes"], n_atoms)
    dipole = _per_atom(key, "atomic_dipole", info["atomic_dipole"], n_atoms)
    quadrupole = _per_atom(key, "atomic_quadrupole", info["atomic_quadrupole"], n_atoms)
    parameters = _per_atom(key, "parameters", group["parameters"], n_atoms)

    if dipole.shape != (n_atoms, 3):
        raise ValueError(
            f"THEMol atomic_dipole for {key} has shape {dipole.shape}, expected "
            f"({n_atoms}, 3); its columns are named by Cartesian axis."
        )
    if quadrupole.shape != (n_atoms, 3, 3):
        raise ValueError(
            f"THEMol atomic_quadrupole for {key} has shape {quadrupole.shape}, expected "
            f"({n_atoms}, 3, 3); its columns are named by Cartesian index pair."
        )
    if parameters.ndim != 2:
        raise ValueError(
            f"THEMol parameters for {key} have shape {parameters.shape}; the per-atom "
            "Slater parameters are read as (N, arity) and their arity is the shard's."
        )

    columns: dict[str, np.ndarray] = {name: np.asarray(atoms[name]) for name in atoms.keys()}
    columns["atomic_charge"] = _scalar_column(key, "atomic_charge", charge)
    columns["atomic_volume"] = _scalar_column(key, "atomic_volumes", volume)
    for index, name in enumerate(_DIPOLE_COLUMNS):
        columns[name] = np.ascontiguousarray(dipole[:, index])
    flat_quadrupole = quadrupole.reshape(n_atoms, len(_QUADRUPOLE_COLUMNS))
    for index, name in enumerate(_QUADRUPOLE_COLUMNS):
        columns[name] = np.ascontiguousarray(flat_quadrupole[:, index])
    for slot in range(parameters.shape[1]):
        columns[f"{_PARAMETER_PREFIX}{slot}"] = np.ascontiguousarray(parameters[:, slot])
    frame["atoms"] = Block(columns)
    return frame


def _numbered_keys(group: Any, prefix: str) -> list[str]:
    keys = [key for key in group.keys() if key.startswith(prefix)]
    return sorted(keys, key=lambda key: int(key.split(" ", 1)[1]))


def _dihedral_angle(coords: np.ndarray, indices: tuple[int, int, int, int]) -> float:
    """The dihedral about *indices*, in degrees, from one geometry."""
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


def _torsion_atom_indices(group: Any, key: str) -> tuple[int, int, int, int]:
    """The four scanned atom indices of a torsion record."""
    indices = tuple(int(value) for value in np.asarray(group["torsion_atom_indices"]).reshape(-1))
    if len(indices) != 4:
        raise ValueError(f"THEMol torsion {key} does not contain four atom indices.")
    return (indices[0], indices[1], indices[2], indices[3])


def _scan_block(indices: tuple[int, int, int, int]) -> Block:
    """The scanned dihedral as the 1-row block ``frame.meta`` cannot hold."""
    return Block(
        {
            name: np.asarray([index], dtype=np.int32)
            for name, index in zip(_SCAN_COLUMNS, indices, strict=True)
        }
    )


def _read_hessian_relax(handle: Any, key: str, source_id: str) -> Trajectory:
    """Read one relaxation as a Trajectory ordered by its per-frame step index.

    Args:
        handle: Open HDF5 file of the shard.
        key: The record's group key.
        source_id: Provenance string written to every frame's ``meta``.

    Returns:
        A :class:`~molpy.Trajectory` of one frame per optimization step, each
        carrying ``energy`` and ``step_index`` in its ``meta`` and its forces as
        ``fx``/``fy``/``fz`` atom columns.

    Raises:
        ValueError: The record has no steps, or a step's geometry disagrees with
            the topology (materializing eagerly means this fails at read, not at
            use).
    """
    group = handle[key]
    step_keys = _numbered_keys(group, "step ")
    if not step_keys:
        raise ValueError(f"THEMol Hessian relaxation {key} contains no steps.")
    topology: Frame | None = None
    frames: list[Frame] = []
    for step_key in step_keys:
        child = group[step_key]
        coords = np.asarray(child["coords"], dtype=np.float64)
        if topology is None:
            topology = _mapped_topology_frame(group, key, source_id, coords_override=coords)
        frames.append(
            _frame_with_energy_forces(
                group,
                key,
                source_id,
                coords=coords,
                energy=float(np.asarray(child["energy"]).reshape(-1)[0]),
                forces=np.asarray(child["forces"], dtype=np.float64),
                extra_meta={"step_index": int(step_key.split(" ", 1)[1])},
                topology_frame=topology,
            )
        )
    return Trajectory(frames)


def _read_torsion(handle: Any, key: str, source_id: str) -> Trajectory:
    """Read one complete constrained torsion profile as a Trajectory.

    Args:
        handle: Open HDF5 file of the shard.
        key: The scan's group key, which is also its ``scan_id``.
        source_id: Provenance string written to every frame's ``meta``.

    Returns:
        A :class:`~molpy.Trajectory` of one frame per constraint, each carrying
        ``energy``, ``torsion_angle``, ``scan_id`` and ``constraint_index`` in
        its ``meta`` and the scanned dihedral in a 1-row ``scan`` block.

    Raises:
        ValueError: The record does not name four atom indices, contains no
            constraints, or has a geometry whose central bond is zero-length —
            an undefined dihedral is refused, never reported as some default.
    """
    group = handle[key]
    indices = _torsion_atom_indices(group, key)
    constraint_keys = _numbered_keys(group, "constraint ")
    if not constraint_keys:
        raise ValueError(f"THEMol torsion {key} contains no constraints.")
    topology: Frame | None = None
    frames: list[Frame] = []
    for constraint_key in constraint_keys:
        child = group[constraint_key]
        coords = np.asarray(child["coords"], dtype=np.float64)
        if topology is None:
            topology = _mapped_topology_frame(group, key, source_id, coords_override=coords)
        frame = _frame_with_energy_forces(
            group,
            key,
            source_id,
            coords=coords,
            energy=float(np.asarray(child["energy"]).reshape(-1)[0]),
            forces=np.asarray(child["forces"], dtype=np.float64),
            extra_meta={
                "scan_id": key,
                "constraint_index": int(constraint_key.split(" ", 1)[1]),
                "torsion_angle": _dihedral_angle(coords, indices),
            },
            topology_frame=topology,
        )
        frame["scan"] = _scan_block(indices)
        frames.append(frame)
    return Trajectory(frames)


def _read_torsion_relax(handle: Any, key: str, source_id: str) -> Trajectory:
    """Read one torsion-constrained optimization as a Trajectory.

    Args:
        handle: Open HDF5 file of the shard.
        key: The scan's group key, which is also its ``scan_id``.
        source_id: Provenance string written to every frame's ``meta``.

    Returns:
        A :class:`~molpy.Trajectory` of one frame per (constraint, step), in
        that order, each carrying ``energy``, ``torsion_angle``, ``scan_id``,
        ``constraint_index`` and ``step_index`` in its ``meta`` and the scanned
        dihedral in a 1-row ``scan`` block.

    Raises:
        ValueError: The record does not name four atom indices, a constraint's
            coordinate / energy / force arrays disagree on their step count, the
            record contains no steps, or a geometry's central bond is zero.
    """
    group = handle[key]
    indices = _torsion_atom_indices(group, key)
    topology: Frame | None = None
    frames: list[Frame] = []
    for constraint_key in _numbered_keys(group, "constraint "):
        child = group[constraint_key]
        n_coords = int(child["coords"].shape[0])
        n_energies = int(child["energy"].shape[0])
        n_forces = int(child["forces"].shape[0])
        if not (n_coords == n_energies == n_forces):
            raise ValueError(f"THEMol torsion relaxation arrays disagree for {key}.")
        constraint_index = int(constraint_key.split(" ", 1)[1])
        for step_index in range(n_coords):
            coords = np.asarray(child["coords"][step_index], dtype=np.float64)
            if topology is None:
                topology = _mapped_topology_frame(group, key, source_id, coords_override=coords)
            frame = _frame_with_energy_forces(
                group,
                key,
                source_id,
                coords=coords,
                energy=float(np.asarray(child["energy"][step_index]).reshape(-1)[0]),
                forces=np.asarray(child["forces"][step_index], dtype=np.float64),
                extra_meta={
                    "scan_id": key,
                    "constraint_index": constraint_index,
                    "step_index": step_index,
                    "torsion_angle": _dihedral_angle(coords, indices),
                },
                topology_frame=topology,
            )
            frame["scan"] = _scan_block(indices)
            frames.append(frame)
    if not frames:
        raise ValueError(f"THEMol torsion relaxation {key} contains no steps.")
    return Trajectory(frames)


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
    units={"hessian": THEMOL_UNITS["hessian"]},
    blocks=("hessian",),
)
class THEMolHessian(_THEMolDefinition[Frame]):
    """THEMol equilibrium geometries; one record is one :class:`~molpy.Frame`.

    The Cartesian Hessian is the frame's ``hessian`` block —
    ``row``/``col``/``value``, all ``(3N)**2`` entries in row-major order — not
    a ``frame.meta`` scalar. ``TARGET_SCHEMA`` still names it ``graph_level``
    because :class:`~molhub.dataset.protocol.TargetSchema` has only the two
    layout sets; the ``blocks`` declaration that would say "block, not meta" is
    ``hf-facade-03-builder-info``'s.
    """

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
    units=_ENERGY_FORCE_UNITS,
)
class THEMolHessianRelax(_THEMolDefinition[Trajectory]):
    """THEMol relaxations; one record is one :class:`~molpy.Trajectory`.

    Per-frame ``meta`` carries ``energy`` and ``step_index`` — the latter is
    where the deleted ``optimization_steps`` tuple went.
    """

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
    units={**_ENERGY_FORCE_UNITS, "torsion_angle": THEMOL_UNITS["torsion_angle"]},
)
class THEMolTorsionScan(_THEMolDefinition[Trajectory]):
    """THEMol torsion profiles; one whole scan is one :class:`~molpy.Trajectory`.

    Per-frame ``meta`` carries ``energy``, ``torsion_angle``, ``scan_id`` and
    ``constraint_index``; the scanned dihedral is the 1-row ``scan`` block
    (``atomi``/``atomj``/``atomk``/``atoml``), identical on every frame.
    """

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
    units={**_ENERGY_FORCE_UNITS, "torsion_angle": THEMOL_UNITS["torsion_angle"]},
)
class THEMolTorsionRelax(_THEMolDefinition[Trajectory]):
    """THEMol torsion-constrained optimizations, one scan per record.

    Same shape as :class:`THEMolTorsionScan`, plus a per-frame
    ``meta["step_index"]``; frames run constraint-major, step-minor.
    """

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
    units=_MBIS_UNITS,
)
class THEMolMBIS(_THEMolDefinition[Frame]):
    """THEMol MBIS supervision; one record is one :class:`~molpy.Frame`.

    Every target is an ``atoms`` column, so ``TARGET_SCHEMA.atom_level`` names
    the columns a reader will actually find on the frame:
    :data:`_MBIS_ATOM_COLUMNS` — ``atomic_charge``, ``atomic_volume``, the three
    ``dipole_<axis>`` components and the nine ``quadrupole_<axis><axis>``
    components. The grouped names it declared before dissolution
    (``atomic_dipole`` / ``atomic_quadrupole`` / ``mbis_parameters``) match no
    column of any sample, so they are gone.

    **The Slater-parameter columns are deliberately not declared.** They are
    ``mbis_parameter_<slot>`` for ``slot < arity``, and the arity is read off
    the shard's ``(N, arity)`` array at load time (D1: "the parameter arity is
    read from the source array shapes"). A class attribute is built without IO,
    so declaring them would mean inventing an arity the format does not fix —
    which is the one thing this schema exists not to do. Their existence is
    documented here and pinned by ``tests/test_dataset/test_themol.py``.
    """

    COORDINATE = "dataset:themol/mbis@1"
    TARGET_SCHEMA = TargetSchema(
        graph_level=frozenset(),
        atom_level=frozenset(_MBIS_ATOM_COLUMNS),
    )
    _READER = staticmethod(_read_mbis)
