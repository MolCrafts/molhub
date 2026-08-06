"""The bundled index must be loadable, schema-valid, and actually resolvable.

Everything here is offline. The one test that would touch Zenodo is marked
``network`` and deselected by default — CI must not go red because a data
repository is having a slow morning.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import molhub
from molhub import Molhub
from molhub.index import Index, IndexSource
from molhub.manifest import Manifest

BUNDLED = Path(molhub.__file__).parent / "index_data"
SCHEMA = Path(molhub.__file__).parent / "schema" / "manifest.schema.yaml"


class TestBundledIndexIsUsable:
    def test_it_ships(self):
        assert BUNDLED.is_dir()

    def test_every_manifest_parses(self):
        for path in IndexSource(BUNDLED).manifest_paths():
            Manifest.from_path(path)

    def test_it_is_not_empty(self):
        assert len(Index.load(BUNDLED)) >= 1

    def test_a_fresh_hub_finds_it_without_configuration(self, monkeypatch):
        monkeypatch.delenv("MOLHUB_INDEX", raising=False)
        assert len(Molhub()) >= 1

    def test_manifest_paths_match_their_coordinates(self):
        """A misfiled manifest resolves under a name nobody will guess."""
        for path in IndexSource(BUNDLED).manifest_paths():
            manifest = Manifest.from_path(path)
            assert path.relative_to(BUNDLED).as_posix() == manifest.coordinate.relative_path()

    def test_every_manifest_validates_against_the_shipped_schema(self):
        jsonschema = pytest.importorskip("jsonschema")
        schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for path in IndexSource(BUNDLED).manifest_paths():
            validator.validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class TestPolymerTgEntry:
    @pytest.fixture
    def manifest(self):
        return Molhub(BUNDLED).resolve("dataset:molcrafts/polymer-tg@1")

    def test_resolves(self, manifest):
        assert manifest.title.startswith("LAMALAB")

    def test_declares_a_zenodo_locator(self, manifest):
        assert str(manifest.artifact("main").locators[0]).startswith("zenodo://")

    def test_records_the_version_doi(self, manifest):
        assert manifest.doi == "10.5281/zenodo.14980914"

    def test_digest_is_zenodos_own_published_md5(self, manifest):
        assert manifest.artifact("main").digest.algorithm == "md5"

    def test_size_is_declared(self, manifest):
        assert manifest.artifact("main").size == 6024335


@pytest.mark.network
class TestAgainstRealUpstream:
    def test_fetching_the_bundled_dataset_verifies(self, tmp_path, monkeypatch):
        """End-to-end against Zenodo: resolve, transfer, verify, cache.

        Run with ``pytest -m network``.
        """
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path))
        paths = Molhub(BUNDLED).fetch("dataset:molcrafts/polymer-tg@1")
        assert paths["main"].stat().st_size == 6024335
        assert paths["main"].read_text(encoding="utf-8").startswith("PSMILES")


@pytest.mark.network
class TestQM9AgainstRealUpstream:
    """The dataset whose silent corruption motivated this whole layer."""

    def test_fetch_verifies_both_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path))
        paths = Molhub(BUNDLED).fetch("dataset:molcrafts/qm9@v2")
        assert paths["main"].stat().st_size == 86144227
        assert paths["exclude"].stat().st_size == 486752

    def test_the_exclusion_list_is_not_empty(self, tmp_path, monkeypatch):
        """A 0-byte exclusion list is exactly what used to get cached."""
        from molhub.dataset.qm9 import _load_exclusion_list

        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path))
        paths = Molhub(BUNDLED).fetch("dataset:molcrafts/qm9@v2", roles=["exclude"])
        assert len(_load_exclusion_list(paths["exclude"])) == 3054

    def test_source_loads_the_documented_sample_count(self, tmp_path, monkeypatch):
        """133,885 raw minus 3,054 uncharacterized is the 130,831 README promises."""
        from molhub.dataset import QM9Source

        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path))
        assert len(QM9Source(tmp_path / "unused", hub=Molhub(BUNDLED))) == 130831


class TestLocatorsPinAVersion:
    """A locator that does not pin a version silently follows upstream's next
    release. Figshare article ids are the trap: they are not version-specific."""

    def _locators(self):
        for path in IndexSource(BUNDLED).manifest_paths():
            manifest = Manifest.from_path(path)
            for role, artifact in manifest.artifacts.items():
                for locator in artifact.locators:
                    yield manifest.coordinate.canonical, role, locator

    def test_no_bare_figshare_article_id(self):
        offenders = [
            f"{coord} [{role}] {locator}"
            for coord, role, locator in self._locators()
            if locator.scheme == "figshare"
            and not any(p.startswith("v") and p[1:].isdigit() for p in locator.path.split("/"))
        ]
        assert offenders == [], f"unpinned Figshare locators: {offenders}"

    def test_every_bundled_manifest_records_a_doi(self):
        missing = [
            Manifest.from_path(p).coordinate.canonical
            for p in IndexSource(BUNDLED).manifest_paths()
            if Manifest.from_path(p).doi is None
        ]
        assert missing == [], f"manifests without a DOI: {missing}"
