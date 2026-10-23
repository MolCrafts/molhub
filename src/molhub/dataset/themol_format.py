"""THEMol record meaning: arrays in, frames out.

A shard's group has already been read. These functions do not open a file
and do not import HDF5. Column names, units and block shapes are the
published THEMol layout.

Every frame's ``atoms`` block also carries what a Class-I parameter head
conditions on, computed once per record from the mapped SMILES and reordered
by atom-map id like ``formal_charge``: ``ring_connectivity`` (ring bonds at
the atom), ``min_ring_size`` (the smallest SSSR ring through the atom, ``0``
outside any ring) and the GAFF2 Lennard-Jones prior ``gaff2_sigma`` /
``gaff2_epsilon`` of the atom's antechamber type (:data:`GAFF2_UNITS`;
``NaN`` where GAFF2 has no row for the type, never ``0``). The ``bonds``
block carries ``in_ring``. Ring perception and atom typing are molpy's
(:func:`molpy.perceive.perceive_rings`,
:class:`molpy.ff.typifier.AtdTypifier`); the table is
:class:`~molhub.dataset.gaff2.Gaff2LennardJones`.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Sequence
from functools import cache
from typing import Any

import numpy as np
from molpy import Block, Element, Frame

from molhub.dataset.gaff2 import Gaff2LennardJones

__all__ = [
    "GAFF2_UNITS",
    "THEMOL_UNITS",
    "read_hessian",
    "read_hessian_relax",
    "read_mbis",
    "read_torsion",
    "read_torsion_relax",
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
    "torsion_angle": "degree",
}

_SCAN_COLUMNS = ("atomi", "atomj", "atomk", "atoml")
_CARTESIAN_AXES = ("x", "y", "z")
_DIPOLE_COLUMNS = tuple(f"dipole_{axis}" for axis in _CARTESIAN_AXES)
_QUADRUPOLE_COLUMNS = tuple(
    f"quadrupole_{first}{second}" for first in _CARTESIAN_AXES for second in _CARTESIAN_AXES
)
_MBIS_SHELL_BLOCK = "mbis_shells"
_MBIS_ATOM_COLUMNS = (
    "atomic_charge",
    "atomic_volume",
    *_DIPOLE_COLUMNS,
    *_QUADRUPOLE_COLUMNS,
)
_MBIS_UNITS: dict[str, str] = {
    "atomic_charge": THEMOL_UNITS["charge"],
    "atomic_volume": THEMOL_UNITS["volume"],
    **{name: THEMOL_UNITS["dipole"] for name in _DIPOLE_COLUMNS},
    **{name: THEMOL_UNITS["quadrupole"] for name in _QUADRUPOLE_COLUMNS},
}
_ENERGY_FORCE_UNITS: dict[str, str] = {
    "energy": THEMOL_UNITS["energy"],
    "forces": THEMOL_UNITS["forces"],
}
#: Units of the GAFF2 Lennard-Jones prior columns every THEMol frame carries.
GAFF2_UNITS: dict[str, str] = {
    "gaff2_sigma": "angstrom",
    "gaff2_epsilon": "kcal/mol",
}
#: The ``atoms`` columns :func:`_mapped_topology_frame` derives from the SMILES
#: topology beyond identity and geometry, and the ``bonds`` column.
TOPOLOGY_ATOM_COLUMNS: tuple[str, ...] = (
    "formal_charge",
    "ring_connectivity",
    "min_ring_size",
    "gaff2_sigma",
    "gaff2_epsilon",
)
TOPOLOGY_BOND_COLUMNS: tuple[str, ...] = ("in_ring",)

_THREAD_LOCAL = threading.local()


def _gaff2_typifier() -> Any:
    """This thread's GAFF2 :class:`~molpy.ff.typifier.AtdTypifier`.

    Building one parses antechamber's ``ATOMTYPE_GFF2.DEF`` (3.6 s measured
    2026-10-11 on molpy 0.17); typing a molecule is then sub-millisecond, so
    the engine is kept. ``typify`` takes a mutable borrow of the engine, so
    each thread holds its own rather than sharing one behind a lock.
    """
    typifier = getattr(_THREAD_LOCAL, "gaff2_typifier", None)
    if typifier is None:
        import molpy as mp

        typifier = mp.ff.typifier.AtdTypifier(parameter_set="gaff2")
        _THREAD_LOCAL.gaff2_typifier = typifier
    return typifier


@cache
def _gaff2_table() -> Gaff2LennardJones:
    """The shipped GAFF2 Lennard-Jones table, read once per process."""
    return Gaff2LennardJones()


def _read_string(value: Any) -> str:
    """A stored string, whether the snapshot already decoded it."""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.ndarray):
        item = value.reshape(-1)[0]
        return item.decode("utf-8") if isinstance(item, bytes) else str(item)
    raw = value.asstr()[()]
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)


def _mapped_topology_frame(
    group: Any,
    record_id: str,
    source_id: str,
    *,
    coords_override: np.ndarray | None = None,
) -> Frame:
    """Build a Frame ordered by atom-map id and validate HDF5 atom ordering.

    Args:
        group: The record's arrays and strings, already read.
        record_id: The record's group key, for messages and provenance.
        source_id: Provenance string written to ``frame.meta``.
        coords_override: Coordinates to write instead of the group's own
            ``coords`` (a relaxation step's, a constraint's).

    Returns:
        A :class:`~molpy.Frame` whose ``atoms`` block holds ``element``,
        ``number``, ``atom_map``, :data:`TOPOLOGY_ATOM_COLUMNS` and
        ``x``/``y``/``z``, all in atom-map order, and — when the molecule has
        a bond — a ``bonds`` block of ``atomi``/``atomj`` (atom-map order,
        0-based), ``bond_type``, ``bond_number`` and
        :data:`TOPOLOGY_BOND_COLUMNS`.

    Raises:
        ValueError: The mapped SMILES carries no atom-map ids, the ids are not
            exactly ``1..N``, the parsed elements disagree with the stored
            atomic numbers, or the coordinates are not ``(N, 3)``.
    """
    import molpy as mp

    mapped_isomeric = _read_string(group["mapped_isomeric_smiles"])
    mapped_nonisomeric = _read_string(group["mapped_nonisomeric_smiles"])
    molecule = mp.io.read_smiles_str(mapped_isomeric)
    topology = molecule.to_frame()
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
    n_atoms = len(atom_map)

    elements = np.asarray(topology_atoms["element"], dtype=str)[order]
    formal_charge = (
        np.asarray(topology_atoms["formal_charge"], dtype=np.int64)[order]
        if "formal_charge" in topology_atoms
        else np.zeros(n_atoms, dtype=np.int64)
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

    # Bonds in parse order, endpoints as parse rows; remapped to atom-map
    # order below. The row order of ``to_frame`` is the handle order of
    # ``entities``, which is how a ring's atom handles become rows.
    if "bonds" in topology:
        bonds = topology["bonds"]
        parsed_i = np.asarray(bonds["atomi"], dtype=np.int64)
        parsed_j = np.asarray(bonds["atomj"], dtype=np.int64)
    else:
        bonds = None
        parsed_i = parsed_j = np.zeros(0, dtype=np.int64)
    handles = molecule.entities()
    row_of = {handle: row for row, handle in enumerate(handles)}

    rings = mp.perceive.perceive_rings(molecule)
    ring_bonds: set[tuple[int, int]] = set()
    for ring in rings.rings():
        rows = [row_of[handle] for handle in ring]
        for a, b in zip(rows, rows[1:] + rows[:1], strict=True):
            ring_bonds.add((min(a, b), max(a, b)))
    in_ring = np.fromiter(
        ((min(i, j), max(i, j)) in ring_bonds for i, j in zip(parsed_i, parsed_j, strict=True)),
        dtype=np.int64,
        count=len(parsed_i),
    )
    ring_ends = np.concatenate([parsed_i[in_ring == 1], parsed_j[in_ring == 1]])
    ring_connectivity = np.bincount(ring_ends, minlength=n_atoms).astype(np.int64)
    min_ring_size = np.asarray(
        [rings.smallest_ring_containing_atom(handle) or 0 for handle in handles],
        dtype=np.int64,
    )

    # GAFF2 types: antechamber's answer for the SMILES graph, every hydrogen
    # drawn. An atom the table cannot type (a silicon, a noble gas) keeps its
    # element as a label GAFF2 has no row for, so its prior is NaN.
    typed = _gaff2_typifier().typify(molecule)
    gaff2_types = [typed.get(handle, "type") for handle in handles]
    gaff2_sigma, gaff2_epsilon = _gaff2_table().sigma_epsilon(gaff2_types)

    frame = Frame()
    frame["atoms"] = Block(
        {
            "element": elements,
            "number": stored_numbers,
            "atom_map": expected_map,
            "formal_charge": formal_charge,
            "ring_connectivity": ring_connectivity[order],
            "min_ring_size": min_ring_size[order],
            "gaff2_sigma": gaff2_sigma[order],
            "gaff2_epsilon": gaff2_epsilon[order],
            "x": coords[:, 0],
            "y": coords[:, 1],
            "z": coords[:, 2],
        }
    )

    if bonds is not None:
        bond_columns: dict[str, np.ndarray] = {
            "atomi": atom_map[parsed_i] - 1,
            "atomj": atom_map[parsed_j] - 1,
        }
        for key in ("bond_number", "bond_type"):
            if key in bonds:
                bond_columns[key] = np.asarray(bonds[key])
        bond_columns["in_ring"] = in_ring
        frame["bonds"] = Block(bond_columns)

    molecule_id = uuid.uuid5(uuid.UUID(int=0), mapped_isomeric).hex
    frame.meta = {
        "molecule_id": molecule_id,
        "source_record_id": record_id,
        "mapped_nonisomeric_smiles": mapped_nonisomeric,
        "mapped_isomeric_smiles": mapped_isomeric,
        "source_id": source_id,
        "total_charge": int(formal_charge.sum()),
    }
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
    merged = {key: getattr(value, "value", value) for key, value in frame.meta.items()}
    merged.update({"energy": float(energy), **extra_meta})
    frame.meta = merged
    return frame


def _read_hessian(record: Any, key: str, source_id: str) -> Sequence[Frame]:
    """Read one equilibrium record as a Frame carrying a COO ``hessian`` block.

    Args:
        record: The record's arrays and strings, already read.
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
    group = record
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
    return (frame,)


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


def _read_mbis(record: Any, key: str, source_id: str) -> Sequence[Frame]:
    """Read one MBIS record as a Frame: multipoles per atom, shells per shell.

    Args:
        record: The record's arrays and strings, already read.
        key: The record's group key.
        source_id: Provenance string written to ``frame.meta``.

    Returns:
        The geometry :class:`~molpy.Frame` whose ``atoms`` block also carries
        ``atomic_charge``, ``atomic_volume`` (from the source's plural
        ``atomic_volumes``), :data:`_DIPOLE_COLUMNS` and
        :data:`_QUADRUPOLE_COLUMNS`, plus the shell-major
        :data:`_MBIS_SHELL_BLOCK` block — ``atom`` / ``population`` /
        ``inverse_width``, one row per MBIS Slater shell in source row order,
        never regrouped or summed.

    Raises:
        ValueError: A per-atom array's row count is not the atom count, a dipole
            is not ``(N, 3)``, a quadrupole is not ``(N, 3, 3)`` — the component
            names are Cartesian index pairs, so any other shape has no names — or
            the shell table is not ``(S, 3)``, carries a non-integral or
            out-of-range atom index, or leaves an atom with no shell at all.
    """
    group = record
    frame = _mapped_topology_frame(group, key, source_id)
    atoms = frame["atoms"]
    n_atoms = int(np.asarray(atoms["number"]).shape[0])
    info = group["mbis_info"]

    charge = _per_atom(key, "atomic_charge", info["atomic_charge"], n_atoms)
    volume = _per_atom(key, "atomic_volumes", info["atomic_volumes"], n_atoms)
    dipole = _per_atom(key, "atomic_dipole", info["atomic_dipole"], n_atoms)
    quadrupole = _per_atom(key, "atomic_quadrupole", info["atomic_quadrupole"], n_atoms)

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

    shells = np.asarray(group["parameters"], dtype=np.float64)
    if shells.ndim != 2 or shells.shape[1] != 3:
        raise ValueError(
            f"THEMol parameters for {key} have shape {shells.shape}; the MBIS Slater "
            "shell table is (S, 3) — one row per shell, of three columns "
            "(atom index, shell population, inverse Slater width)."
        )
    shell_atom = shells[:, 0]
    fractional = shell_atom[shell_atom != np.trunc(shell_atom)]
    if fractional.size:
        raise ValueError(
            f"THEMol parameters for {key} carry shell atom indices that are not "
            f"integer-valued: {sorted({float(value) for value in fractional})}. Column 0 "
            "addresses an atom, so it is never rounded."
        )
    out_of_range = shell_atom[(shell_atom < 0) | (shell_atom >= n_atoms)]
    if out_of_range.size:
        raise ValueError(
            f"THEMol parameters for {key} carry shell atom indices outside "
            f"[0, {n_atoms}): {sorted({int(value) for value in out_of_range})}. A shell "
            "addressing no atom is a defect, not a row to drop."
        )
    shell_index = shell_atom.astype(np.int64)
    shells_per_atom = np.bincount(shell_index, minlength=n_atoms)
    if not shells_per_atom.all():
        raise ValueError(
            f"THEMol parameters for {key} leave atom(s) "
            f"{np.flatnonzero(shells_per_atom == 0).tolist()} with no shell; every atom "
            "carries at least one MBIS Slater shell, so a missing index is a lost row."
        )

    columns: dict[str, np.ndarray] = {name: np.asarray(atoms[name]) for name in atoms.keys()}
    columns["atomic_charge"] = _scalar_column(key, "atomic_charge", charge)
    columns["atomic_volume"] = _scalar_column(key, "atomic_volumes", volume)
    for index, name in enumerate(_DIPOLE_COLUMNS):
        columns[name] = np.ascontiguousarray(dipole[:, index])
    flat_quadrupole = quadrupole.reshape(n_atoms, len(_QUADRUPOLE_COLUMNS))
    for index, name in enumerate(_QUADRUPOLE_COLUMNS):
        columns[name] = np.ascontiguousarray(flat_quadrupole[:, index])
    frame["atoms"] = Block(columns)
    frame[_MBIS_SHELL_BLOCK] = Block(
        {
            "atom": shell_index.astype(np.int32),
            "population": np.ascontiguousarray(shells[:, 1]),
            "inverse_width": np.ascontiguousarray(shells[:, 2]),
        }
    )
    return (frame,)


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


def _read_hessian_relax(record: Any, key: str, source_id: str) -> Sequence[Frame]:
    """Read one relaxation as a ``Sequence[Frame]`` ordered by per-frame step index.

    Args:
        record: The record's arrays and strings, already read.
        key: The record's group key.
        source_id: Provenance string written to every frame's ``meta``.

    Returns:
        A ``Sequence[Frame]`` of one frame per optimization step,
        each carrying ``energy`` and ``step_index`` in its ``meta`` and its
        forces as ``fx``/``fy``/``fz`` atom columns.

    Raises:
        ValueError: The record has no steps, or a step's geometry disagrees with
            the topology (materializing eagerly means this fails at read, not at
            use).
    """
    group = record
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
    return tuple(frames)


def _read_torsion(record: Any, key: str, source_id: str) -> Sequence[Frame]:
    """Read one complete constrained torsion profile as a ``Sequence[Frame]``.

    Args:
        record: The record's arrays and strings, already read.
        key: The scan's group key, which is also its ``scan_id``.
        source_id: Provenance string written to every frame's ``meta``.

    Returns:
        A ``Sequence[Frame]`` of one frame per constraint, each
        carrying ``energy``, ``torsion_angle``, ``scan_id`` and
        ``constraint_index`` in its ``meta`` and the scanned dihedral in a
        1-row ``scan`` block.

    Raises:
        ValueError: The record does not name four atom indices, contains no
            constraints, or has a geometry whose central bond is zero-length —
            an undefined dihedral is refused, never reported as some default.
    """
    group = record
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
    return tuple(frames)


def _read_torsion_relax(record: Any, key: str, source_id: str) -> Sequence[Frame]:
    """Read one torsion-constrained optimization as a ``Sequence[Frame]``.

    Args:
        record: The record's arrays and strings, already read.
        key: The scan's group key, which is also its ``scan_id``.
        source_id: Provenance string written to every frame's ``meta``.

    Returns:
        A ``Sequence[Frame]`` of one frame per (constraint, step),
        in that order, each carrying ``energy``, ``torsion_angle``,
        ``scan_id``, ``constraint_index`` and ``step_index`` in its ``meta``
        and the scanned dihedral in a 1-row ``scan`` block.

    Raises:
        ValueError: The record does not name four atom indices, a constraint's
            coordinate / energy / force arrays disagree on their step count, the
            record contains no steps, or a geometry's central bond is zero.
    """
    group = record
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
    return tuple(frames)


read_hessian = _read_hessian
read_hessian_relax = _read_hessian_relax
read_mbis = _read_mbis
read_torsion = _read_torsion
read_torsion_relax = _read_torsion_relax
