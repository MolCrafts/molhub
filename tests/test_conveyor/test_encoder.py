"""Tests for the THEMol record -> ``RawUnit`` encoder.

Mirrors ``src/molhub/conveyor/encoder.py``. Every fixture is a hand-built
:class:`molpy.Frame` wrapped in the record dataclass
``molhub.dataset.themol`` already parses out of HDF5 — no HDF5 file, no
network, no torch, no molnex, so a failure here is about the encoder and
nothing else.

Numbers are chosen so that *nothing* in this file needs a tolerance:

* every coordinate, force, energy and angle is a multiple of ``0.5``, which is
  exact in float32, so the spec's "the encoder's only numeric transformation is
  the float64 -> float32 narrowing" is checkable with ``==`` on the literal the
  fixture put in;
* the torsion fixture's two geometries really do have dihedrals ``0.0`` and
  ``180.0`` about atoms ``(0, 1, 2, 3)`` (verified against
  ``molhub.dataset.themol._dihedral_angle``), so the pinned angle goldens stay
  true whether the encoder copies ``TorsionProfile.angles`` or the per-frame
  ``torsion_angle`` target;
* the identity hexes are pinned literals. Provenance: computed once, offline,
  with the stdlib ``hashlib.blake2b(smiles.encode(), digest_size=16).hexdigest()``
  rule that ``scripts/build_class1_splits.py:55-56`` uses to *produce* the
  ``class1-universal-splits@1`` tables (python 3.14.5, 2026-08-14). They are
  literals here on purpose: if the promoted implementation ever disagrees with
  the tables already on disk, routing silently mis-splits molecules, and a test
  that recomputed the digest with the same call could not see it.

One spec case turned out to be unrepresentable and is documented where it would
have been tested: molpy 0.12 declares ``bond_number`` / ``bond_type`` ``uint`` in
the Frame schema and rejects a string or non-integral float at write time, so
"bonds carrying a non-integer order" cannot reach the encoder at all. The
reachable half — bonds carrying *no* order column — is tested.

Units are THEMol's own (angstrom / kcal mol^-1 / kcal mol^-1 angstrom^-1,
``molhub.dataset.themol.THEMOL_UNITS``), which is already the block format's
convention; the goldens below are therefore the fixture's numbers *unchanged*,
which is how "no unit conversion happens here" is tested rather than asserted.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

import numpy as np
import pytest
from molpy import Block, Frame

from molhub.conveyor.encoder import RawUnit, THEMolUnitEncoder
from molhub.conveyor.errors import IncompleteRecordError, UnsupportedRecordError
from molhub.dataset import Targets
from molhub.dataset.themol import (
    EnergyForceTrajectory,
    HessianRecord,
    MBISRecord,
    TorsionProfile,
)

# ---------------------------------------------------------------------------
# Molecules. Three species, three identities, one bondless case.
# ---------------------------------------------------------------------------

WATER_SMILES = "[O:2]([H:1])[H:3]"
WATER_IDENTITY = "810eef0a316c3ae716b15724bd6a8779"
WATER_ELEMENTS = ("H", "O", "H")
WATER_Z = (1, 8, 1)
# Atom-map order H:1, O:2, H:3 — the order `_mapped_topology_frame` produces,
# deliberately unlike SMILES parse order.
WATER_BOND_ATOMI = (1, 1)
WATER_BOND_ATOMJ = (0, 2)
WATER_BOND_ORDER = (1, 1)

WATER_EQ_POS = ((-0.5, 0.0, 0.0), (0.0, 0.0, 0.0), (0.5, 0.0, 0.0))
WATER_STEP_POS = ((-1.0, 0.0, 0.0), (0.0, 0.5, 0.0), (1.0, 0.0, 0.0))
WATER_EQ_FORCES = ((0.5, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.5, 0.0, 0.0))
WATER_STEP_FORCES = ((0.0, 0.5, 0.0), (0.0, -1.0, 0.0), (0.0, 0.5, 0.0))
WATER_ENERGIES = (-10.0, -10.5)

HOOH_SMILES = "[H:1][O:2][O:3][H:4]"
HOOH_IDENTITY = "159fcddf7a882e2d79a52e4f129e2459"
HOOH_ELEMENTS = ("H", "O", "O", "H")
HOOH_Z = (1, 8, 8, 1)
HOOH_BOND_ATOMI = (0, 1, 2)
HOOH_BOND_ATOMJ = (1, 2, 3)
HOOH_BOND_ORDER = (1, 1, 1)
HOOH_TORSION_ATOMS = (0, 1, 2, 3)

# cis, then trans: dihedral(0,1,2,3) is exactly 0.0 and exactly 180.0.
HOOH_CIS_POS = ((-1.0, 0.5, 0.0), (-0.5, 0.0, 0.0), (0.5, 0.0, 0.0), (1.0, 0.5, 0.0))
HOOH_TRANS_POS = ((-1.0, 0.5, 0.0), (-0.5, 0.0, 0.0), (0.5, 0.0, 0.0), (1.0, -0.5, 0.0))
HOOH_ANGLES = (0.0, 180.0)
HOOH_FORCES = ((0.0, 0.5, 0.0), (0.0, -0.5, 0.0), (0.0, -0.5, 0.0), (0.0, 0.5, 0.0))
HOOH_ENERGIES = (-2.5, -2.0)

NEON_SMILES = "[Ne:1]"
NEON_IDENTITY = "7a8a2304bb79b7d3459719ef0c416aef"

# The four columns a bonded molecule declares; a bondless one must declare the
# same four (empty), because the block freezes its schema on the first unit.
HESSIAN_TOPOLOGY_COLUMNS = frozenset({"Z", "bond_atomi", "bond_atomj", "bond_type"})


# ---------------------------------------------------------------------------
# Frame construction, in the shape `molhub.dataset.themol` hands it over.
# ---------------------------------------------------------------------------


def _frame(
    *,
    smiles: str,
    molecule_id: str,
    elements: Sequence[str],
    numbers: Sequence[int],
    positions: Sequence[Sequence[float]],
    bonds: Mapping[str, Sequence[int]] | None,
    forces: Sequence[Sequence[float]] | None = None,
    targets: Mapping[str, bool | float | int | str] | None = None,
) -> Frame:
    """One frame with the columns ``_mapped_topology_frame`` writes.

    Args:
        smiles: ``mapped_isomeric_smiles`` — the split key's only input.
        molecule_id: The record-level id, written to the frame targets.
        elements: Element symbols in atom-map order.
        numbers: Atomic numbers in atom-map order.
        positions: ``(N, 3)`` coordinates in angstrom.
        bonds: Bond columns, or ``None`` for a molecule with no bonds (which
            writes no ``bonds`` block at all, exactly as the reader does).
        forces: ``(N, 3)`` forces in kcal mol^-1 angstrom^-1, when the frame
            carries them.
        targets: Extra graph-level targets (``energy``, ``torsion_angle``, ...).
    """
    coords = np.asarray(positions, dtype=np.float64)
    columns: dict[str, np.ndarray] = {
        "element": np.asarray(elements, dtype=str),
        "number": np.asarray(numbers, dtype=np.int64),
        "atom_map": np.arange(1, len(numbers) + 1, dtype=np.int64),
        "formal_charge": np.zeros(len(numbers), dtype=np.int64),
        "x": coords[:, 0],
        "y": coords[:, 1],
        "z": coords[:, 2],
    }
    if forces is not None:
        force_array = np.asarray(forces, dtype=np.float64)
        columns |= {"fx": force_array[:, 0], "fy": force_array[:, 1], "fz": force_array[:, 2]}

    frame = Frame()
    frame["atoms"] = Block(columns)
    if bonds is not None:
        frame["bonds"] = Block({name: np.asarray(value) for name, value in bonds.items()})

    Targets(frame).write(
        {
            "molecule_id": molecule_id,
            "source_record_id": molecule_id,
            "mapped_nonisomeric_smiles": smiles,
            "mapped_isomeric_smiles": smiles,
            "source_id": "dataset:themol/hessian@1#role=shard-000",
            "total_charge": 0,
            **dict(targets or {}),
        }
    )
    return frame


def _water_bonds(order_column: str = "bond_number") -> dict[str, Sequence[int]]:
    return {
        "atomi": WATER_BOND_ATOMI,
        "atomj": WATER_BOND_ATOMJ,
        order_column: WATER_BOND_ORDER,
    }


def _water_frame(
    positions: Sequence[Sequence[float]],
    *,
    molecule_id: str = "water-eq",
    forces: Sequence[Sequence[float]] | None = None,
    targets: Mapping[str, bool | float | int | str] | None = None,
    bonds: Mapping[str, Sequence[int]] | None = None,
) -> Frame:
    return _frame(
        smiles=WATER_SMILES,
        molecule_id=molecule_id,
        elements=WATER_ELEMENTS,
        numbers=WATER_Z,
        positions=positions,
        bonds=_water_bonds() if bonds is None else bonds,
        forces=forces,
        targets=targets,
    )


def _hooh_frame(
    positions: Sequence[Sequence[float]],
    *,
    energy: float,
    angle: float,
) -> Frame:
    return _frame(
        smiles=HOOH_SMILES,
        molecule_id="hooh",
        elements=HOOH_ELEMENTS,
        numbers=HOOH_Z,
        positions=positions,
        bonds={
            "atomi": HOOH_BOND_ATOMI,
            "atomj": HOOH_BOND_ATOMJ,
            "bond_number": HOOH_BOND_ORDER,
        },
        forces=HOOH_FORCES,
        targets={"scan_id": "hooh-scan-0", "energy": energy, "torsion_angle": angle},
    )


# ---------------------------------------------------------------------------
# The four records, exactly as `THEMolShardDataset.__getitem__` returns them.
# ---------------------------------------------------------------------------


def _hessian_record() -> HessianRecord:
    """One equilibrium geometry; its ``(3N, 3N)`` Hessian is deliberately dropped."""
    return HessianRecord(
        molecule_id="water-eq",
        frame=_water_frame(WATER_EQ_POS),
        hessian=np.eye(9, dtype=np.float64) * 0.5,
    )


def _bondless_record() -> HessianRecord:
    """A single neon atom — legitimate chemistry with zero bonds."""
    return HessianRecord(
        molecule_id="neon-eq",
        frame=_frame(
            smiles=NEON_SMILES,
            molecule_id="neon-eq",
            elements=("Ne",),
            numbers=(10,),
            positions=((0.0, 0.0, 0.0),),
            bonds=None,
        ),
        hessian=np.zeros((3, 3), dtype=np.float64),
    )


def _trajectory_record() -> EnergyForceTrajectory:
    """One molecule's whole relaxation — two frames of the same topology."""
    return EnergyForceTrajectory(
        molecule_id="water-relax",
        frames=(
            _water_frame(
                WATER_EQ_POS,
                molecule_id="water-relax",
                forces=WATER_EQ_FORCES,
                targets={"energy": WATER_ENERGIES[0]},
            ),
            _water_frame(
                WATER_STEP_POS,
                molecule_id="water-relax",
                forces=WATER_STEP_FORCES,
                targets={"energy": WATER_ENERGIES[1]},
            ),
        ),
    )


def _torsion_record() -> TorsionProfile:
    """One whole scan: angles and frames together, keyed by the scan id."""
    return TorsionProfile(
        molecule_id="hooh",
        scan_id="hooh-scan-0",
        torsion_atom_indices=HOOH_TORSION_ATOMS,
        angles=HOOH_ANGLES,
        frames=(
            _hooh_frame(HOOH_CIS_POS, energy=HOOH_ENERGIES[0], angle=HOOH_ANGLES[0]),
            _hooh_frame(HOOH_TRANS_POS, energy=HOOH_ENERGIES[1], angle=HOOH_ANGLES[1]),
        ),
    )


def _mbis_record() -> MBISRecord:
    return MBISRecord(
        molecule_id="water-mbis",
        frame=_water_frame(WATER_EQ_POS),
        atomic_volumes=np.ones((3, 1), dtype=np.float64),
        atomic_charge=np.asarray([[0.5], [-1.0], [0.5]], dtype=np.float64),
        atomic_dipole=np.zeros((3, 3), dtype=np.float64),
        atomic_quadrupole=np.zeros((3, 3, 3), dtype=np.float64),
        parameters=np.zeros((1, 3), dtype=np.float64),
    )


@pytest.fixture
def hessian_unit() -> RawUnit:
    return THEMolUnitEncoder(task="hessian").encode(_hessian_record())


@pytest.fixture
def trajectory_unit() -> RawUnit:
    return THEMolUnitEncoder(task="hessian-relax").encode(_trajectory_record())


@pytest.fixture
def torsion_unit() -> RawUnit:
    return THEMolUnitEncoder(task="torsion-scan").encode(_torsion_record())


class TestTHEMolUnitEncoder:
    """One record in, one whole unit out — and the units are THEMol's own."""

    # -- identity ----------------------------------------------------------

    @pytest.mark.parametrize(
        ("smiles", "identity"),
        [
            (WATER_SMILES, WATER_IDENTITY),
            (HOOH_SMILES, HOOH_IDENTITY),
            (NEON_SMILES, NEON_IDENTITY),
        ],
        ids=["water", "hooh", "neon"],
    )
    def test_identity_is_the_pinned_blake2b_128_hex(self, smiles: str, identity: str) -> None:
        """The one rule shared with split *production*; a literal, never recomputed."""
        assert THEMolUnitEncoder.identity(smiles) == identity

    def test_identity_reads_the_same_from_the_class_and_an_instance(self) -> None:
        """``scripts/build_class1_splits.py`` calls it without building an encoder."""
        assert THEMolUnitEncoder(task="hessian").identity(WATER_SMILES) == WATER_IDENTITY

    def test_identity_is_128_bits_of_hex(self) -> None:
        """``digest_size=16``: a wider digest would not match the shipped tables."""
        assert len(THEMolUnitEncoder.identity(WATER_SMILES)) == 32

    # -- HessianRecord -----------------------------------------------------

    def test_a_hessian_unit_keys_on_the_molecule_id(self, hessian_unit: RawUnit) -> None:
        assert hessian_unit.key == "water-eq"

    def test_a_hessian_unit_carries_the_molecular_identity(self, hessian_unit: RawUnit) -> None:
        assert hessian_unit.identity == WATER_IDENTITY

    def test_a_hessian_unit_carries_the_encoders_task(self, hessian_unit: RawUnit) -> None:
        """One shard, one task label, one frozen schema."""
        assert hessian_unit.task == "hessian"

    def test_a_hessian_unit_declares_the_geometry_only_columns(self, hessian_unit: RawUnit) -> None:
        """Pinned so the dropped Cartesian Hessian stays a decision, not an accident.

        ``molix.block/1`` has no routable column space for a per-molecule ragged
        2-D payload, and the Hessian core is hot-tier by strategy section 6. If a
        ``*hessian*`` column ever appears here, it arrived without a route.
        """
        assert set(hessian_unit.topology) == set(HESSIAN_TOPOLOGY_COLUMNS)
        assert set(hessian_unit.frames) == {"pos"}

    def test_a_hessian_unit_stores_atomic_numbers_as_int16(self, hessian_unit: RawUnit) -> None:
        atom_z = hessian_unit.topology["Z"]
        assert atom_z.dtype.str == "<i2"
        assert atom_z.tolist() == [1, 8, 1]

    def test_a_hessian_unit_stores_bond_columns_as_int32(self, hessian_unit: RawUnit) -> None:
        """Molecule-local ``[0, N)`` indices plus the integer bond order."""
        bond_columns = ("bond_atomi", "bond_atomj", "bond_type")
        assert [hessian_unit.topology[name].dtype.str for name in bond_columns] == [
            "<i4",
            "<i4",
            "<i4",
        ]
        assert hessian_unit.topology["bond_atomi"].tolist() == [1, 1]
        assert hessian_unit.topology["bond_atomj"].tolist() == [0, 2]
        assert hessian_unit.topology["bond_type"].tolist() == [1, 1]

    def test_a_hessian_unit_stores_positions_as_float32_angstrom(
        self, hessian_unit: RawUnit
    ) -> None:
        """The fixture's angstrom numbers, narrowed and otherwise untouched."""
        pos = hessian_unit.frames["pos"]
        assert pos.dtype.str == "<f4"
        assert pos.shape == (3, 3)
        assert pos.tolist() == [[-0.5, 0.0, 0.0], [0.0, 0.0, 0.0], [0.5, 0.0, 0.0]]

    def test_a_hessian_unit_holds_one_frame(self, hessian_unit: RawUnit) -> None:
        assert (hessian_unit.n_atoms, hessian_unit.n_frames) == (3, 1)

    # -- EnergyForceTrajectory --------------------------------------------

    def test_a_trajectory_unit_keys_on_the_molecule_id(self, trajectory_unit: RawUnit) -> None:
        assert trajectory_unit.key == "water-relax"

    def test_a_trajectory_unit_declares_energy_and_force_columns(
        self, trajectory_unit: RawUnit
    ) -> None:
        assert set(trajectory_unit.topology) == set(HESSIAN_TOPOLOGY_COLUMNS)
        assert set(trajectory_unit.frames) == {
            "pos",
            "energy",
            "forces",
        }

    def test_a_trajectory_unit_stacks_every_frames_positions(
        self, trajectory_unit: RawUnit
    ) -> None:
        """``pos`` is ``(F * N, 3)`` — the ``k * N`` stride the block relies on."""
        pos = trajectory_unit.frames["pos"]
        assert pos.dtype.str == "<f4"
        assert pos.shape == (6, 3)
        assert pos.tolist() == [
            [-0.5, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.5, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 0.5, 0.0],
            [1.0, 0.0, 0.0],
        ]

    def test_a_trajectory_unit_stacks_every_frames_forces(self, trajectory_unit: RawUnit) -> None:
        """kcal mol^-1 angstrom^-1, unchanged."""
        forces = trajectory_unit.frames["forces"]
        assert forces.dtype.str == "<f4"
        assert forces.shape == (6, 3)
        assert forces.tolist() == [
            [0.5, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.5, 0.0, 0.0],
            [0.0, 0.5, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 0.5, 0.0],
        ]

    def test_a_trajectory_unit_carries_one_energy_per_frame(self, trajectory_unit: RawUnit) -> None:
        """kcal mol^-1, unchanged."""
        energy = trajectory_unit.frames["energy"]
        assert energy.dtype.str == "<f4"
        assert energy.shape == (2,)
        assert energy.tolist() == list(WATER_ENERGIES)

    def test_a_trajectory_unit_holds_the_whole_trajectory(self, trajectory_unit: RawUnit) -> None:
        assert (trajectory_unit.n_atoms, trajectory_unit.n_frames) == (3, 2)

    # -- TorsionProfile ----------------------------------------------------

    def test_a_torsion_unit_keys_on_the_scan_id(self, torsion_unit: RawUnit) -> None:
        """A scan is the sampling unit; its key is the scan, not the molecule."""
        assert torsion_unit.key == "hooh-scan-0"

    def test_a_torsion_unit_identifies_the_molecule_not_the_scan(
        self, torsion_unit: RawUnit
    ) -> None:
        """The uuid trap: a scan id has zero overlap with molecular identity."""
        assert torsion_unit.identity == HOOH_IDENTITY
        assert torsion_unit.identity != THEMolUnitEncoder.identity("hooh-scan-0")

    def test_a_torsion_unit_declares_the_two_torsion_columns(self, torsion_unit: RawUnit) -> None:
        assert set(torsion_unit.topology) == {
            "Z",
            "bond_atomi",
            "bond_atomj",
            "bond_type",
            "torsion_atoms",
        }
        assert set(torsion_unit.frames) == {
            "pos",
            "energy",
            "forces",
            "torsion_angle",
        }

    def test_a_torsion_unit_records_the_scanned_dihedral(self, torsion_unit: RawUnit) -> None:
        """One molecule-space row of four molecule-local atom indices."""
        target_atoms = torsion_unit.topology["torsion_atoms"]
        assert target_atoms.dtype.str == "<i4"
        assert target_atoms.shape == (1, 4)
        assert target_atoms.tolist() == [[0, 1, 2, 3]]

    def test_a_torsion_unit_records_one_angle_per_frame(self, torsion_unit: RawUnit) -> None:
        """Degrees, unchanged: the fixture's geometries are exactly cis and trans."""
        angles = torsion_unit.frames["torsion_angle"]
        assert angles.dtype.str == "<f4"
        assert angles.shape == (2,)
        assert angles.tolist() == [0.0, 180.0]

    def test_a_torsion_unit_holds_the_whole_scan(self, torsion_unit: RawUnit) -> None:
        assert (torsion_unit.n_atoms, torsion_unit.n_frames) == (4, 2)

    def test_a_torsion_unit_stacks_both_geometries(self, torsion_unit: RawUnit) -> None:
        pos = torsion_unit.frames["pos"]
        assert pos.shape == (8, 3)
        assert pos.tolist() == [list(row) for row in HOOH_CIS_POS + HOOH_TRANS_POS]

    # -- edges -------------------------------------------------------------

    def test_a_molecule_with_no_bonds_yields_empty_bond_columns(self) -> None:
        """Empty, not missing: the block freezes its schema on the first unit."""
        unit = THEMolUnitEncoder(task="hessian").encode(_bondless_record())
        assert set(unit.topology) == set(HESSIAN_TOPOLOGY_COLUMNS)
        for name in ("bond_atomi", "bond_atomj", "bond_type"):
            assert unit.topology[name].shape == (0,)
            assert unit.topology[name].dtype.str == "<i4"

    def test_a_bondless_molecule_still_carries_its_atoms(self) -> None:
        unit = THEMolUnitEncoder(task="hessian").encode(_bondless_record())
        assert unit.topology["Z"].tolist() == [10]
        assert (unit.n_atoms, unit.n_frames) == (1, 1)

    def test_a_ragged_trajectory_is_rejected(self) -> None:
        """``k * N`` is what makes the two-level layout valid; a stack would lie."""
        record = EnergyForceTrajectory(
            molecule_id="water-ragged",
            frames=(
                _water_frame(
                    WATER_EQ_POS,
                    molecule_id="water-ragged",
                    forces=WATER_EQ_FORCES,
                    targets={"energy": WATER_ENERGIES[0]},
                ),
                _hooh_frame(HOOH_CIS_POS, energy=HOOH_ENERGIES[0], angle=HOOH_ANGLES[0]),
            ),
        )
        with pytest.raises(IncompleteRecordError):
            THEMolUnitEncoder(task="hessian-relax").encode(record)

    def test_bonds_without_an_order_column_are_rejected(self) -> None:
        """A fabricated zero order would invent chemistry."""
        record = HessianRecord(
            molecule_id="water-orderless",
            frame=_water_frame(
                WATER_EQ_POS,
                bonds={"atomi": WATER_BOND_ATOMI, "atomj": WATER_BOND_ATOMJ},
            ),
            hessian=np.eye(9, dtype=np.float64),
        )
        with pytest.raises(IncompleteRecordError):
            THEMolUnitEncoder(task="hessian").encode(record)

    def test_an_integer_bond_type_serves_as_the_order_fallback(self) -> None:
        """``bond_number`` first, then ``bond_type`` — the reader writes either.

        There is no third case to test: molpy 0.12 declares ``bond_number`` and
        ``bond_type`` ``uint`` in the Frame schema and refuses both a string
        (``"aromatic"``) and a non-integral float at write time, so a bonded
        molecule carrying a *non-integer* order is unrepresentable upstream of
        the encoder. The reachable defect is the one above: no order column at
        all.
        """
        record = HessianRecord(
            molecule_id="water-typed",
            frame=_water_frame(WATER_EQ_POS, bonds=_water_bonds(order_column="bond_type")),
            hessian=np.eye(9, dtype=np.float64) * 0.5,
        )
        unit = THEMolUnitEncoder(task="hessian").encode(record)
        assert unit.topology["bond_type"].dtype.str == "<i4"
        assert unit.topology["bond_type"].tolist() == [1, 1]

    def test_an_mbis_record_is_unsupported(self) -> None:
        """Atom-level electrostatics targets need column routes that do not exist."""
        with pytest.raises(UnsupportedRecordError):
            THEMolUnitEncoder(task="hessian").encode(_mbis_record())

    def test_an_unknown_object_is_unsupported(self) -> None:
        """``encode`` dispatches on record type; anything else is a caller error."""
        with pytest.raises(UnsupportedRecordError):
            THEMolUnitEncoder(task="hessian").encode(object())


class TestRawUnit:
    """The frozen numpy value type the whole prepare stage moves around."""

    @staticmethod
    def _unit() -> RawUnit:
        return RawUnit(
            key="water-relax",
            identity=WATER_IDENTITY,
            task="hessian-relax",
            topology={"Z": np.asarray([1, 8, 1], dtype=np.int16)},
            frames={"pos": np.zeros((6, 3), dtype=np.float32)},
        )

    def test_n_atoms_is_the_length_of_z(self) -> None:
        assert self._unit().n_atoms == 3

    def test_n_frames_divides_pos_rows_by_n_atoms(self) -> None:
        assert self._unit().n_frames == 2

    def test_a_raw_unit_is_frozen(self) -> None:
        """A unit that could be edited after routing could be edited after routing."""
        with pytest.raises(dataclasses.FrozenInstanceError):
            self._unit().key = "somewhere-else"  # type: ignore[misc]

    def test_the_encoder_returns_a_raw_unit(self) -> None:
        assert isinstance(THEMolUnitEncoder(task="hessian").encode(_hessian_record()), RawUnit)
