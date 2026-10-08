"""Tests for the 3BPA source — parsing, and retrieval by coordinate.

Every test here is offline. The hub is injected as a fake at the source's one
seam, so nothing in this file resolves a registry, selects a driver, or opens a
socket. The single test that does talk to GitHub is marked ``network`` and is
deselected by default.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from molhub.coordinate import Coordinate
from molhub.dataset import ArtifactHub, MapDataset, ThreeBPADataset
from molhub.dataset.threebpa import COORDINATE

# Two structures in the shape the real files use: seven columns per atom
# (species, x, y, z, fx, fy, fz) and an ``energy=`` token in a comment line
# that also carries Lattice/Properties tokens containing spaces.
_SAMPLE_EXTXYZ = """5
Lattice="50.0 0.0 0.0 0.0 50.0 0.0 0.0 0.0 50.0" \
Properties=species:S:1:pos:R:3:forces:R:3 energy=-40.50 pbc="F F F"
C  0.000 0.000 0.000 0.01 0.00 -0.01
H  0.630 0.630 0.630 0.00 0.01 0.00
H -0.630 -0.630 0.630 -0.01 0.00 0.00
H  0.630 -0.630 -0.630 0.00 -0.01 0.00
H -0.630 0.630 -0.630 0.00 0.00 0.01
5
Properties=species:S:1:pos:R:3:forces:R:3 energy=-40.45
C  0.001 0.001 0.001 0.00 0.00 0.00
H  0.631 0.631 0.631 0.01 0.00 0.00
H -0.629 -0.629 0.631 0.00 -0.01 0.00
H  0.631 -0.629 -0.629 0.00 0.00 0.01
H -0.629 0.631 -0.629 0.00 0.00 -0.01
"""


class FakeHub:
    """An :class:`~molhub.dataset.hub.ArtifactHub` serving files already on disk.

    Records what was asked for, so the retrieval path can be exercised with no
    registry, no driver, and no network.
    """

    def __init__(self, paths: dict[str, Path]) -> None:
        self._paths = paths
        self.calls: list[tuple[str, list[str] | None]] = []

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        self.calls.append((coordinate, roles))
        wanted = list(self._paths) if roles is None else roles
        return {role: self._paths[role] for role in wanted}


@pytest.fixture
def sample_xyz_path(tmp_path) -> Path:
    """A local 3BPA-shaped file, as a user who downloaded one would have."""
    path = tmp_path / "train_300K.xyz"
    path.write_text(_SAMPLE_EXTXYZ, encoding="utf-8")
    return path


class TestThreeBPADataset:
    # -- parsing a local file ------------------------------------------------

    def test_parse_and_len(self, sample_xyz_path):
        assert len(ThreeBPADataset(sample_xyz_path, tag="train_300K")) == 2

    def test_is_map_dataset(self, sample_xyz_path):
        assert isinstance(ThreeBPADataset(sample_xyz_path, tag="train_300K"), MapDataset)

    def test_atoms_block(self, sample_xyz_path):
        atoms = ThreeBPADataset(sample_xyz_path, tag="train_300K")[0]["atoms"]
        for column in ("element", "x", "y", "z", "number", "fx", "fy", "fz"):
            assert column in atoms

    def test_natoms(self, sample_xyz_path):
        src = ThreeBPADataset(sample_xyz_path, tag="train_300K")
        assert src[0]["atoms"].n_rows == 5
        assert src[1]["atoms"].n_rows == 5

    def test_element_dtype(self, sample_xyz_path):
        elem = ThreeBPADataset(sample_xyz_path, tag="train_300K")[0]["atoms"]["element"]
        assert elem.dtype.kind == "U"

    def test_atomic_numbers(self, sample_xyz_path):
        atoms = ThreeBPADataset(sample_xyz_path, tag="train_300K")[0]["atoms"]
        assert list(atoms["number"]) == [6, 1, 1, 1, 1]

    def test_number_dtype(self, sample_xyz_path):
        num = ThreeBPADataset(sample_xyz_path, tag="train_300K")[0]["atoms"]["number"]
        assert np.issubdtype(num.dtype, np.integer)

    def test_coord_dtype(self, sample_xyz_path):
        atoms = ThreeBPADataset(sample_xyz_path, tag="train_300K")[0]["atoms"]
        assert atoms["x"].dtype == np.float64
        assert atoms["y"].dtype == np.float64
        assert atoms["z"].dtype == np.float64

    def test_energy_in_metadata(self, sample_xyz_path):
        src = ThreeBPADataset(sample_xyz_path, tag="train_300K")
        assert src[0].meta["energy"] == pytest.approx(-40.50)
        assert src[1].meta["energy"] == pytest.approx(-40.45)

    def test_lattice_token_is_not_mistaken_for_the_energy(self, sample_xyz_path):
        """``Lattice="…"`` splits into bare numeric tokens; only ``energy=`` counts."""
        assert ThreeBPADataset(sample_xyz_path, tag="train_300K")[0].meta == {
            "energy": pytest.approx(-40.50)
        }

    def test_forces_shape(self, sample_xyz_path):
        atoms = ThreeBPADataset(sample_xyz_path, tag="train_300K")[0]["atoms"]
        assert atoms["fx"].shape == (5,)
        assert atoms["fy"].shape == (5,)
        assert atoms["fz"].shape == (5,)

    def test_index_out_of_range(self, sample_xyz_path):
        with pytest.raises(IndexError):
            ThreeBPADataset(sample_xyz_path, tag="train_300K")[5]

    def test_target_schema(self, sample_xyz_path):
        src = ThreeBPADataset(sample_xyz_path, tag="train_300K")
        assert "energy" in src.TARGET_SCHEMA.graph_level
        assert "forces" in src.TARGET_SCHEMA.atom_level

    def test_missing_energy_tag_raises(self, tmp_path):
        path = tmp_path / "bad.xyz"
        path.write_text("2\nno energy here\nH 0 0 0 0 0 0\nH 1 0 0 0 0 0\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Missing 'energy=...' tag"):
            ThreeBPADataset(path, tag="train_300K")

    # -- the four splits -----------------------------------------------------

    def test_splits_are_the_four_benchmark_files(self):
        assert ThreeBPADataset.SPLITS == frozenset(
            {"train_300K", "test_300K", "test_600K", "test_1200K"}
        )

    # -- source_id -----------------------------------------------------------

    def test_source_id_names_the_coordinate_and_the_split(self, sample_xyz_path):
        src = ThreeBPADataset(sample_xyz_path, tag="train_300K")
        assert src.source_id == "dataset:molcrafts/3bpa@v1#split=train_300K"

    def test_source_id_distinguishes_splits(self, sample_xyz_path):
        train = ThreeBPADataset(sample_xyz_path, tag="train_300K")
        test = ThreeBPADataset(sample_xyz_path, tag="test_600K")
        assert train.source_id != test.source_id

    def test_source_id_prefix_is_a_parseable_coordinate(self, sample_xyz_path):
        """Everything before ``#`` round-trips through :meth:`Coordinate.parse`."""
        bare = ThreeBPADataset(sample_xyz_path, tag="train_300K").source_id.split("#", 1)[0]
        assert Coordinate.parse(bare).canonical == bare == COORDINATE

    def test_source_id_carries_no_local_details(self, sample_xyz_path):
        """It named the byte size and frame count, which made it unaddressable."""
        source_id = ThreeBPADataset(sample_xyz_path, tag="train_300K").source_id
        assert "size=" not in source_id
        assert "n=" not in source_id

    # -- retrieval by coordinate --------------------------------------------

    def test_the_fake_still_matches_the_seam_it_stands_in_for(self):
        """A fake that drifts from the protocol proves nothing about the source."""
        assert isinstance(FakeHub({}), ArtifactHub)

    def test_absent_file_is_fetched_by_coordinate(self, tmp_path, sample_xyz_path):
        hub = FakeHub({"train_300K": sample_xyz_path})
        src = ThreeBPADataset(tmp_path / "not-here.xyz", tag="train_300K", hub=hub)
        assert len(src) == 2

    def test_fetch_asks_for_the_canonical_coordinate(self, tmp_path, sample_xyz_path):
        hub = FakeHub({"train_300K": sample_xyz_path})
        ThreeBPADataset(tmp_path / "not-here.xyz", tag="train_300K", hub=hub)
        assert hub.calls == [(COORDINATE, ["train_300K"])]

    def test_fetch_asks_only_for_the_tagged_role(self, tmp_path, sample_xyz_path):
        """Fetching all four would pull ~19 MB to read one split."""
        hub = FakeHub({"test_600K": sample_xyz_path})
        ThreeBPADataset(tmp_path / "not-here.xyz", tag="test_600K", hub=hub)
        assert hub.calls[0][1] == ["test_600K"]

    def test_path_points_at_the_fetched_file(self, tmp_path, sample_xyz_path):
        hub = FakeHub({"train_300K": sample_xyz_path})
        src = ThreeBPADataset(tmp_path / "not-here.xyz", tag="train_300K", hub=hub)
        assert src.path == sample_xyz_path

    def test_present_file_is_used_without_the_hub(self, sample_xyz_path):
        hub = FakeHub({})
        ThreeBPADataset(sample_xyz_path, tag="train_300K", hub=hub)
        assert hub.calls == []

    def test_zero_byte_file_is_treated_as_absent(self, tmp_path, sample_xyz_path):
        """An interrupted download used to parse as a silently empty dataset."""
        stub = tmp_path / "interrupted" / "train_300K.xyz"
        stub.parent.mkdir()
        stub.write_bytes(b"")
        hub = FakeHub({"train_300K": sample_xyz_path})
        assert len(ThreeBPADataset(stub, tag="train_300K", hub=hub)) == 2

    def test_absent_file_with_an_unknown_tag_raises(self, tmp_path):
        hub = FakeHub({})
        with pytest.raises(FileNotFoundError, match="not one of the 3BPA splits"):
            ThreeBPADataset(tmp_path / "not-here.xyz", tag="whatever", hub=hub)

    def test_unknown_tag_error_lists_the_splits(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="test_1200K"):
            ThreeBPADataset(tmp_path / "not-here.xyz", tag="whatever", hub=FakeHub({}))

    def test_unknown_tag_is_fine_when_the_file_exists(self, sample_xyz_path):
        """A user pointing at their own extended-XYZ file keeps working."""
        assert len(ThreeBPADataset(sample_xyz_path, tag="my-own-split")) == 2
