"""THEMol records to numpy sampling units — one record in, one whole unit out.

This is the semantic half of the prepare stage: it maps the records
:mod:`molhub.dataset.themol` already parses out of HDF5 — a
:data:`~molpy.FrameCollection` (``Sequence[Frame]``) — onto the column names
``molix.block/1`` routes, and does nothing else. It opens no file, holds no
writer, decides no split, and imports neither torch nor molix — so a shard
can be encoded, inspected and unit-tested in an environment where molnex is
not installed at all.

**A record is recognised by shape, not by name.**
``tests/test_conveyor/test_layering.py`` allows this module stdlib, ``molhub``
and ``numpy`` and nothing else — ``molpy`` is on its forbidden list at *any*
depth — so :meth:`THEMolUnitEncoder.encode` cannot name ``Frame`` or
``FrameCollection`` in an ``isinstance`` check. It requires a sequence whose
first item has ``meta``. A bare frame is not a collection.

**Column names are molnex's route names, not molhub's.** They are rows of the
closed ``_COLUMN_ROUTES`` registry in ``molnex:src/molix/store/block.py``, which
resolves a column to a row space and a payload route by *name* — an
unregistered column is a ``ValueError``, not a new prefix — so the encoder emits
exactly: ``Z`` / ``bond_atomi`` / ``bond_atomj`` / ``bond_type`` /
``torsion_atoms`` in molecule space, and ``pos`` / ``forces`` / ``energy`` /
``torsion_angle`` in frame space.

**No unit conversion happens here, by construction.**
:data:`~molhub.dataset.themol.THEMOL_UNITS` declares Å / kcal mol⁻¹ /
kcal mol⁻¹ Å⁻¹, which is already the block format's convention. The only numeric
transformation is the dtype narrowing the store refuses to do silently
(float64 → ``<f4``, molpy's uint32 valence columns → ``<i4``, atomic numbers →
``<i2``); no conversion factor appears anywhere in this module, and the caller
puts ``THEMOL_UNITS`` itself into ``provenance["units"]``.

**Named gap — the Cartesian Hessian is not encoded.** A hessian record yields a
one-frame equilibrium-geometry unit, and the ``hessian`` block its frame carries
— all ``(3N)**2`` COO entries — is deliberately dropped, for two independent
reasons:

1. ``molix.block/1`` has no routable column space for a per-molecule ragged 2-D
   payload. Its only Hessian column is ``hessian_diag``, a *projected internal*
   target, and the projection needs a B-matrix that is equally unroutable — so
   storing the Cartesian block would mean forking the block format, which is the
   one thing this boundary exists to prevent.
2. The streaming strategy classifies the Hessian core as **hot tier**
   (``.claude/specs/streaming-data-tiers-01-strategy.md`` § 6), permanently
   resident at ≈ 5.8 GB. It does not belong in a rolling block at all.

The successor owns the projected-target column: the chain's ``-04`` sub-spec, or
a dedicated Hessian-target spec if the projection lands first. Until then
``TestTHEMolUnitEncoder`` pins the hessian unit's column set, so the omission
cannot decay from a decision into an accident.

Also not encoded: a frame's ``meta["step_index"]``. It labels which optimizer
iteration a torsion-relax or relaxation frame came from, which is provenance
about the *generation* of a frame rather than a supervision target, and
``molix.block/1`` has no frame-space route for it.

Reference:
    ``.claude/specs/streaming-data-tiers-03-conveyor-03-prepare.md`` § 3
    *Encoder*.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from molhub.conveyor.errors import IncompleteRecordError, UnsupportedRecordError

__all__ = ["RawUnit", "THEMolUnitEncoder"]

# The two columns every block declares, and the names this module derives its
# counts from. Mirrored from `molnex:src/molix/store/block.py`'s required pair,
# name for name.
_REQUIRED_TOPOLOGY = "Z"
_REQUIRED_FRAME = "pos"

# molpy's atom-block spelling of the two vectors a frame can carry.
_POSITION_COLUMNS = ("x", "y", "z")
_FORCE_COLUMNS = ("fx", "fy", "fz")

# Integer bond order, in the order the THEMol reader may have written it
# (`molhub/dataset/themol.py:262`): `bond_number` first, `bond_type` as the
# fallback. There is no third candidate and no default.
_BOND_ORDER_COLUMNS = ("bond_number", "bond_type")

# The three columns a bond family declares — together, always, even when empty.
_BOND_COLUMNS = ("bond_atomi", "bond_atomj", "bond_type")

# The 1-row block a scanned dihedral lives in, and its four columns, exactly as
# `molhub.dataset.themol` writes them. A record carrying this block on its first
# frame is a torsion scan; one without it is not, whatever its task is called.
_SCAN_BLOCK = "scan"
_SCAN_COLUMNS = ("atomi", "atomj", "atomk", "atoml")

# The one subset whose targets have no column routes at all. It is refused where
# the task is named — at construction — because after the record dataclasses were
# dissolved an MBIS frame and a hessian frame are the same type, so a per-record
# refusal would be both later (a writer is already open) and weaker.
_UNROUTABLE_TASK = "mbis"


@dataclass(frozen=True, eq=False)
class RawUnit:
    """One whole sampling unit as numpy columns, before any torch exists.

    The value the prepare stage routes, counts and hands to a writer. It is the
    torch-free mirror of molnex's ``SamplingUnit`` plus one field molnex has no
    room for — :attr:`identity`, the split key, which is dropped again at the
    writer boundary once routing has used it.

    Frozen, with both mappings wrapped in :class:`types.MappingProxyType`: a
    unit that could be edited after routing could be edited after routing.
    Equality is identity (``eq=False``, as molnex's ``SamplingUnit``): array
    payloads make value equality ill-defined.

    Attributes:
        key: Unit identity — ``molecule_id`` for a bundle, ``scan_id`` for a
            scan. This is what a sealed block records.
        identity: blake2b-128 hex of ``mapped_isomeric_smiles``, the *molecule*
            level key the split table is keyed by. A scan id is not a molecular
            identity, and keying a split on one silently straddles splits.
        task: The THEMol subset label (``hessian``, ``hessian-relax``,
            ``torsion-scan``, ``torsion-relax``) — one per shard, one per block.
        topology: Molecule-space columns, ``{name: np.ndarray}``.
        frames: Frame-space columns, ``{name: np.ndarray}``.
    """

    key: str
    identity: str
    task: str
    topology: Mapping[str, np.ndarray]
    frames: Mapping[str, np.ndarray]

    def __post_init__(self) -> None:
        object.__setattr__(self, "topology", MappingProxyType(dict(self.topology)))
        object.__setattr__(self, "frames", MappingProxyType(dict(self.frames)))

    @property
    def n_atoms(self) -> int:
        """Atoms in this unit's topology, ``N = len(Z)``."""
        return int(self.topology[_REQUIRED_TOPOLOGY].shape[0])

    @property
    def n_frames(self) -> int:
        """Frames of this unit, ``len(pos) // n_atoms``.

        Exact by construction: :meth:`THEMolUnitEncoder.encode` refuses a record
        whose frames disagree with its topology's atom count.
        """
        return int(self.frames[_REQUIRED_FRAME].shape[0]) // self.n_atoms


class THEMolUnitEncoder:
    """Encodes one THEMol shard's records as :class:`RawUnit`s.

    One shard is one subset is one task label, so the encoder is constructed per
    shard and stamps every unit it produces with the same *task*. That is what
    lets molnex freeze a block's schema from its first unit without any
    negotiation: every unit of a job declares the same column set.

    ``encode`` is the single public verb. There is deliberately no frame-level
    method: a torsion scan and a relaxation trajectory are sampling units, and
    an encoder that could emit half of one would make block-level unit
    integrality (I2) a matter of discipline rather than of shape.

    Args:
        task: The THEMol subset label stored on every unit, e.g.
            ``"torsion-scan"``.

    Raises:
        ValueError: *task* is empty; molnex stores it as a dictionary code and
            refuses an empty label.
        UnsupportedRecordError: *task* is ``"mbis"``, whose atom-level
            electrostatics targets need column routes ``molix.block/1`` does not
            define.
    """

    def __init__(self, *, task: str) -> None:
        if not task:
            raise ValueError(
                "THEMolUnitEncoder(task=...) needs a non-empty subset label; it is stored "
                "in every unit's task dictionary code and one shard carries exactly one."
            )
        if task == _UNROUTABLE_TASK:
            raise UnsupportedRecordError(
                "THEMol 'mbis' has no encoder: its atom-level electrostatics targets "
                "(atomic_charge, atomic_volume, the dipole and quadrupole components and "
                "the per-atom Slater parameters) need column routes molix.block/1 does not "
                "define. Encoding the geometry alone would produce a unit that silently lost "
                "every target it exists for. The refusal is here, at construction, because an "
                "MBIS frame and a hessian frame are the same type: one shard is one task, and "
                "the task is named here."
            )
        self._task = task

    @staticmethod
    def identity(mapped_isomeric_smiles: str) -> str:
        """Return the molecular identity of *mapped_isomeric_smiles*.

        blake2b-128 hex — the **one** implementation of the rule that produced
        the shipped ``class1-universal-splits@1`` tables, which
        ``scripts/build_class1_splits.py`` now imports rather than redefining.
        Split *production* and split *routing* drifting apart would mis-route
        molecules with nothing able to detect it, so there is one function and
        the tests pin its output as literals.

        THEMol's ``mapped_isomeric_smiles`` strings are byte-identical for the
        same molecule across the hessian / torsion-scan / mbis subsets, which is
        what makes them usable as a cross-subset molecular identity. The torsion
        ``uuid`` is a **scan** identity with zero overlap with hessian/mbis
        uuids — never key a split on it.

        Args:
            mapped_isomeric_smiles: The atom-mapped isomeric SMILES exactly as
                THEMol stores it; no normalisation, canonicalisation or
                stripping happens here, because any of them would change the
                digest and orphan the shipped tables.

        Returns:
            32 hex characters (128 bits).
        """
        return hashlib.blake2b(mapped_isomeric_smiles.encode(), digest_size=16).hexdigest()

    def encode(self, record: Any) -> RawUnit:
        """Encode one whole THEMol record as one whole :class:`RawUnit`.

        Args:
            record: A :data:`~molpy.FrameCollection` — ``Sequence[Frame]`` —
                exactly what ``THEMolShardDataset.__getitem__`` returns.

        Returns:
            The unit, with molecule-space and frame-space columns named as
            ``molix.block/1`` routes them.

        Raises:
            UnsupportedRecordError: *record* is not a sequence of frames.
            IncompleteRecordError: *record* carries bonds without an integer
                order, frames that disagree with its topology, a frame missing a
                target its siblings declare, or no ``mapped_isomeric_smiles``.
        """
        if isinstance(record, Sequence) and not isinstance(record, (str, bytes)):
            frames = tuple(record)
            if frames and hasattr(frames[0], "meta"):
                return self._unit(frames)
        raise UnsupportedRecordError(
            f"{type(record).__name__} is not a FrameCollection; encode() takes "
            "Sequence[Frame], which is what THEMolShardDataset.__getitem__ returns."
        )

    # -- one record --------------------------------------------------------

    def _unit(self, frames: Sequence[Any]) -> RawUnit:
        """Encode one record's frames into one unit, reading each frame once.

        The first frame decides everything about the unit — its key, its
        topology, its molecular identity, whether it carries forces and
        energies, and whether it is a torsion scan (the ``scan`` block) — and
        every later frame must agree with it. Frames are consumed in order and
        never held together.
        """
        if not frames:
            raise IncompleteRecordError(
                "a THEMol record carries no frames; a sampling unit is one topology plus at "
                "least one frame of it, and molnex refuses a unit without one."
            )
        torsion = self._scanned_dihedral(frames[0])
        key = self._key(frames[0], scanned=torsion is not None)

        topology: dict[str, np.ndarray] = {}
        identity = ""
        n_atoms = 0
        with_forces = False
        with_energy = False
        positions: list[np.ndarray] = []
        forces: list[np.ndarray] = []
        energies: list[float] = []
        angles: list[float] = []

        for index, frame in enumerate(frames):
            atoms = frame["atoms"]
            targets = frame.meta
            if index == 0:
                topology = self._topology(key, frame)
                identity = self.identity(self._smiles(key, targets))
                n_atoms = int(topology[_REQUIRED_TOPOLOGY].shape[0])
                with_forces = _FORCE_COLUMNS[0] in atoms
                with_energy = "energy" in targets

            coordinates = self._vectors(key, atoms, _POSITION_COLUMNS)
            if coordinates.shape[0] != n_atoms:
                raise IncompleteRecordError(
                    f"frame {index} of THEMol record {key!r} has {coordinates.shape[0]} atoms "
                    f"but its topology declares {n_atoms}. A block stores frame columns with "
                    "a k * N stride, so a ragged unit cannot be laid out at all — the record "
                    "is what has to be fixed, not the stride."
                )
            positions.append(coordinates)
            if with_forces:
                forces.append(self._vectors(key, atoms, _FORCE_COLUMNS))
            if with_energy:
                energies.append(self._target(key, targets, "energy", index))
            if torsion is not None:
                angles.append(self._target(key, targets, "torsion_angle", index))

        frame_columns: dict[str, np.ndarray] = {_REQUIRED_FRAME: _stack(positions)}
        if with_forces:
            frame_columns["forces"] = _stack(forces)
        if with_energy:
            frame_columns["energy"] = np.asarray(energies, dtype=np.float32)
        if torsion is not None:
            topology["torsion_atoms"] = self._torsion_atoms(key, torsion, n_atoms)
            frame_columns["torsion_angle"] = np.asarray(angles, dtype=np.float32)

        return RawUnit(
            key=key,
            identity=identity,
            task=self._task,
            topology=topology,
            frames=frame_columns,
        )

    # -- one frame ---------------------------------------------------------

    @staticmethod
    def _scanned_dihedral(frame: Any) -> tuple[int, int, int, int] | None:
        """The four scanned atoms of *frame*, or ``None`` when it is not a scan.

        The ``scan`` block, not the task label, is what makes a unit a scan, and
        it is read off the record's **first** frame only: every frame of a THEMol
        scan carries it identically (pinned by
        ``tests/test_dataset/test_themol.py``), and the first frame is what
        freezes the rest of the unit's schema anyway.
        """
        if _SCAN_BLOCK not in frame:
            return None
        block = frame[_SCAN_BLOCK]
        missing = [name for name in _SCAN_COLUMNS if name not in block]
        if missing:
            raise IncompleteRecordError(
                f"THEMol record carries a {_SCAN_BLOCK!r} block without {missing}; a scanned "
                "dihedral is four atoms."
            )
        columns = [np.asarray(block[name]).reshape(-1) for name in _SCAN_COLUMNS]
        if any(column.shape != (1,) for column in columns):
            raise IncompleteRecordError(
                f"THEMol record carries a {_SCAN_BLOCK!r} block of "
                f"{[int(column.shape[0]) for column in columns]} rows; one scan is one "
                "dihedral, so the block is one row."
            )
        return (int(columns[0][0]), int(columns[1][0]), int(columns[2][0]), int(columns[3][0]))

    @staticmethod
    def _key(frame: Any, *, scanned: bool) -> str:
        """This unit's identity: a scan is keyed by its scan, a molecule by itself.

        A sealed block records the key, and the two answer different questions —
        which is why a scan's key is its ``scan_id`` while everything else keys
        on ``molecule_id``. Neither is the *molecular* identity a split is routed
        by; that is :meth:`identity`.
        """
        name = "scan_id" if scanned else "molecule_id"
        value = frame.meta.get(name)
        if not isinstance(value, str) or not value:
            raise IncompleteRecordError(
                f"THEMol record carries no {name!r}, so its unit has no key; a sealed block "
                "records one key per unit and molnex refuses an empty one."
            )
        return value

    def _topology(self, key: str, frame: Any) -> dict[str, np.ndarray]:
        """Molecule-space columns of *frame*: atomic numbers and the bond block."""
        atoms = frame["atoms"]
        if "number" not in atoms:
            raise IncompleteRecordError(
                f"THEMol record {key!r} has no 'number' atom column, so its atomic numbers "
                "cannot be read; every block declares Z."
            )
        atom_z = np.asarray(atoms["number"], dtype=np.int16)
        if atom_z.ndim != 1 or atom_z.shape[0] == 0:
            raise IncompleteRecordError(
                f"THEMol record {key!r} declares {atom_z.shape} atomic numbers; a unit needs "
                "a one-dimensional, non-empty Z."
            )
        return {_REQUIRED_TOPOLOGY: atom_z, **self._bonds(key, frame)}

    def _bonds(self, key: str, frame: Any) -> dict[str, np.ndarray]:
        """Valence columns of *frame* — empty rather than missing when bondless.

        A molecule with no bonds (a bare noble-gas atom, an ion) is legitimate
        chemistry, and its unit still declares all three bond columns with zero
        rows: molnex freezes a block's schema from its first unit, so a *missing*
        column would make the second unit unappendable.
        """
        if "bonds" not in frame:
            return {name: np.empty(0, dtype=np.int32) for name in _BOND_COLUMNS}

        bonds = frame["bonds"]
        missing = [name for name in ("atomi", "atomj") if name not in bonds]
        if missing:
            raise IncompleteRecordError(
                f"THEMol record {key!r} carries a bond block without {missing}; a bond "
                "without both of its atoms is not a bond."
            )
        order = self._bond_order(key, bonds)
        atomi = np.asarray(bonds["atomi"], dtype=np.int32)
        atomj = np.asarray(bonds["atomj"], dtype=np.int32)
        if atomi.shape != atomj.shape or atomi.shape != order.shape:
            raise IncompleteRecordError(
                f"THEMol record {key!r} has bond columns of shapes atomi={atomi.shape}, "
                f"atomj={atomj.shape}, order={order.shape}; one bond family is one row "
                "count, and molnex refuses a block whose family disagrees with itself."
            )
        return {"bond_atomi": atomi, "bond_atomj": atomj, "bond_type": order}

    @staticmethod
    def _bond_order(key: str, bonds: Any) -> np.ndarray:
        """The integer bond order of *bonds*, as ``<i4``.

        ``bond_number`` first, then an integral ``bond_type`` — the two spellings
        ``molhub.dataset.themol`` copies out of the mapped-SMILES topology.
        """
        for candidate in _BOND_ORDER_COLUMNS:
            if candidate not in bonds:
                continue
            values = np.asarray(bonds[candidate])
            if values.dtype.kind in "iub":
                return values.astype(np.int32)
        raise IncompleteRecordError(
            f"THEMol record {key!r} carries bonds but no integer order column "
            f"({' or '.join(_BOND_ORDER_COLUMNS)}). A fabricated order — zero, or one for "
            "everything — would invent chemistry that the trained model would then learn, "
            "so the unit is refused instead."
        )

    @staticmethod
    def _vectors(key: str, atoms: Any, columns: tuple[str, str, str]) -> np.ndarray:
        """Stack three scalar atom columns into one ``(N, 3)`` float64 array."""
        missing = [name for name in columns if name not in atoms]
        if missing:
            raise IncompleteRecordError(
                f"THEMol record {key!r} has a frame missing atom column(s) {missing}; "
                f"{list(columns)} are read as one vector, so a partial one cannot be encoded."
            )
        return np.column_stack([np.asarray(atoms[name], dtype=np.float64) for name in columns])

    @staticmethod
    def _target(key: str, targets: Mapping[str, Any], name: str, index: int) -> float:
        """One frame-space scalar target, refusing a frame that lacks it.

        A unit's frame columns are one array each: a frame missing the target its
        siblings carry would silently shorten that array and misalign every later
        frame, which is worse than refusing the record.
        """
        if name not in targets:
            raise IncompleteRecordError(
                f"frame {index} of THEMol record {key!r} carries no {name!r} target, but the "
                "unit's first frame does. A frame column is one value per frame; dropping "
                "this one would misalign every frame after it."
            )
        return float(targets[name])

    @staticmethod
    def _torsion_atoms(key: str, torsion: Sequence[int], n_atoms: int) -> np.ndarray:
        """The scanned dihedral as one molecule-space row of four local indices."""
        indices = np.asarray(tuple(torsion), dtype=np.int32)
        if indices.shape != (4,):
            raise IncompleteRecordError(
                f"THEMol scan {key!r} names {indices.shape[0]} torsion atoms; a dihedral is four."
            )
        if int(indices.min()) < 0 or int(indices.max()) >= n_atoms:
            raise IncompleteRecordError(
                f"THEMol scan {key!r} names torsion atoms {indices.tolist()} outside its "
                f"molecule's {n_atoms} atoms; block topology indices are molecule-local."
            )
        return indices.reshape(1, 4)

    @staticmethod
    def _smiles(key: str, targets: Mapping[str, Any]) -> str:
        """The molecular identity's only input, read off the frame's targets."""
        smiles = targets.get("mapped_isomeric_smiles")
        if not isinstance(smiles, str) or not smiles:
            raise IncompleteRecordError(
                f"THEMol record {key!r} carries no 'mapped_isomeric_smiles' target, so it has "
                "no molecular identity and cannot be routed to a split. Its record id is a "
                "record id, not a molecule."
            )
        return smiles


def _stack(vectors: Sequence[np.ndarray]) -> np.ndarray:
    """Concatenate per-frame ``(N, 3)`` arrays into one ``(F * N, 3)`` ``<f4``.

    The float64 -> float32 narrowing molnex refuses to do silently, applied in
    the one place the encoder is allowed to change a number at all.
    """
    return np.concatenate(vectors).astype(np.float32, copy=False)
