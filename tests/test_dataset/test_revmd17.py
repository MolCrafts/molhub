"""Tests for the revMD17 source — built on synthetic NPZ files, never network."""

from __future__ import annotations

import numpy as np
import pytest

from molhub.dataset import MapDataset, RevMD17Source, Targets

_N_FRAMES = 3
_CHARGES = [6, 1, 8]  # C, H, O


def _write_npz(
    root,
    *,
    molecule: str = "aspirin",
    charges: list[int] | None = None,
    drop_key: str | None = None,
):
    """Write a synthetic ``rmd17_<molecule>.npz`` and return its path."""
    z = np.array(_CHARGES if charges is None else charges, dtype=np.int64)
    n_atoms = len(z)
    payload = {
        "nuclear_charges": z,
        "coords": np.arange(_N_FRAMES * n_atoms * 3, dtype=np.float64).reshape(
            _N_FRAMES, n_atoms, 3
        ),
        "energies": np.array([-10.0, -11.0, -12.0], dtype=np.float64),
        "forces": np.full((_N_FRAMES, n_atoms, 3), 0.5, dtype=np.float64),
    }
    if drop_key is not None:
        del payload[drop_key]
    path = root / f"rmd17_{molecule}.npz"
    np.savez(path, **payload)
    return path


@pytest.fixture
def npz_root(tmp_path):
    _write_npz(tmp_path)
    return tmp_path


class TestRevMD17SourceConstruction:
    def test_unknown_molecule_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown revMD17 molecule"):
            RevMD17Source(tmp_path, molecule="caffeine")

    def test_error_lists_available_molecules(self, tmp_path):
        with pytest.raises(ValueError, match="aspirin"):
            RevMD17Source(tmp_path, molecule="caffeine")

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            RevMD17Source(tmp_path, molecule="aspirin")

    def test_missing_required_key_raises(self, tmp_path):
        _write_npz(tmp_path, drop_key="forces")
        with pytest.raises(KeyError, match="forces"):
            RevMD17Source(tmp_path, molecule="aspirin")

    def test_filepath_points_at_canonical_name(self, npz_root):
        src = RevMD17Source(npz_root, molecule="aspirin")
        assert src.filename == "rmd17_aspirin.npz"
        assert src.filepath == npz_root / "rmd17_aspirin.npz"


class TestRevMD17SourceAccess:
    def test_len_matches_frame_count(self, npz_root):
        assert len(RevMD17Source(npz_root)) == _N_FRAMES

    def test_is_map_dataset(self, npz_root):
        assert isinstance(RevMD17Source(npz_root), MapDataset)

    def test_atoms_block_columns(self, npz_root):
        frame = RevMD17Source(npz_root)[0]
        for column in ("element", "x", "y", "z", "number", "fx", "fy", "fz"):
            assert column in frame["atoms"].keys()

    def test_element_symbols_from_charges(self, npz_root):
        frame = RevMD17Source(npz_root)[0]
        assert list(frame["atoms"]["element"]) == ["C", "H", "O"]

    def test_unmapped_charge_becomes_question_mark(self, tmp_path):
        _write_npz(tmp_path, charges=[6, 15])  # phosphorus is not in the table
        frame = RevMD17Source(tmp_path)[0]
        assert list(frame["atoms"]["element"]) == ["C", "?"]

    def test_atomic_numbers_preserved(self, npz_root):
        frame = RevMD17Source(npz_root)[0]
        assert list(frame["atoms"]["number"]) == _CHARGES

    def test_coordinates_are_split_into_columns(self, npz_root):
        frame = RevMD17Source(npz_root)[0]
        # coords[0] is [[0,1,2],[3,4,5],[6,7,8]]
        assert list(frame["atoms"]["x"]) == pytest.approx([0.0, 3.0, 6.0])
        assert list(frame["atoms"]["y"]) == pytest.approx([1.0, 4.0, 7.0])
        assert list(frame["atoms"]["z"]) == pytest.approx([2.0, 5.0, 8.0])

    def test_forces_are_split_into_columns(self, npz_root):
        frame = RevMD17Source(npz_root)[0]
        assert list(frame["atoms"]["fx"]) == pytest.approx([0.5, 0.5, 0.5])

    def test_energy_lands_in_frame_meta(self, npz_root):
        src = RevMD17Source(npz_root)
        assert Targets(src[0]).read()["energy"] == pytest.approx(-10.0)
        assert Targets(src[2]).read()["energy"] == pytest.approx(-12.0)

    def test_energy_is_a_plain_float(self, npz_root):
        assert isinstance(Targets(RevMD17Source(npz_root)[0]).read()["energy"], float)

    def test_frames_are_independent(self, npz_root):
        src = RevMD17Source(npz_root)
        assert Targets(src[0]).read()["energy"] != Targets(src[1]).read()["energy"]

    def test_source_id_shape(self, npz_root):
        src = RevMD17Source(npz_root, molecule="aspirin")
        assert src.source_id.startswith("revmd17:aspirin:size=")
        assert src.source_id.endswith(f":n={_N_FRAMES}")


class TestRevMD17TargetSchema:
    def test_energy_is_graph_level(self):
        assert "energy" in RevMD17Source.TARGET_SCHEMA.graph_level

    def test_forces_are_atom_level(self):
        assert "forces" in RevMD17Source.TARGET_SCHEMA.atom_level
