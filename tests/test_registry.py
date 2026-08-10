"""Tests for registry source resolution and lookup."""

from __future__ import annotations

import pytest

from molhub.manifest import InvalidManifest
from molhub.registry import Registry, RegistrySource, UnknownArtifact

from .conftest import manifest_yaml


class TestRegistrySourceResolution:
    def test_explicit_path_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_REGISTRY", str(tmp_path / "env"))
        assert RegistrySource.resolve(tmp_path / "explicit").root == tmp_path / "explicit"

    def test_env_var_is_used_next(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_REGISTRY", str(tmp_path / "env"))
        assert RegistrySource.resolve().root == tmp_path / "env"

    def test_falls_back_to_the_bundled_snapshot(self, monkeypatch):
        """A fresh install resolves the built-ins with no network and no config."""
        monkeypatch.delenv("MOLHUB_REGISTRY", raising=False)
        assert RegistrySource.resolve().root.name == "registry_data"

    def test_tilde_is_expanded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_REGISTRY", "~/idx")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert RegistrySource.resolve().root == tmp_path / "idx"

    def test_path_for_follows_the_layout(self, tmp_path):
        from molhub.coordinate import Coordinate

        source = RegistrySource(tmp_path)
        expected = tmp_path / "dataset" / "molcrafts" / "qm9" / "v2.yaml"
        assert source.path_for(Coordinate.parse("qm9@v2")) == expected

    def test_missing_directory_yields_no_manifests(self, tmp_path):
        assert list(RegistrySource(tmp_path / "absent").manifest_paths()) == []


class TestRegistryLoading:
    def test_loads_a_manifest(self, registry_dir):
        assert len(Registry.load(registry_dir)) == 1

    def test_empty_source_gives_an_empty_registry(self, tmp_path):
        assert len(Registry.load(tmp_path / "absent")) == 0

    def test_a_broken_manifest_fails_loudly(self, registry_dir):
        """Skipping a bad entry would silently hide a dataset; worse than failing."""
        (registry_dir / "dataset" / "molcrafts" / "bad" / "v1.yaml").parent.mkdir(parents=True)
        (registry_dir / "dataset" / "molcrafts" / "bad" / "v1.yaml").write_text(
            "schema_version: 1\n"
        )
        with pytest.raises(InvalidManifest):
            Registry.load(registry_dir)

    def test_load_accepts_a_registry_source(self, registry_dir):
        assert len(Registry.load(RegistrySource(registry_dir))) == 1

    def test_load_uses_the_env_var_when_given_nothing(self, registry_dir, monkeypatch):
        monkeypatch.setenv("MOLHUB_REGISTRY", str(registry_dir))
        assert len(Registry.load()) == 1


class TestRegistryLookup:
    @pytest.fixture
    def registry(self, registry_dir):
        return Registry.load(registry_dir)

    def test_get_by_full_coordinate(self, registry):
        assert registry.get("dataset:molcrafts/qm9@v2").coordinate.name == "qm9"

    def test_get_by_shorthand(self, registry):
        assert registry.get("qm9@v2").coordinate.name == "qm9"

    def test_contains(self, registry):
        assert "qm9@v2" in registry
        assert "qm9@v9" not in registry

    def test_contains_tolerates_a_malformed_coordinate(self, registry):
        assert "not a coordinate" not in registry

    def test_unknown_coordinate_raises(self, registry):
        with pytest.raises(UnknownArtifact):
            registry.get("qm9@v9")

    def test_unknown_version_suggests_the_ones_that_exist(self, registry):
        """A stale version pin is the likeliest cause, so say what is available."""
        with pytest.raises(UnknownArtifact, match="v2"):
            registry.get("qm9@v9")

    def test_unknown_artifact_reports_the_registry_size(self, registry):
        with pytest.raises(UnknownArtifact, match="1 artifacts"):
            registry.get("nothing-like-it@v1")


class TestRegistrySearch:
    @pytest.fixture
    def registry(self, tmp_path):
        root = tmp_path / "registry"
        for kind, name, version in [
            ("dataset", "qm9", "v2"),
            ("dataset", "revmd17-aspirin", "v1"),
            ("model", "mace-mp-0", "1.0"),
        ]:
            path = root / kind / "molcrafts" / name / f"{version}.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(manifest_yaml(kind=kind, name=name, version=version))
        return Registry.load(root)

    def test_no_filter_returns_everything(self, registry):
        assert len(registry.search()) == 3

    def test_kind_filter(self, registry):
        assert {m.coordinate.kind for m in registry.search(kind="dataset")} == {"dataset"}

    def test_query_filter(self, registry):
        assert [m.coordinate.name for m in registry.search(query="revmd17")] == ["revmd17-aspirin"]

    def test_query_is_case_insensitive(self, registry):
        assert registry.search(query="REVMD17")

    def test_combined_filters(self, registry):
        assert registry.search(kind="model", query="mace")

    def test_contradictory_filters_return_nothing(self, registry):
        assert registry.search(kind="plugin", query="mace") == []

    def test_results_are_ordered_by_coordinate(self, registry):
        found = [m.coordinate.canonical for m in registry.search()]
        assert found == sorted(found)

    def test_iteration_matches_unfiltered_search(self, registry):
        assert list(registry) == registry.search()
