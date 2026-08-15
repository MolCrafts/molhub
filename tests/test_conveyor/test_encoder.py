"""Tests for the THEMol record -> ``RawUnit`` encoder.

Mirrors ``src/molhub/conveyor/encoder.py``. Every fixture is a hand-built
:class:`molpy.Frame`, or a :class:`molpy.Trajectory` of them — exactly what
``molhub.dataset.themol`` parses out of HDF5 — with no HDF5 file, no network, no
torch and no molnex, so a failure here is about the encoder and nothing else.

Numbers are chosen so that *nothing* in this file needs a tolerance:

* every coordinate, force, energy and angle is a multiple of ``0.5``, which is
  exact in float32, so the spec's "the encoder's only numeric transformation is
  the float64 -> float32 narrowing" is checkable with ``==`` on the literal the
  fixture put in;
* the torsion fixture's two geometries really do have dihedrals ``0.0`` and
  ``180.0`` about atoms ``(0, 1, 2, 3)`` (verified against
  ``molhub.dataset.themol._dihedral_angle``), so the pinned angle goldens are
  the geometry's own and not just a copy of what the fixture wrote into
  ``frame.meta["torsion_angle"]``;
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
from molpy import Block, Frame, Trajectory

from molhub.conveyor.encoder import RawUnit, THEMolUnitEncoder
from molhub.conveyor.errors import IncompleteRecordError, UnsupportedRecordError

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

    frame.meta.update(
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
# The records after dissolution — `hf-facade-02-frame-records`: one geometry is
# a `Frame`, a multi-frame sampling unit is a `Trajectory`, and there is no
# wrapper object left to dispatch on. The MBIS record has no builder here at
# all: after dissolution an MBIS frame and a hessian frame are the same type, so
# the refusal moved to `THEMolUnitEncoder(task="mbis")` and is pinned there.
# ---------------------------------------------------------------------------

_SCAN_COLUMNS = ("atomi", "atomj", "atomk", "atoml")


def _with_scan_block(frame: Frame, atoms: Sequence[int] = HOOH_TORSION_ATOMS) -> Frame:
    """Attach the scanned dihedral as the 1-row block ``frame.meta`` cannot hold."""
    frame["scan"] = Block(
        {
            name: np.asarray([index], dtype=np.int32)
            for name, index in zip(_SCAN_COLUMNS, atoms, strict=True)
        }
    )
    return frame


def _hessian_frame() -> Frame:
    """One equilibrium geometry carrying its Hessian as a COO block.

    The block is here on purpose: the unit's pinned column set below is what
    proves the Cartesian Hessian is *dropped* rather than never offered.
    """
    frame = _water_frame(WATER_EQ_POS)
    rows, cols = np.divmod(np.arange(81), 9)
    frame["hessian"] = Block(
        {
            "row": rows.astype(np.int32),
            "col": cols.astype(np.int32),
            "value": (np.eye(9, dtype=np.float64) * 0.5).reshape(-1),
        }
    )
    return frame


def _bondless_frame() -> Frame:
    """A single neon atom — legitimate chemistry with zero bonds."""
    return _frame(
        smiles=NEON_SMILES,
        molecule_id="neon-eq",
        elements=("Ne",),
        numbers=(10,),
        positions=((0.0, 0.0, 0.0),),
        bonds=None,
    )


def _relax_trajectory() -> Trajectory:
    """One molecule's whole relaxation — two frames, no scan block."""
    return Trajectory(
        [
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
        ]
    )


def _torsion_trajectory(*, scan_on_frame_zero: bool = True) -> Trajectory:
    """One whole scan; every frame carries the scan block, unless asked otherwise.

    ``scan_on_frame_zero=False`` builds the pathological trajectory whose first
    frame has no ``scan`` block and whose second does — the encoder inspects
    frame 0, so this must encode as a plain multi-frame unit.
    """
    first = _hooh_frame(HOOH_CIS_POS, energy=HOOH_ENERGIES[0], angle=HOOH_ANGLES[0])
    second = _hooh_frame(HOOH_TRANS_POS, energy=HOOH_ENERGIES[1], angle=HOOH_ANGLES[1])
    if scan_on_frame_zero:
        _with_scan_block(first)
    _with_scan_block(second)
    return Trajectory([first, second])


@pytest.fixture
def frame_unit() -> RawUnit:
    return THEMolUnitEncoder(task="hessian").encode(_hessian_frame())


@pytest.fixture
def relax_unit() -> RawUnit:
    return THEMolUnitEncoder(task="hessian-relax").encode(_relax_trajectory())


@pytest.fixture
def scan_unit() -> RawUnit:
    return THEMolUnitEncoder(task="torsion-scan").encode(_torsion_trajectory())


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

    # -- edges -------------------------------------------------------------
    #
    # `hf-facade-02-frame-records` deleted the record dataclasses, so the
    # per-record assertions that used to live here — key, identity, task, column
    # sets, dtypes and values for a hessian / trajectory / torsion record — moved
    # verbatim into the dispatch section below, which the tester wrote as their
    # literal-for-literal replacement. What stays here are the cases that section
    # does not already make: the ones the dissolution has nothing to say about.

    def test_a_torsion_unit_identifies_the_molecule_not_the_scan(self, scan_unit: RawUnit) -> None:
        """The uuid trap: a scan id has zero overlap with molecular identity."""
        assert scan_unit.identity == HOOH_IDENTITY
        assert scan_unit.identity != THEMolUnitEncoder.identity("hooh-scan-0")

    def test_a_torsion_unit_holds_the_whole_scan(self, scan_unit: RawUnit) -> None:
        assert (scan_unit.n_atoms, scan_unit.n_frames) == (4, 2)

    def test_a_torsion_unit_stacks_both_geometries(self, scan_unit: RawUnit) -> None:
        pos = scan_unit.frames["pos"]
        assert pos.shape == (8, 3)
        assert pos.tolist() == [list(row) for row in HOOH_CIS_POS + HOOH_TRANS_POS]

    def test_a_bondless_molecule_still_carries_its_atoms(self) -> None:
        unit = THEMolUnitEncoder(task="hessian").encode(_bondless_frame())
        assert unit.topology["Z"].tolist() == [10]
        assert (unit.n_atoms, unit.n_frames) == (1, 1)

    def test_bonds_without_an_order_column_are_rejected(self) -> None:
        """A fabricated zero order would invent chemistry."""
        record = _water_frame(
            WATER_EQ_POS,
            molecule_id="water-orderless",
            bonds={"atomi": WATER_BOND_ATOMI, "atomj": WATER_BOND_ATOMJ},
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
        record = _water_frame(
            WATER_EQ_POS,
            molecule_id="water-typed",
            bonds=_water_bonds(order_column="bond_type"),
        )
        unit = THEMolUnitEncoder(task="hessian").encode(record)
        assert unit.topology["bond_type"].dtype.str == "<i4"
        assert unit.topology["bond_type"].tolist() == [1, 1]

    def test_an_unknown_object_is_unsupported(self) -> None:
        """``encode`` dispatches on record shape; anything else is a caller error."""
        with pytest.raises(UnsupportedRecordError):
            THEMolUnitEncoder(task="hessian").encode(object())

    # -- Frame / Trajectory dispatch ---------------------------------------
    #
    # After `hf-facade-02-frame-records` the record dataclasses are gone, so
    # `encode` branches on `Frame` vs `Trajectory` and on the encoder's declared
    # task. Dissolution changes the *container*, never an encoded column: every
    # key set, dtype and value below is copied from the pre-dissolution
    # assertions above, literal for literal.

    def test_a_frame_record_keys_on_the_molecule_id(self, frame_unit: RawUnit) -> None:
        """One geometry is one unit, keyed by ``frame.meta["molecule_id"]``."""
        assert frame_unit.key == "water-eq"
        assert frame_unit.identity == WATER_IDENTITY
        assert frame_unit.task == "hessian"

    def test_a_frame_record_declares_the_geometry_only_columns(self, frame_unit: RawUnit) -> None:
        """The frame's ``hessian`` block is offered and deliberately dropped."""
        assert set(frame_unit.topology) == set(HESSIAN_TOPOLOGY_COLUMNS)
        assert set(frame_unit.frames) == {"pos"}

    def test_a_frame_record_keeps_the_pinned_dtypes_and_values(self, frame_unit: RawUnit) -> None:
        """``<i2`` atomic numbers, ``<i4`` bonds, ``<f4`` angstrom positions."""
        assert frame_unit.topology["Z"].dtype.str == "<i2"
        assert frame_unit.topology["Z"].tolist() == [1, 8, 1]
        assert [
            frame_unit.topology[name].dtype.str
            for name in ("bond_atomi", "bond_atomj", "bond_type")
        ] == ["<i4", "<i4", "<i4"]
        assert frame_unit.topology["bond_atomi"].tolist() == [1, 1]
        assert frame_unit.topology["bond_atomj"].tolist() == [0, 2]
        assert frame_unit.topology["bond_type"].tolist() == [1, 1]
        assert frame_unit.frames["pos"].dtype.str == "<f4"
        assert frame_unit.frames["pos"].tolist() == [list(row) for row in WATER_EQ_POS]

    def test_a_frame_record_holds_one_frame(self, frame_unit: RawUnit) -> None:
        assert (frame_unit.n_atoms, frame_unit.n_frames) == (3, 1)

    def test_a_trajectory_record_declares_energy_and_force_columns(
        self, relax_unit: RawUnit
    ) -> None:
        assert relax_unit.key == "water-relax"
        assert set(relax_unit.topology) == set(HESSIAN_TOPOLOGY_COLUMNS)
        assert set(relax_unit.frames) == {"pos", "energy", "forces"}

    def test_a_trajectory_record_stacks_every_frame(self, relax_unit: RawUnit) -> None:
        """``pos`` is ``(F * N, 3)`` — the ``k * N`` stride the block relies on."""
        assert (relax_unit.n_atoms, relax_unit.n_frames) == (3, 2)
        assert relax_unit.frames["pos"].dtype.str == "<f4"
        assert relax_unit.frames["pos"].tolist() == [
            list(row) for row in WATER_EQ_POS + WATER_STEP_POS
        ]
        assert relax_unit.frames["forces"].dtype.str == "<f4"
        assert relax_unit.frames["forces"].tolist() == [
            list(row) for row in WATER_EQ_FORCES + WATER_STEP_FORCES
        ]

    def test_a_trajectory_record_carries_one_energy_per_frame(self, relax_unit: RawUnit) -> None:
        """kcal mol^-1, unchanged."""
        energy = relax_unit.frames["energy"]
        assert energy.dtype.str == "<f4"
        assert energy.tolist() == list(WATER_ENERGIES)

    def test_a_scan_trajectory_keys_on_the_scan_id(self, scan_unit: RawUnit) -> None:
        """A scan is the sampling unit; its key is the scan, its identity the molecule."""
        assert scan_unit.key == "hooh-scan-0"
        assert scan_unit.identity == HOOH_IDENTITY

    def test_a_scan_trajectory_declares_the_two_torsion_columns(self, scan_unit: RawUnit) -> None:
        assert set(scan_unit.topology) == {
            "Z",
            "bond_atomi",
            "bond_atomj",
            "bond_type",
            "torsion_atoms",
        }
        assert set(scan_unit.frames) == {"pos", "energy", "forces", "torsion_angle"}

    def test_a_scan_trajectory_records_the_dihedral_and_its_angles(
        self, scan_unit: RawUnit
    ) -> None:
        """Read off the ``scan`` block and the per-frame ``torsion_angle`` meta."""
        target_atoms = scan_unit.topology["torsion_atoms"]
        assert target_atoms.dtype.str == "<i4"
        assert target_atoms.shape == (1, 4)
        assert target_atoms.tolist() == [[0, 1, 2, 3]]
        angles = scan_unit.frames["torsion_angle"]
        assert angles.dtype.str == "<f4"
        assert angles.tolist() == [0.0, 180.0]

    def test_a_trajectory_without_a_scan_block_declares_no_torsion_columns(
        self, relax_unit: RawUnit
    ) -> None:
        """The scan block, not the task label, is what makes a unit a scan."""
        assert "torsion_atoms" not in relax_unit.topology
        assert "torsion_angle" not in relax_unit.frames

    def test_the_scan_block_is_inspected_on_frame_zero(self) -> None:
        """Frame 0 decides the schema; a block that appears later is not a scan."""
        unit = THEMolUnitEncoder(task="torsion-scan").encode(
            _torsion_trajectory(scan_on_frame_zero=False)
        )
        assert "torsion_atoms" not in unit.topology
        assert "torsion_angle" not in unit.frames

    def test_a_bondless_frame_yields_empty_bond_columns(self) -> None:
        """Empty, not missing: the block freezes its schema on the first unit."""
        unit = THEMolUnitEncoder(task="hessian").encode(_bondless_frame())
        assert set(unit.topology) == set(HESSIAN_TOPOLOGY_COLUMNS)
        for name in ("bond_atomi", "bond_atomj", "bond_type"):
            assert unit.topology[name].shape == (0,)
            assert unit.topology[name].dtype.str == "<i4"
        assert (unit.n_atoms, unit.n_frames) == (1, 1)

    def test_a_ragged_trajectory_of_frames_is_rejected(self) -> None:
        """``k * N`` is what makes the two-level layout valid; a stack would lie."""
        record = Trajectory(
            [
                _water_frame(
                    WATER_EQ_POS,
                    molecule_id="water-ragged",
                    forces=WATER_EQ_FORCES,
                    targets={"energy": WATER_ENERGIES[0]},
                ),
                _hooh_frame(HOOH_CIS_POS, energy=HOOH_ENERGIES[0], angle=HOOH_ANGLES[0]),
            ]
        )
        with pytest.raises(IncompleteRecordError):
            THEMolUnitEncoder(task="hessian-relax").encode(record)

    def test_constructing_an_mbis_encoder_is_refused(self) -> None:
        """After dissolution an MBIS frame and a Hessian frame are the same type.

        One shard is one task, so the refusal has to happen where the task is
        named — at construction. Refusing per record would be both later (a
        writer is already open) and weaker (a geometry-only MBIS frame is
        indistinguishable from a hessian frame).
        """
        with pytest.raises(UnsupportedRecordError):
            THEMolUnitEncoder(task="mbis")


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
        assert isinstance(THEMolUnitEncoder(task="hessian").encode(_hessian_frame()), RawUnit)
