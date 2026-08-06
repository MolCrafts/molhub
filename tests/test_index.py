"""Tests for index source resolution and lookup."""

from __future__ import annotations

import pytest

from molhub.index import Index, IndexSource, UnknownArtifact
from molhub.manifest import InvalidManifest

from .conftest import manifest_yaml


class TestIndexSourceResolution:
    def test_explicit_path_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_INDEX", str(tmp_path / "env"))
        assert IndexSource.resolve(tmp_path / "explicit").root == tmp_path / "explicit"

    def test_env_var_is_used_next(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_INDEX", str(tmp_path / "env"))
        assert IndexSource.resolve().root == tmp_path / "env"

    def test_falls_back_to_the_bundled_snapshot(self, monkeypatch):
        """A fresh install resolves the built-ins with no network and no config."""
        monkeypatch.delenv("MOLHUB_INDEX", raising=False)
        assert IndexSource.resolve().root.name == "index_data"

    def test_tilde_is_expanded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_INDEX", "~/idx")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert IndexSource.resolve().root == tmp_path / "idx"

    def test_path_for_follows_the_layout(self, tmp_path):
        from molhub.coordinate import Coordinate

        source = IndexSource(tmp_path)
        expected = tmp_path / "dataset" / "molcrafts" / "qm9" / "v2.yaml"
        assert source.path_for(Coordinate.parse("qm9@v2")) == expected

    def test_missing_directory_yields_no_manifests(self, tmp_path):
        assert list(IndexSource(tmp_path / "absent").manifest_paths()) == []


class TestIndexLoading:
    def test_loads_a_manifest(self, index_dir):
        assert len(Index.load(index_dir)) == 1

    def test_empty_source_gives_an_empty_index(self, tmp_path):
        assert len(Index.load(tmp_path / "absent")) == 0

    def test_a_broken_manifest_fails_loudly(self, index_dir):
        """Skipping a bad entry would silently hide a dataset; worse than failing."""
        (index_dir / "dataset" / "molcrafts" / "bad" / "v1.yaml").parent.mkdir(parents=True)
        (index_dir / "dataset" / "molcrafts" / "bad" / "v1.yaml").write_text("schema_version: 1\n")
        with pytest.raises(InvalidManifest):
            Index.load(index_dir)

    def test_load_accepts_an_index_source(self, index_dir):
        assert len(Index.load(IndexSource(index_dir))) == 1

    def test_load_uses_the_env_var_when_given_nothing(self, index_dir, monkeypatch):
        monkeypatch.setenv("MOLHUB_INDEX", str(index_dir))
        assert len(Index.load()) == 1


class TestIndexLookup:
    @pytest.fixture
    def index(self, index_dir):
        return Index.load(index_dir)

    def test_get_by_full_coordinate(self, index):
        assert index.get("dataset:molcrafts/qm9@v2").coordinate.name == "qm9"

    def test_get_by_shorthand(self, index):
        assert index.get("qm9@v2").coordinate.name == "qm9"

    def test_contains(self, index):
        assert "qm9@v2" in index
        assert "qm9@v9" not in index

    def test_contains_tolerates_a_malformed_coordinate(self, index):
        assert "not a coordinate" not in index

    def test_unknown_coordinate_raises(self, index):
        with pytest.raises(UnknownArtifact):
            index.get("qm9@v9")

    def test_unknown_version_suggests_the_ones_that_exist(self, index):
        """A stale version pin is the likeliest cause, so say what is available."""
        with pytest.raises(UnknownArtifact, match="v2"):
            index.get("qm9@v9")

    def test_unknown_artifact_reports_the_index_size(self, index):
        with pytest.raises(UnknownArtifact, match="1 artifacts"):
            index.get("nothing-like-it@v1")


class TestIndexSearch:
    @pytest.fixture
    def index(self, tmp_path):
        root = tmp_path / "index"
        for kind, name, version in [
            ("dataset", "qm9", "v2"),
            ("dataset", "revmd17-aspirin", "v1"),
            ("model", "mace-mp-0", "1.0"),
        ]:
            path = root / kind / "molcrafts" / name / f"{version}.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(manifest_yaml(kind=kind, name=name, version=version))
        return Index.load(root)

    def test_no_filter_returns_everything(self, index):
        assert len(index.search()) == 3

    def test_kind_filter(self, index):
        assert {m.coordinate.kind for m in index.search(kind="dataset")} == {"dataset"}

    def test_query_filter(self, index):
        assert [m.coordinate.name for m in index.search(query="revmd17")] == ["revmd17-aspirin"]

    def test_query_is_case_insensitive(self, index):
        assert index.search(query="REVMD17")

    def test_combined_filters(self, index):
        assert index.search(kind="model", query="mace")

    def test_contradictory_filters_return_nothing(self, index):
        assert index.search(kind="plugin", query="mace") == []

    def test_results_are_ordered_by_coordinate(self, index):
        found = [m.coordinate.canonical for m in index.search()]
        assert found == sorted(found)

    def test_iteration_matches_unfiltered_search(self, index):
        assert list(index) == index.search()
