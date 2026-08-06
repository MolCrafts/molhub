"""Tests for the typer command line.

Run in-process through CliRunner rather than as a subprocess, so a failure
shows a Python traceback instead of an exit code.
"""

from __future__ import annotations

import hashlib

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
        assert "sha256:" in out
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
    def test_reports_an_empty_cache(self, tmp_path):
        result = runner.invoke(app, ["cache", "verify", "--home", str(tmp_path)])
        assert result.exit_code == 0
        assert "No cached blobs" in result.stdout

    def test_passes_on_an_intact_blob(self, tmp_path):
        body = b"intact"
        digest = hashlib.sha256(body).hexdigest()
        blob = tmp_path / "blobs" / "sha256" / digest[:2] / digest
        blob.parent.mkdir(parents=True)
        blob.write_bytes(body)
        result = runner.invoke(app, ["cache", "verify", "--home", str(tmp_path)])
        assert result.exit_code == 0
        assert "0 corrupt" in result.stdout

    def test_detects_a_corrupted_blob(self, tmp_path):
        digest = hashlib.sha256(b"intact").hexdigest()
        blob = tmp_path / "blobs" / "sha256" / digest[:2] / digest
        blob.parent.mkdir(parents=True)
        blob.write_bytes(b"tampered")
        result = runner.invoke(app, ["cache", "verify", "--home", str(tmp_path)])
        assert result.exit_code == 1
        assert "1 corrupt" in result.stdout


class TestBrokenIndex:
    def test_a_malformed_manifest_is_a_clean_error(self, tmp_path):
        bad = tmp_path / "dataset" / "molcrafts" / "x" / "1.yaml"
        bad.parent.mkdir(parents=True)
        bad.write_text("schema_version: 1\n")
        result = runner.invoke(app, ["search", "--index", str(tmp_path)])
        assert result.exit_code != 0
        assert "Traceback" not in result.stdout
