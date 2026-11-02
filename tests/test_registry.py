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

    def test_unset_env_has_no_yaml_directory(self, monkeypatch):
        """The package catalog is Python; there is no bundled YAML tree."""
        monkeypatch.delenv("MOLHUB_REGISTRY", raising=False)
        with pytest.raises(FileNotFoundError, match="Registry.builtin"):
            RegistrySource.resolve()

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
        (registry_dir / "dataset" / "molcrafts" / "bad" / "v1.yaml").write_text("kind: dataset\n")
        with pytest.raises(InvalidManifest):
            Registry.load(registry_dir)

    def test_load_accepts_a_registry_source(self, registry_dir):
        assert len(Registry.load(RegistrySource(registry_dir))) == 1

    def test_load_uses_the_env_var_when_given_nothing(self, registry_dir, monkeypatch):
        monkeypatch.setenv("MOLHUB_REGISTRY", str(registry_dir))
        assert len(Registry.load()) == 1

    def test_load_without_env_uses_the_python_catalog(self, monkeypatch):
        monkeypatch.delenv("MOLHUB_REGISTRY", raising=False)
        registry = Registry.load()
        assert "dataset:molcrafts/qm9@v2" in registry
        assert len(registry) >= 1


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

    def test_versions_lists_declared_versions_for_an_unversioned_name(self, registry):
        """The sibling scan ``_not_found_message`` already does, said out loud.

        ``hf-facade-03-builder-info`` needs it on the way in, not only in an
        error message on the way out: defaulting a ``revision`` means asking
        which versions exist. Promoted rather than duplicated, so the suggestion
        in an :class:`UnknownArtifact` and the loader's default always agree.
        """
        assert list(registry.versions("dataset:molcrafts/qm9")) == ["v2"]

    def test_versions_lists_every_declared_version_of_one_artifact(self, tmp_path):
        root = tmp_path / "registry"
        for version in ("v2", "v3"):
            path = root / "dataset" / "molcrafts" / "qm9" / f"{version}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(manifest_yaml(version=version), encoding="utf-8")
        assert list(Registry.load(root).versions("dataset:molcrafts/qm9")) == ["v2", "v3"]


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
