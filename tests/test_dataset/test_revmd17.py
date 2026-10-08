"""Tests for the revMD17 source — synthetic NPZ files and a fake hub, never network.

The one class that talks to Figshare is marked ``network`` and deselected by
default; it resolves metadata and fetches the 2 kB readme, never a 150 MB array.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

import molhub
from molhub.coordinate import Coordinate
from molhub.dataset import ArtifactHub, MapDataset, RevMD17Dataset
from molhub.dataset.revmd17 import _MOLECULES, COORDINATE
from molhub.manifest import Manifest

_N_FRAMES = 3
_CHARGES = [6, 1, 8]  # C, H, O

_MANIFEST_PATH = (
    Path(molhub.__file__).parent / "registry_data" / Coordinate.parse(COORDINATE).relative_path()
)


def _write_npz(
    root,
    *,
    molecule: str = "aspirin",
    charges: list[int] | None = None,
    drop_key: str | None = None,
) -> Path:
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


@dataclass
class FakeHub:
    """An :class:`~molhub.dataset.hub.ArtifactHub` serving files already on disk.

    Records what it was asked for so a test can assert the source requests one
    pinned coordinate and only the role it actually needs.
    """

    paths: dict[str, Path] = field(default_factory=dict)
    calls: list[tuple[str, list[str] | None]] = field(default_factory=list)

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        self.calls.append((coordinate, roles))
        wanted = list(self.paths) if roles is None else roles
        return {role: self.paths[role] for role in wanted}


@pytest.fixture
def npz_root(tmp_path):
    """A directory holding a pre-downloaded ``rmd17_aspirin.npz``."""
    _write_npz(tmp_path)
    return tmp_path


@pytest.fixture
def hub(tmp_path):
    """A hub serving a synthetic aspirin NPZ from outside *root*."""
    served = tmp_path / "served"
    served.mkdir()
    return FakeHub(paths={"aspirin": _write_npz(served)})


class TestRevMD17DatasetConstruction:
    def test_unknown_molecule_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown revMD17 molecule"):
            RevMD17Dataset(tmp_path, molecule="caffeine", download=False)

    def test_error_lists_available_molecules(self, tmp_path):
        with pytest.raises(ValueError, match="aspirin"):
            RevMD17Dataset(tmp_path, molecule="caffeine", download=False)

    def test_unknown_molecule_is_rejected_before_any_fetch(self, tmp_path, hub):
        """Validate at the boundary: a typo must not cost a download."""
        with pytest.raises(ValueError, match="Unknown revMD17 molecule"):
            RevMD17Dataset(tmp_path, molecule="caffeine", hub=hub)
        assert hub.calls == []

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            RevMD17Dataset(tmp_path, molecule="aspirin", download=False)

    def test_zero_byte_file_counts_as_absent(self, tmp_path):
        """A truncated transfer leaves a 0-byte file; treating it as present is
        how such a failure becomes permanent."""
        (tmp_path / "rmd17_aspirin.npz").write_bytes(b"")
        with pytest.raises(FileNotFoundError):
            RevMD17Dataset(tmp_path, molecule="aspirin", download=False)

    def test_offline_error_points_at_the_coordinate(self, tmp_path):
        with pytest.raises(FileNotFoundError, match=COORDINATE):
            RevMD17Dataset(tmp_path, molecule="aspirin", download=False)

    def test_missing_required_key_raises(self, tmp_path):
        _write_npz(tmp_path, drop_key="forces")
        with pytest.raises(KeyError, match="forces"):
            RevMD17Dataset(tmp_path, molecule="aspirin", download=False)

    def test_filepath_points_at_canonical_name(self, npz_root):
        src = RevMD17Dataset(npz_root, molecule="aspirin", download=False)
        assert src.filename == "rmd17_aspirin.npz"
        assert src.filepath == npz_root / "rmd17_aspirin.npz"

    def test_no_upstream_url_is_hardcoded(self):
        """Locators belong in the manifest; the module holds a coordinate only."""
        assert not hasattr(RevMD17Dataset, "BASE_URL")


class TestRevMD17DatasetDownload:
    def test_the_fake_still_matches_the_seam_it_stands_in_for(self, hub):
        """A fake that drifts from the protocol proves nothing about the source."""
        assert isinstance(hub, ArtifactHub)

    def test_download_fetches_through_the_hub(self, tmp_path, hub):
        src = RevMD17Dataset(tmp_path, molecule="aspirin", download=True, hub=hub)
        assert len(src) == _N_FRAMES

    def test_download_uses_the_pinned_coordinate(self, tmp_path, hub):
        RevMD17Dataset(tmp_path, molecule="aspirin", download=True, hub=hub)
        assert hub.calls[0][0] == COORDINATE

    def test_download_requests_only_this_molecules_role(self, tmp_path, hub):
        """A whole-manifest fetch would pull all ten molecules — over a gigabyte."""
        RevMD17Dataset(tmp_path, molecule="aspirin", download=True, hub=hub)
        assert hub.calls[0][1] == ["aspirin"]

    def test_download_is_the_default(self, tmp_path, hub):
        RevMD17Dataset(tmp_path, molecule="aspirin", hub=hub)
        assert len(hub.calls) == 1

    def test_download_ignores_root(self, tmp_path, hub):
        """Fetched bytes land in the shared cache, not in *root*."""
        src = RevMD17Dataset(tmp_path, molecule="aspirin", download=True, hub=hub)
        assert src.filepath == hub.paths["aspirin"]
        assert list(tmp_path.iterdir()) == [tmp_path / "served"]

    def test_offline_never_touches_the_hub(self, npz_root, hub):
        RevMD17Dataset(npz_root, molecule="aspirin", download=False, hub=hub)
        assert hub.calls == []


class TestRevMD17DatasetAccess:
    def test_len_matches_frame_count(self, npz_root):
        assert len(RevMD17Dataset(npz_root, download=False)) == _N_FRAMES

    def test_is_map_dataset(self, npz_root):
        assert isinstance(RevMD17Dataset(npz_root, download=False), MapDataset)

    def test_atoms_block_columns(self, npz_root):
        frame = RevMD17Dataset(npz_root, download=False)[0]
        for column in ("element", "x", "y", "z", "number", "fx", "fy", "fz"):
            assert column in frame["atoms"].keys()

    def test_element_symbols_from_charges(self, npz_root):
        frame = RevMD17Dataset(npz_root, download=False)[0]
        assert list(frame["atoms"]["element"]) == ["C", "H", "O"]

    def test_unmapped_charge_becomes_question_mark(self, tmp_path):
        _write_npz(tmp_path, charges=[6, 15])  # phosphorus is not in the table
        frame = RevMD17Dataset(tmp_path, download=False)[0]
        assert list(frame["atoms"]["element"]) == ["C", "?"]

    def test_atomic_numbers_preserved(self, npz_root):
        frame = RevMD17Dataset(npz_root, download=False)[0]
        assert list(frame["atoms"]["number"]) == _CHARGES

    def test_coordinates_are_split_into_columns(self, npz_root):
        frame = RevMD17Dataset(npz_root, download=False)[0]
        # coords[0] is [[0,1,2],[3,4,5],[6,7,8]]
        assert list(frame["atoms"]["x"]) == pytest.approx([0.0, 3.0, 6.0])
        assert list(frame["atoms"]["y"]) == pytest.approx([1.0, 4.0, 7.0])
        assert list(frame["atoms"]["z"]) == pytest.approx([2.0, 5.0, 8.0])

    def test_forces_are_split_into_columns(self, npz_root):
        frame = RevMD17Dataset(npz_root, download=False)[0]
        assert list(frame["atoms"]["fx"]) == pytest.approx([0.5, 0.5, 0.5])

    def test_energy_lands_in_frame_meta(self, npz_root):
        src = RevMD17Dataset(npz_root, download=False)
        assert src[0].meta["energy"] == pytest.approx(-10.0)
        assert src[2].meta["energy"] == pytest.approx(-12.0)

    def test_energy_is_a_plain_float(self, npz_root):
        src = RevMD17Dataset(npz_root, download=False)
        assert isinstance(src[0].meta["energy"], float)

    def test_frames_are_independent(self, npz_root):
        src = RevMD17Dataset(npz_root, download=False)
        assert src[0].meta["energy"] != src[1].meta["energy"]


class TestRevMD17DatasetId:
    def test_names_the_coordinate_and_the_molecule(self, npz_root):
        src = RevMD17Dataset(npz_root, molecule="aspirin", download=False)
        assert src.source_id == f"{COORDINATE}#molecule=aspirin"

    def test_the_part_before_the_hash_is_a_coordinate(self, npz_root):
        src = RevMD17Dataset(npz_root, molecule="aspirin", download=False)
        coordinate, _, _ = src.source_id.partition("#")
        assert Coordinate.parse(coordinate).canonical == COORDINATE

    def test_differs_per_molecule(self, tmp_path):
        _write_npz(tmp_path, molecule="uracil")
        _write_npz(tmp_path, molecule="aspirin")
        first = RevMD17Dataset(tmp_path, molecule="uracil", download=False)
        second = RevMD17Dataset(tmp_path, molecule="aspirin", download=False)
        assert first.source_id != second.source_id

    def test_carries_no_local_file_size(self, npz_root):
        """The old id embedded st_size and len(), so the same data cached under
        two ids whenever the file was re-downloaded."""
        src = RevMD17Dataset(npz_root, molecule="aspirin", download=False)
        assert "size=" not in src.source_id
        assert str(npz_root) not in src.source_id


class TestRevMD17TargetSchema:
    def test_energy_is_graph_level(self):
        assert "energy" in RevMD17Dataset.TARGET_SCHEMA.graph_level

    def test_forces_are_atom_level(self):
        assert "forces" in RevMD17Dataset.TARGET_SCHEMA.atom_level


class TestRevMD17Manifest:
    """The module's coordinate and its manifest must agree on the role names —
    nothing else in the tree checks that seam."""

    @pytest.fixture
    def manifest(self):
        return Manifest.from_path(_MANIFEST_PATH)

    def test_the_manifest_ships_at_the_coordinates_path(self):
        assert _MANIFEST_PATH.is_file()

    def test_every_molecule_has_a_role(self, manifest):
        assert set(_MOLECULES) <= set(manifest.artifacts)

    def test_each_role_serves_that_molecules_file(self, manifest):
        for molecule, filename in _MOLECULES.items():
            assert manifest.artifact(molecule).filename == filename

    def test_locators_pin_the_article_version(self, manifest):
        for molecule in _MOLECULES:
            locator = manifest.artifact(molecule).locators[0]
            assert locator.scheme == "figshare"
            assert locator.path.startswith("12672038/v4/")

    def test_digests_are_figshares_published_md5(self, manifest):
        for molecule in _MOLECULES:
            digest = manifest.artifact(molecule).digest
            assert digest is not None
            assert digest.algorithm == "md5"

    def test_records_the_version_doi(self, manifest):
        assert manifest.doi == "10.6084/m9.figshare.12672038.v4"

    def test_declares_the_sources_targets(self, manifest):
        assert manifest.targets.graph_level == ("energy",)
        assert manifest.targets.atom_level == ("forces",)
