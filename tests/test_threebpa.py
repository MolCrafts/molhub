"""Tests for the 3BPA dataset source (uses local temp files)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from molhub.dataset import MapDataset, ThreeBPASource

# A minimal valid extended-XYZ file with two methane-like structures.
_SAMPLE_EXTXYZ = """5
energy=-40.50
C  0.000 0.000 0.000 0.01 0.00 -0.01
H  0.630 0.630 0.630 0.00 0.01 0.00
H -0.630 -0.630 0.630 -0.01 0.00 0.00
H  0.630 -0.630 -0.630 0.00 -0.01 0.00
H -0.630 0.630 -0.630 0.00 0.00 0.01
5
energy=-40.45
C  0.001 0.001 0.001 0.00 0.00 0.00
H  0.631 0.631 0.631 0.01 0.00 0.00
H -0.629 -0.629 0.631 0.00 -0.01 0.00
H  0.631 -0.629 -0.629 0.00 0.00 0.01
H -0.629 0.631 -0.629 0.00 0.00 -0.01
"""


@pytest.fixture
def sample_xyz_path():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xyz", delete=False) as f:
        f.write(_SAMPLE_EXTXYZ)
    yield Path(f.name)
    f.name and Path(f.name).unlink(missing_ok=True)


class TestThreeBPASource:
    def test_parse_and_len(self, sample_xyz_path):
        src = ThreeBPASource(sample_xyz_path, tag="test")
        assert len(src) == 2
        assert isinstance(src, MapDataset)

    def test_atoms_block(self, sample_xyz_path):
        src = ThreeBPASource(sample_xyz_path, tag="test")
        frame = src[0]
        atoms = frame["atoms"]
        assert "element" in atoms
        assert "x" in atoms
        assert "y" in atoms
        assert "z" in atoms
        assert "number" in atoms
        assert "fx" in atoms
        assert "fy" in atoms
        assert "fz" in atoms

    def test_natoms(self, sample_xyz_path):
        src = ThreeBPASource(sample_xyz_path, tag="test")
        # CH4 = 5 atoms
        assert src[0]["atoms"].nrows == 5
        assert src[1]["atoms"].nrows == 5

    def test_element_dtype(self, sample_xyz_path):
        src = ThreeBPASource(sample_xyz_path, tag="test")
        elem = src[0]["atoms"]["element"]
        assert elem.dtype.kind == "U"

    def test_number_dtype(self, sample_xyz_path):
        src = ThreeBPASource(sample_xyz_path, tag="test")
        num = src[0]["atoms"]["number"]
        assert np.issubdtype(num.dtype, np.integer)

    def test_coord_dtype(self, sample_xyz_path):
        src = ThreeBPASource(sample_xyz_path, tag="test")
        assert src[0]["atoms"]["x"].dtype == np.float64
        assert src[0]["atoms"]["y"].dtype == np.float64
        assert src[0]["atoms"]["z"].dtype == np.float64

    def test_energy_in_metadata(self, sample_xyz_path):
        src = ThreeBPASource(sample_xyz_path, tag="test")
        assert src[0].metadata["energy"] == pytest.approx(-40.50)
        assert src[1].metadata["energy"] == pytest.approx(-40.45)

    def test_forces_shape(self, sample_xyz_path):
        src = ThreeBPASource(sample_xyz_path, tag="test")
        fx = src[0]["atoms"]["fx"]
        fy = src[0]["atoms"]["fy"]
        fz = src[0]["atoms"]["fz"]
        assert fx.shape == (5,)
        assert fy.shape == (5,)
        assert fz.shape == (5,)

    def test_source_id(self, sample_xyz_path):
        src = ThreeBPASource(sample_xyz_path, tag="train_300K")
        assert src.source_id.startswith("3bpa:train_300K")

    def test_target_schema(self, sample_xyz_path):
        src = ThreeBPASource(sample_xyz_path, tag="test")
        assert "energy" in src.TARGET_SCHEMA.graph_level
        assert "forces" in src.TARGET_SCHEMA.atom_level

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            ThreeBPASource("/nonexistent/path.xyz", tag="test")

    def test_missing_energy_tag_raises(self):
        bad_xyz = """2
no energy here
H 0 0 0 0 0 0
H 1 0 0 0 0 0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xyz", delete=False) as f:
            f.write(bad_xyz)
        path = Path(f.name)
        try:
            with pytest.raises(ValueError, match="Missing 'energy=...' tag"):
                ThreeBPASource(path, tag="test")
        finally:
            path.unlink(missing_ok=True)
