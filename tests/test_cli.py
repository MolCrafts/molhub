"""Tests for the typer command line.

Run in-process through CliRunner rather than as a subprocess, so a failure
shows a Python traceback instead of an exit code.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from molhub.cli import app

runner = CliRunner()


@pytest.fixture
def idx(index_dir):
    return ["--index", str(index_dir)]


class TestSearch:
    def test_lists_matching_artifacts(self, idx):
        result = runner.invoke(app, ["search", "qm9", *idx])
        assert result.exit_code == 0
        assert "dataset:molcrafts/qm9@v2" in result.stdout

    def test_shows_the_title(self, idx):
        assert "QM9" in runner.invoke(app, ["search", *idx]).stdout

    def test_kind_filter(self, idx):
        result = runner.invoke(app, ["search", "--kind", "model", *idx])
        assert result.exit_code == 1

    def test_no_match_exits_nonzero(self, idx):
        assert runner.invoke(app, ["search", "nothing-like-it", *idx]).exit_code == 1

    def test_bare_search_lists_everything(self, idx):
        assert runner.invoke(app, ["search", *idx]).exit_code == 0


class TestInfo:
    def test_prints_the_coordinate(self, idx):
        result = runner.invoke(app, ["info", "qm9@v2", *idx])
        assert result.exit_code == 0
        assert "dataset:molcrafts/qm9@v2" in result.stdout

    def test_prints_license_and_citation(self, idx):
        out = runner.invoke(app, ["info", "qm9@v2", *idx]).stdout
        assert "CC0-1.0" in out
        assert "10.1038/sdata.2014.22" in out

    def test_prints_every_artifact_role(self, idx):
        out = runner.invoke(app, ["info", "qm9@v2", *idx]).stdout
        assert "[main]" in out and "[exclude]" in out

    def test_prints_the_digest_and_locators(self, idx):
        out = runner.invoke(app, ["info", "qm9@v2", *idx]).stdout
        assert "md5:" in out
        assert "fake://main-backup" in out

    def test_prints_declared_targets(self, idx):
        assert "U0" in runner.invoke(app, ["info", "qm9@v2", *idx]).stdout

    def test_unknown_coordinate_exits_nonzero(self, idx):
        assert runner.invoke(app, ["info", "qm9@v9", *idx]).exit_code == 1

    def test_malformed_coordinate_exits_nonzero(self, idx):
        assert runner.invoke(app, ["info", "qm9", *idx]).exit_code == 1


class TestFetch:
    @pytest.fixture(autouse=True)
    def offline_registry(self, monkeypatch, bodies, tmp_path):
        """Serve the fixture bytes through a fake driver; never touch the network."""
        from molhub.registry import BlobStore, Drivers, Fetcher

        from .test_registry.conftest import FakeRegistry

        real_init = Fetcher.__init__

        def _patched(self, *, drivers=None, blobs=None):
            real_init(
                self,
                drivers=drivers or Drivers.of(FakeRegistry(bodies=bodies)),
                blobs=blobs or BlobStore(root=tmp_path / "home"),
            )

        monkeypatch.setattr(Fetcher, "__init__", _patched)

    def test_reports_a_path_per_role(self, idx):
        result = runner.invoke(app, ["fetch", "qm9@v2", *idx])
        assert result.exit_code == 0
        assert "main\t" in result.stdout and "exclude\t" in result.stdout

    def test_into_copies_files_out_under_their_manifest_names(self, idx, tmp_path):
        target = tmp_path / "out"
        result = runner.invoke(app, ["fetch", "qm9@v2", "--into", str(target), *idx])
        assert result.exit_code == 0
        assert (target / "qm9.tar.bz2").exists()
        assert (target / "excluded.txt").exists()

    def test_unknown_coordinate_exits_nonzero(self, idx):
        assert runner.invoke(app, ["fetch", "qm9@v9", *idx]).exit_code == 1


class TestCacheVerify:
    """Verify re-checks cached files against the digests their manifests name."""

    def _cache(self, home, body: bytes) -> None:
        from molhub.registry import BlobStore

        path = BlobStore(root=home).path_for("dataset:molcrafts/qm9@v2/main")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def test_reports_an_empty_cache(self, idx, tmp_path):
        result = runner.invoke(app, ["cache", "verify", "--home", str(tmp_path), *idx])
        assert result.exit_code == 0
        assert "Nothing cached" in result.stdout

    def test_passes_on_an_intact_file(self, idx, tmp_path):
        from .conftest import MAIN_BODY

        self._cache(tmp_path, MAIN_BODY)
        result = runner.invoke(app, ["cache", "verify", "--home", str(tmp_path), *idx])
        assert result.exit_code == 0
        assert "0 stale" in result.stdout

    def test_detects_a_file_that_no_longer_matches(self, idx, tmp_path):
        self._cache(tmp_path, b"a different version")
        result = runner.invoke(app, ["cache", "verify", "--home", str(tmp_path), *idx])
        assert result.exit_code == 1
        assert "1 stale" in result.stdout

    def test_counts_files_whose_manifest_has_no_digest(self, tmp_path, index_dir):
        """Nothing published means nothing to check — say so, do not pretend."""
        manifest = index_dir / "dataset" / "molcrafts" / "qm9" / "v2.yaml"
        manifest.write_text(
            "\n".join(line for line in manifest.read_text().splitlines() if "digest:" not in line)
        )
        self._cache(tmp_path, b"anything at all")
        result = runner.invoke(
            app, ["cache", "verify", "--home", str(tmp_path), "--index", str(index_dir)]
        )
        assert result.exit_code == 0
        assert "1 without a published digest" in result.stdout


class TestBrokenIndex:
    def test_a_malformed_manifest_is_a_clean_error(self, tmp_path):
        bad = tmp_path / "dataset" / "molcrafts" / "x" / "1.yaml"
        bad.parent.mkdir(parents=True)
        bad.write_text("schema_version: 1\n")
        result = runner.invoke(app, ["search", "--index", str(tmp_path)])
        assert result.exit_code != 0
        assert "Traceback" not in result.stdout
