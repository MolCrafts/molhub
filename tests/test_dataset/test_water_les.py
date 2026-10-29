"""Tests for the WaterLES source — bulk liquid water (RPBE-D3) extended-XYZ.

Every test here is offline: the extended-XYZ files are written into ``tmp_path``
by the fixture below, and the retrieval seam is exercised through a fake hub, so
nothing in this file resolves a registry or opens a socket.

The literals are lifted from the deleted molnex tests
``tests/test_molix/test_datasets/test_water_les.py`` and
``tests/test_molix/test_datasets/test_units_contract.py`` (molnex commit
``6d425f7^``), together with the fixture writer in
``tests/test_molix/conftest.py`` that produced them: 40 train frames, 2 test
frames, 2 H2O per frame, a 12 Å cubic cell, and ``E(i) = -60.0 - 0.1 * i`` eV.
The forces are re-expressed as a deterministic arithmetic pattern (molnex seeded
``random.Random``), so every value in this file is a literal, not a draw.

Reference:
    Cheng B., "Latent Ewald summation for machine-learning potentials"
    npj Comput. Mater. 11:80 (2025). https://doi.org/10.1038/s41524-025-01577-7
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from molpy import Frame

from molhub.coordinate import Coordinate
from molhub.dataset import ArtifactHub, Dataset, water_les
from molhub.dataset.water_les import COORDINATE, WaterLESDataset
from tests.test_dataset.conftest import FakeHub, dissolved_wrapper_names

# ---------------------------------------------------------------------------
# Fixture writer — the molnex conftest, made RNG-free
# ---------------------------------------------------------------------------

#: Cubic cell edge in Å. The paper uses ~12.4 Å for 64 H2O at ambient density;
#: the micro-fixture keeps 12.0 Å so the Å-scale check stays meaningful.
_EDGE = 12.0

#: Per-atom binding energy used to build paper-realistic fixture energies.
#: RPBE-D3 bulk water sits near -10 eV/atom (Cheng 2025), so a 2-water,
#: 6-atom frame targets -60 eV.
_E0_PER_ATOM_EV = -10.0

#: Offsets of the two hydrogens from their oxygen, in Å. Exactly representable
#: in binary so parsed positions can be pinned as literals.
_H_OFFSETS = ((0.75, 0.5, 0.0), (0.75, -0.5, 0.0))


def _force_row(atom: int, frame: int) -> tuple[float, float, float]:
    """Deterministic force components in ``[-0.5, 0.5]`` eV·Å⁻¹.

    Well inside the ``[-1, 1]`` band the molnex fixture drew from, and inside
    the 50 eV·Å⁻¹ ceiling a healthy liquid-water frame respects.
    """
    return (
        0.25 * ((atom + frame) % 5) - 0.5,
        0.25 * ((atom + 2 * frame) % 5) - 0.5,
        0.25 * ((atom + 3 * frame) % 5) - 0.5,
    )


def _water_frame(*, frame: int, n_water: int, with_forces: bool = True) -> str:
    """One extended-XYZ frame of *n_water* H2O molecules (O, H, H per water)."""
    spacing = _EDGE / (n_water + 1)
    rows: list[str] = []
    atom = 0
    for w in range(n_water):
        ox, oy, oz = (w + 1) * spacing, _EDGE / 2.0, _EDGE / 2.0
        for symbol, (dx, dy, dz) in (("O", (0.0, 0.0, 0.0)), *zip("HH", _H_OFFSETS)):
            x, y, z = ox + dx, oy + dy, oz + dz
            if with_forces:
                fx, fy, fz = _force_row(atom, frame)
                rows.append(f"{symbol}  {x:.6f} {y:.6f} {z:.6f}  {fx:.6f} {fy:.6f} {fz:.6f}")
            else:
                rows.append(f"{symbol}  {x:.6f} {y:.6f} {z:.6f}")
            atom += 1

    lattice = f'"{_EDGE:.6f} 0.0 0.0 0.0 {_EDGE:.6f} 0.0 0.0 0.0 {_EDGE:.6f}"'
    properties = "species:S:1:pos:R:3:forces:R:3" if with_forces else "species:S:1:pos:R:3"
    energy = 3 * n_water * _E0_PER_ATOM_EV - 0.1 * frame
    comment = f'Lattice={lattice} Properties={properties} energy={energy:.6f} pbc="T T T"'
    return "\n".join([str(3 * n_water), comment, *rows]) + "\n"


def _write_water_extxyz(
    path: Path, *, n_frames: int, n_water: int = 2, with_forces: bool = True
) -> None:
    path.write_text(
        "".join(
            _water_frame(frame=i, n_water=n_water, with_forces=with_forces) for i in range(n_frames)
        ),
        encoding="utf-8",
    )


@pytest.fixture
def water_les_root(tmp_path) -> Path:
    """Directory with a 40-frame train pool and a 2-frame test file.

    40 train frames is the smallest count that gives a clean 0.95 / 0.05
    deterministic slice (38 train / 2 val), so the split test can assert
    disjoint, ordered, non-empty slices on both sides.
    """
    root = tmp_path / "water_les"
    root.mkdir()
    _write_water_extxyz(root / WaterLESDataset.TRAIN_FILE, n_frames=40)
    _write_water_extxyz(root / WaterLESDataset.TEST_FILE, n_frames=2)
    return root


def _energies(frames: Dataset) -> list[float]:
    return [float(frames[i][0].meta["energy"]) for i in range(len(frames))]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestWaterLESParse:
    def test_test_split_frame_count(self, water_les_root):
        assert len(WaterLESDataset(water_les_root, split="test").load()) == 2

    def test_sample_is_a_molpy_frame(self, water_les_root):
        assert isinstance(WaterLESDataset(water_les_root, split="test").load()[0][0], Frame)

    def test_loaded_collection_is_a_map_dataset(self, water_les_root):
        assert isinstance(WaterLESDataset(water_les_root, split="test").load(), Dataset)

    def test_atoms_block_columns(self, water_les_root):
        atoms = WaterLESDataset(water_les_root, split="test").load()[0][0]["atoms"]
        for column in ("element", "x", "y", "z", "number", "fx", "fy", "fz"):
            assert column in atoms

    def test_atom_count(self, water_les_root):
        """2 H2O = 6 atoms in the fixture-scaled configuration."""
        assert WaterLESDataset(water_les_root, split="test").load()[0][0]["atoms"].n_rows == 6

    def test_atomic_numbers(self, water_les_root):
        atoms = WaterLESDataset(water_les_root, split="test").load()[0][0]["atoms"]
        assert list(atoms["number"]) == [8, 1, 1, 8, 1, 1]

    def test_element_column_is_unicode(self, water_les_root):
        atoms = WaterLESDataset(water_les_root, split="test").load()[0][0]["atoms"]
        assert atoms["element"].dtype.kind == "U"

    def test_coordinate_dtype_is_float64(self, water_les_root):
        atoms = WaterLESDataset(water_les_root, split="test").load()[0][0]["atoms"]
        assert atoms["x"].dtype == np.float64
        assert atoms["y"].dtype == np.float64
        assert atoms["z"].dtype == np.float64

    def test_first_oxygen_position(self, water_les_root):
        """First O sits at ``(4, 6, 6)`` Å — position tolerance 1e-12."""
        atoms = WaterLESDataset(water_les_root, split="test").load()[0][0]["atoms"]
        assert atoms["x"][0] == pytest.approx(4.0, abs=1e-12)
        assert atoms["y"][0] == pytest.approx(6.0, abs=1e-12)
        assert atoms["z"][0] == pytest.approx(6.0, abs=1e-12)

    def test_first_hydrogen_position(self, water_les_root):
        atoms = WaterLESDataset(water_les_root, split="test").load()[0][0]["atoms"]
        assert atoms["x"][1] == pytest.approx(4.75, abs=1e-12)
        assert atoms["y"][1] == pytest.approx(6.5, abs=1e-12)
        assert atoms["z"][1] == pytest.approx(6.0, abs=1e-12)

    def test_energy_is_a_plain_float_target(self, water_les_root):
        """Graph-level energy lives in ``frame.meta`` as a Python float."""
        frame = WaterLESDataset(water_les_root, split="test").load()[0][0]
        assert isinstance(getattr(frame.meta["energy"], "value", frame.meta["energy"]), float)

    def test_energy_is_the_only_graph_level_target(self, water_les_root):
        """``Lattice="…"`` splits into bare numeric tokens; only ``energy=`` counts."""
        frame = WaterLESDataset(water_les_root, split="test").load()[0][0]
        assert set(frame.meta) == {"energy"}


# ---------------------------------------------------------------------------
# Periodic cell
# ---------------------------------------------------------------------------


class TestWaterLESCell:
    def test_cell_is_carried_on_the_frame_box(self, water_les_root):
        frame = WaterLESDataset(water_les_root, split="test").load()[0][0]
        assert frame.box is not None
        assert np.asarray(frame.box.matrix).shape == (3, 3)

    def test_cell_is_the_twelve_angstrom_cubic_lattice(self, water_les_root):
        """The loader passes the lattice through verbatim — no unit scaling.

        A loader that silently dropped a Bohr→Å factor would land at ~6.3 Å;
        one that scaled Å→nm would land at 0.12.
        """
        frame = WaterLESDataset(water_les_root, split="test").load()[0][0]
        expected = np.eye(3) * 12.0
        assert np.allclose(np.asarray(frame.box.matrix), expected, atol=1e-12)


# ---------------------------------------------------------------------------
# Deterministic 0.95 / 0.05 split
# ---------------------------------------------------------------------------


class TestWaterLESSplit:
    def test_train_split_length(self, water_les_root):
        assert len(WaterLESDataset(water_les_root, split="train").load()) == 38

    def test_val_split_length(self, water_les_root):
        assert len(WaterLESDataset(water_les_root, split="val").load()) == 2

    def test_test_split_length(self, water_les_root):
        assert len(WaterLESDataset(water_les_root, split="test").load()) == 2

    def test_val_is_the_tail_of_the_train_file(self, water_les_root):
        """No shuffle: val is the last ``ceil(0.05 * n)`` frames, in order."""
        val = _energies(WaterLESDataset(water_les_root, split="val").load())
        assert val == [pytest.approx(-63.8, abs=1e-6), pytest.approx(-63.9, abs=1e-6)]

    def test_train_and_val_do_not_overlap(self, water_les_root):
        train = set(_energies(WaterLESDataset(water_les_root, split="train").load()))
        val = _energies(WaterLESDataset(water_les_root, split="val").load())
        assert all(energy not in train for energy in val)

    def test_train_and_val_reconstruct_the_whole_file(self, water_les_root):
        train = _energies(WaterLESDataset(water_les_root, split="train").load())
        val = _energies(WaterLESDataset(water_les_root, split="val").load())
        expected = sorted(-60.0 - 0.1 * i for i in range(40))
        for got, want in zip(sorted(train + val), expected):
            assert got == pytest.approx(want, abs=1e-6)

    def test_single_frame_train_file_keeps_the_frame_in_train(self, tmp_path):
        """``ceil(0.95 * 1) == 1`` — the lone frame trains, val is empty."""
        root = tmp_path / "one"
        root.mkdir()
        _write_water_extxyz(root / WaterLESDataset.TRAIN_FILE, n_frames=1)
        assert len(WaterLESDataset(root, split="train").load()) == 1

    def test_single_frame_train_file_yields_an_empty_val(self, tmp_path):
        root = tmp_path / "one"
        root.mkdir()
        _write_water_extxyz(root / WaterLESDataset.TRAIN_FILE, n_frames=1)
        assert len(WaterLESDataset(root, split="val").load()) == 0

    def test_train_val_ratio_matches_the_upstream_yaml(self):
        """Guards against a silent retune of the Allegro-LES water recipe."""
        assert WaterLESDataset.TRAIN_VAL_RATIO == (0.95, 0.05)

    def test_train_file_name_matches_upstream(self):
        assert WaterLESDataset.TRAIN_FILE == "train-H2O_RPBE-D3.xyz"

    def test_test_file_name_matches_upstream(self):
        assert WaterLESDataset.TEST_FILE == "test-H2O_RPBE-D3.xyz"

    def test_splits_are_the_three_named_views(self):
        assert WaterLESDataset.SPLITS == frozenset({"train", "val", "test"})


# ---------------------------------------------------------------------------
# Paper units — eV / eV·Å⁻¹ / Å, pass-through only
# ---------------------------------------------------------------------------


class TestWaterLESUnits:
    def test_energy_is_ev_scale_per_atom(self, water_les_root):
        """Healthy RPBE-D3 water sits near -10 eV/atom.

        A loader that dropped a Hartree→eV factor would land near -370 eV/atom;
        one that dropped a kJ/mol→eV factor near -0.1 eV/atom. Either fails.
        """
        frames = WaterLESDataset(water_les_root, split="test").load()
        for i in range(len(frames)):
            frame = frames[i][0]
            per_atom = float(frame.meta["energy"]) / frame["atoms"].n_rows
            assert -20.0 < per_atom < -5.0

    def test_energy_passes_through_unscaled(self, water_les_root):
        """The fixture writes ``E(i) = -60.0 - 0.1 * i`` eV; so must the loader."""
        frames = WaterLESDataset(water_les_root, split="test").load()
        assert _energies(frames) == [
            pytest.approx(-60.0, abs=1e-6),
            pytest.approx(-60.1, abs=1e-6),
        ]

    def test_forces_pass_through_unscaled(self, water_les_root):
        """First atom of the first frame carries ``(-0.5, -0.5, -0.5)`` eV·Å⁻¹."""
        atoms = WaterLESDataset(water_les_root, split="test").load()[0][0]["atoms"]
        assert atoms["fx"][0] == pytest.approx(-0.5, abs=1e-8)
        assert atoms["fy"][0] == pytest.approx(-0.5, abs=1e-8)
        assert atoms["fz"][0] == pytest.approx(-0.5, abs=1e-8)

    def test_forces_stay_inside_the_written_band(self, water_les_root):
        """A silent Hartree/Bohr→eV/Å rescale would inflate these by ~51×."""
        frames = WaterLESDataset(water_les_root, split="test").load()
        for i in range(len(frames)):
            atoms = frames[i][0]["atoms"]
            for column in ("fx", "fy", "fz"):
                assert float(np.abs(np.asarray(atoms[column])).max()) <= 1.0 + 1e-8

    def test_force_columns_are_float64(self, water_les_root):
        atoms = WaterLESDataset(water_les_root, split="test").load()[0][0]["atoms"]
        assert atoms["fx"].dtype == np.float64

    # -- and the declaration that says so ------------------------------------
    #
    # The tests above pin that the loader rescales nothing; these pin that the
    # class *says* what the numbers are. ``@dataset`` is already on
    # ``WaterLESDataset`` but passes no ``units=``, so a reader of the
    # declaration (and ``Feature.declared``) is told nothing.
    #
    # Provenance, in this module's own docstring, ``water_les.py:16-18``:
    #     "Units pass through unscaled: energies in eV, forces in eV·Å⁻¹,
    #      positions and cell in Å, exactly as written upstream."
    #
    # Spelling: the ASCII, solidus-composed ``eV/angstrom``, not the docstring's
    # typographic ``eV·Å⁻¹``. Every declared unit string in molhub is ASCII —
    # ``THEMOL_UNITS`` spells ``kcal/mol/angstrom``, ``angstrom^-1``,
    # ``e*angstrom^2`` — and these strings are parsed back through the molpy
    # unit registry by ``molhub.dataset.transforms.UnitConvert``, which knows
    # ``angstrom`` and not ``Å``. Prose may use the typographic form; a
    # declaration may not.
    #
    # Positions and the cell are in Å too, but ``pos`` is not a declared target
    # name — ``units`` is keyed by the names in ``TARGET_SCHEMA`` — so the
    # mapping carries no key for it.

    def test_the_declaration_says_the_energy_is_in_electronvolts(self):
        assert WaterLESDataset.manifest.units["energy"] == "eV"

    def test_the_declaration_says_the_forces_are_in_electronvolts_per_angstrom(self):
        assert WaterLESDataset.manifest.units["forces"] == "eV/angstrom"

    def test_the_units_mapping_names_exactly_the_declared_targets(self):
        """No stray key: a unit for a name no record carries never renders."""
        schema = WaterLESDataset.TARGET_SCHEMA
        assert set(WaterLESDataset.manifest.units) == set(schema.graph_level) | set(
            schema.atom_level
        )


# ---------------------------------------------------------------------------
# Target schema
# ---------------------------------------------------------------------------


class TestWaterLESTargetSchema:
    def test_energy_is_graph_level(self):
        assert WaterLESDataset.TARGET_SCHEMA.graph_level == frozenset({"energy"})

    def test_forces_are_atom_level(self):
        assert WaterLESDataset.TARGET_SCHEMA.atom_level == frozenset({"forces"})


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestWaterLESIdentity:
    def test_definition_carries_a_frozen_manifest(self):
        """Declared on the ``@dataset`` protocol, not beside it."""
        assert WaterLESDataset.manifest.canonical == COORDINATE

    def test_coordinate_literal(self):
        assert COORDINATE == "dataset:molcrafts/water-les@1"

    def test_source_id_names_the_coordinate_and_the_split(self, water_les_root):
        src = WaterLESDataset(water_les_root, split="train")
        assert src.source_id == "dataset:molcrafts/water-les@1#split=train"

    def test_source_id_is_deterministic(self, water_les_root):
        src = WaterLESDataset(water_les_root, split="train")
        assert src.source_id == src.source_id

    def test_source_id_distinguishes_the_three_splits(self, water_les_root):
        ids = {
            WaterLESDataset(water_les_root, split=split).source_id
            for split in ("train", "val", "test")
        }
        assert len(ids) == 3

    def test_source_id_prefix_is_a_parseable_coordinate(self, water_les_root):
        bare = WaterLESDataset(water_les_root, split="val").source_id.split("#", 1)[0]
        assert Coordinate.parse(bare).canonical == bare == COORDINATE

    def test_source_id_carries_no_local_details(self, water_les_root):
        """molnex folded byte size and frame count in; that made it unaddressable."""
        source_id = WaterLESDataset(water_les_root, split="train").source_id
        assert "size=" not in source_id
        assert "n=" not in source_id

    def test_loaded_dataset_keeps_the_declared_source_id(self, water_les_root):
        """load() used to hand back an InMemoryDataset that folded the frame
        count into its id — the loaded view must keep the coordinate form."""
        loaded = WaterLESDataset(water_les_root, split="train").load()
        assert loaded.source_id == "dataset:molcrafts/water-les@1#split=train"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TestWaterLESErrors:
    def test_unknown_split_is_rejected(self, water_les_root):
        with pytest.raises(ValueError, match="split"):
            WaterLESDataset(water_les_root, split="not_a_split")

    def test_unknown_split_error_lists_the_splits(self, water_les_root):
        with pytest.raises(ValueError, match="val"):
            WaterLESDataset(water_les_root, split="not_a_split")

    def test_frame_without_forces_is_rejected(self, tmp_path):
        """``TARGET_SCHEMA`` promises forces; a file without them is malformed."""
        root = tmp_path / "no_forces"
        root.mkdir()
        _write_water_extxyz(root / WaterLESDataset.TEST_FILE, n_frames=1, with_forces=False)
        with pytest.raises(ValueError, match="forces"):
            WaterLESDataset(root, split="test").load()


# ---------------------------------------------------------------------------
# Retrieval by coordinate
# ---------------------------------------------------------------------------


class TestWaterLESRetrieval:
    def test_the_fake_still_matches_the_seam_it_stands_in_for(self):
        """A fake that drifts from the protocol proves nothing about the source."""
        assert isinstance(FakeHub({}), ArtifactHub)

    def test_absent_file_is_fetched_by_coordinate(self, tmp_path, water_les_root):
        hub = FakeHub({"train": water_les_root / WaterLESDataset.TRAIN_FILE})
        frames = WaterLESDataset(tmp_path / "empty", split="train", hub=hub).load()
        assert len(frames) == 38

    def test_fetch_asks_for_the_canonical_coordinate(self, tmp_path, water_les_root):
        hub = FakeHub({"train": water_les_root / WaterLESDataset.TRAIN_FILE})
        WaterLESDataset(tmp_path / "empty", split="train", hub=hub).load()
        assert hub.calls == [(COORDINATE, ["train"])]

    def test_val_reuses_the_train_role(self, tmp_path, water_les_root):
        """train and val slice one upstream file; val must not fetch a second."""
        hub = FakeHub({"train": water_les_root / WaterLESDataset.TRAIN_FILE})
        WaterLESDataset(tmp_path / "empty", split="val", hub=hub).load()
        assert hub.calls == [(COORDINATE, ["train"])]

    def test_test_split_asks_for_the_test_role(self, tmp_path, water_les_root):
        hub = FakeHub({"test": water_les_root / WaterLESDataset.TEST_FILE})
        WaterLESDataset(tmp_path / "empty", split="test", hub=hub).load()
        assert hub.calls == [(COORDINATE, ["test"])]

    def test_construction_alone_fetches_nothing(self, tmp_path, water_les_root):
        """Loading is lazy: constructing must not cost a download."""
        hub = FakeHub({"train": water_les_root / WaterLESDataset.TRAIN_FILE})
        WaterLESDataset(tmp_path / "empty", split="train", hub=hub)
        assert hub.calls == []

    def test_present_file_is_used_without_the_hub(self, water_les_root):
        hub = FakeHub({})
        WaterLESDataset(water_les_root, split="train", hub=hub).load()
        assert hub.calls == []

    def test_zero_byte_file_is_treated_as_absent(self, tmp_path, water_les_root):
        """An interrupted download used to parse as a silently empty dataset."""
        stub_root = tmp_path / "interrupted"
        stub_root.mkdir()
        (stub_root / WaterLESDataset.TEST_FILE).write_bytes(b"")
        hub = FakeHub({"test": water_les_root / WaterLESDataset.TEST_FILE})
        assert len(WaterLESDataset(stub_root, split="test", hub=hub).load()) == 2


# ---------------------------------------------------------------------------
# Graph-level meta lives on the frame, not behind a molhub wrapper
# ---------------------------------------------------------------------------


class TestWaterLESMeta:
    """The loader's graph-level surface is ``frame.meta`` and nothing else."""

    def test_energy_is_read_straight_off_frame_meta(self, water_les_root):
        """First test frame carries ``E = -60.0`` eV, with no accessor between."""
        frame = WaterLESDataset(water_les_root, split="test").load()[0][0]
        assert float(frame.meta["energy"]) == pytest.approx(-60.0, abs=1e-6)

    def test_frame_meta_hands_back_a_plain_python_float(self, water_les_root):
        """molpy 0.13 unwraps on read, so nothing in molhub has to decode."""
        frame = WaterLESDataset(water_les_root, split="test").load()[0][0]
        assert isinstance(getattr(frame.meta["energy"], "value", frame.meta["energy"]), float)

    def test_module_namespace_holds_no_deleted_meta_wrapper(self):
        assert [
            name for name in ("Targets", "MetaCodec", "write_meta") if hasattr(water_les, name)
        ] == []

    def test_module_source_names_no_deleted_meta_wrapper(self):
        assert dissolved_wrapper_names(water_les) == []
