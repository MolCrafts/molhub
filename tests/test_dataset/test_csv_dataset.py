"""Tests for CSVDataset — local CSV parsing and Frame output."""

from __future__ import annotations

import tempfile
import urllib.request
from pathlib import Path

import pytest
from molpy import Frame

from molhub.dataset import CSVDataset, MapDataset, Targets
from molhub.dataset.csv_dataset import _infer_value

from ..test_sources.conftest import FakeResponse

_SAMPLE_CSV = """PSMILES,labels.Exp_Tg(K),meta.source,meta.reliability
*C#Cc1cccc(C#C[SiH2]*)c1,345.15,GREA,black
*C#Cc1cccc(C#C[SiH](*)c2ccccc2)c1,358.15,GREA,black
*C#Cc1ccccc1C#C[SiH](*)c1ccccc1,344.15,GREA,black
*/C(=C(/*)c1ccc(C(C)(C)C)cc1)c1ccccc1,473.15,GREA,black
*/C(=C(/*)c1ccc(CCCC)cc1)c1ccccc1,473.15,GREA,black
"""


@pytest.fixture
def sample_csv_path():
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".csv", delete=False) as f:
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
        meta = Targets(ds[0]).read()
        assert "PSMILES" in meta
        assert "labels.Exp_Tg(K)" in meta
        assert "meta.source" in meta
        assert "meta.reliability" in meta

    def test_numeric_inference(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        meta = Targets(ds[0]).read()
        # Tg value should be inferred as float
        assert isinstance(meta["labels.Exp_Tg(K)"], float)
        assert meta["labels.Exp_Tg(K)"] == pytest.approx(345.15)

    def test_string_columns_remain_string(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        meta = Targets(ds[0]).read()
        assert isinstance(meta["PSMILES"], str)
        assert isinstance(meta["meta.reliability"], str)
        assert meta["meta.reliability"] == "black"

    def test_all_rows_accessible(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        tgs = [Targets(ds[i]).read()["labels.Exp_Tg(K)"] for i in range(len(ds))]
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

    def test_source_id_is_not_a_coordinate(self, sample_csv_path):
        """A raw path or URL has no coordinate — source_id must not fake one."""
        ds = CSVDataset(str(sample_csv_path))
        assert "@" not in ds.source_id

    def test_path(self, sample_csv_path):
        ds = CSVDataset(str(sample_csv_path))
        assert ds.path.samefile(sample_csv_path)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            CSVDataset("/nonexistent/data.csv")

    def test_empty_csv(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("", encoding="utf-8")
        ds = CSVDataset(str(p))
        assert len(ds) == 0
        assert ds.headers == []


class TestInferValue:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("42", 42), ("-7", -7), ("3.5", 3.5), ("1e3", 1000.0)],
    )
    def test_numeric_strings(self, raw, expected):
        assert _infer_value(raw) == pytest.approx(expected)

    def test_int_stays_int(self):
        assert isinstance(_infer_value("42"), int)

    @pytest.mark.parametrize("raw", ["abc", "C#Cc1ccccc1", ""])
    def test_non_numeric_stays_string(self, raw):
        assert isinstance(_infer_value(raw), str)

    def test_surrounding_whitespace_is_stripped(self):
        assert _infer_value("  3.5  ") == pytest.approx(3.5)


class TestRemoteCsv:
    def test_url_with_download_disabled_and_no_cache_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path))
        with pytest.raises(FileNotFoundError):
            CSVDataset("https://example.invalid/missing.csv", download=False)

    def test_url_is_downloaded_then_parsed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path))
        body = b"a,b\n1,x\n2,y\n"
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, body))
        ds = CSVDataset("https://example.invalid/remote.csv")
        assert len(ds) == 2
        assert ds.headers == ["a", "b"]
        assert Targets(ds[1]).read()["a"] == 2

    def test_download_honours_molhub_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path))
        monkeypatch.setenv("MOLHUB_CACHE_DIR", str(tmp_path / "legacy"))
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"a\n1\n"))
        ds = CSVDataset("https://example.invalid/remote.csv")
        assert ds.path == tmp_path / "urls" / "remote.csv"

    def test_download_never_writes_into_the_shared_files_tree(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path))
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"a\n1\n"))
        CSVDataset("https://example.invalid/remote.csv")
        assert not (tmp_path / "files").exists()

    def test_download_classmethod_skips_existing_file(self, tmp_path, monkeypatch):
        cached = tmp_path / "urls" / "keep.csv"
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text("already,here\n", encoding="utf-8")

        def _boom(*a, **k):
            raise AssertionError("should not re-download a cached file")

        monkeypatch.setattr(urllib.request, "urlopen", _boom)
        got = CSVDataset.download("https://example.invalid/keep.csv", cache_dir=tmp_path)
        assert got == cached
        assert got.read_text(encoding="utf-8") == "already,here\n"
