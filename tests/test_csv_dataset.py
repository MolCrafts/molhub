"""Tests for CSVDataset — local CSV parsing and Frame output."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from molpy.core.frame import Frame

from molhub.dataset import CSVDataset, MapDataset

_SAMPLE_CSV = """PSMILES,labels.Exp_Tg(K),meta.source,meta.reliability
*C#Cc1cccc(C#C[SiH2]*)c1,345.15,GREA,black
*C#Cc1cccc(C#C[SiH](*)c2ccccc2)c1,358.15,GREA,black
*C#Cc1ccccc1C#C[SiH](*)c1ccccc1,344.15,GREA,black
*/C(=C(/*)c1ccc(C(C)(C)C)cc1)c1ccccc1,473.15,GREA,black
*/C(=C(/*)c1ccc(CCCC)cc1)c1ccccc1,473.15,GREA,black
"""


@pytest.fixture
def sample_csv_path():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(_SAMPLE_CSV)
    yield Path(f.name)
    f.name and Path(f.name).unlink(missing_ok=True)


class TestCSVDataset:
    def test_len(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        assert len(ds) == 5

    def test_is_map_dataset(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        assert isinstance(ds, MapDataset)

    def test_getitem_returns_frame(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        frame = ds[0]
        assert isinstance(frame, Frame)

    def test_metadata_contains_columns(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        frame = ds[0]
        assert "PSMILES" in frame.metadata
        assert "labels.Exp_Tg(K)" in frame.metadata
        assert "meta.source" in frame.metadata
        assert "meta.reliability" in frame.metadata

    def test_numeric_inference(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        frame = ds[0]
        # Tg value should be inferred as float
        assert isinstance(frame.metadata["labels.Exp_Tg(K)"], float)
        assert frame.metadata["labels.Exp_Tg(K)"] == pytest.approx(345.15)

    def test_string_columns_remain_string(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        frame = ds[0]
        assert isinstance(frame.metadata["PSMILES"], str)
        assert isinstance(frame.metadata["meta.reliability"], str)
        assert frame.metadata["meta.reliability"] == "black"

    def test_all_rows_accessible(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        tgs = [ds[i].metadata["labels.Exp_Tg(K)"] for i in range(len(ds))]
        assert tgs == pytest.approx([345.15, 358.15, 344.15, 473.15, 473.15])

    def test_headers(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        assert ds.headers == [
            "PSMILES",
            "labels.Exp_Tg(K)",
            "meta.source",
            "meta.reliability",
        ]

    def test_source_id(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        assert ds.source_id.startswith("csv:")

    def test_path(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        assert ds.path.samefile(sample_csv_path)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            CSVDataset("/nonexistent/data.csv")

    def test_download_path_from_url(self, tmp_path):
        """_filename_from_url and cache path resolution with explicit cache_dir."""
        dest = CSVDataset._resolve_cache_path_static(
            "https://example.com/test.csv",
            cache_dir=tmp_path,
        )
        assert dest == tmp_path / "test.csv"

    def test_empty_csv(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("")
        ds = CSVDataset(str(p))
        assert len(ds) == 0
        assert ds.headers == []
