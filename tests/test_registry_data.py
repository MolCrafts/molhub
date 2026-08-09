"""The bundled registry must be loadable, schema-valid, and actually resolvable.

Everything here is offline. The one test that would touch Zenodo is marked
``network`` and deselected by default — CI must not go red because a data
repository is having a slow morning.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

import molhub
from molhub import Molhub
from molhub.manifest import Manifest
from molhub.registry import Registry, RegistrySource
from molhub.sources import Drivers, Locator

BUNDLED = Path(molhub.__file__).parent / "registry_data"
SCHEMA = Path(molhub.__file__).parent / "schema" / "manifest.schema.yaml"

GITHUB_RAW_HOST = "raw.githubusercontent.com"
COMMIT_ID = re.compile(r"[0-9a-fA-F]{40}")


def bundled_locators():
    """Yield ``(coordinate, role, locator)`` for every locator in the bundled registry."""
    for path in RegistrySource(BUNDLED).manifest_paths():
        manifest = Manifest.from_path(path)
        for role, artifact in manifest.artifacts.items():
            for locator in artifact.locators:
                yield manifest.coordinate.canonical, role, locator


class TestBundledRegistryIsUsable:
    def test_it_ships(self):
        assert BUNDLED.is_dir()

    def test_every_manifest_parses(self):
        for path in RegistrySource(BUNDLED).manifest_paths():
            Manifest.from_path(path)

    def test_it_is_not_empty(self):
        assert len(Registry.load(BUNDLED)) >= 1

    def test_a_fresh_hub_finds_it_without_configuration(self, monkeypatch):
        monkeypatch.delenv("MOLHUB_REGISTRY", raising=False)
        assert len(Molhub()) >= 1

    def test_manifest_paths_match_their_coordinates(self):
        """A misfiled manifest resolves under a name nobody will guess."""
        for path in RegistrySource(BUNDLED).manifest_paths():
            manifest = Manifest.from_path(path)
            assert path.relative_to(BUNDLED).as_posix() == manifest.coordinate.relative_path()

    def test_every_manifest_validates_against_the_shipped_schema(self):
        jsonschema = pytest.importorskip("jsonschema")
        schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for path in RegistrySource(BUNDLED).manifest_paths():
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
        from molhub.dataset import QM9Dataset

        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path))
        assert len(QM9Dataset(tmp_path / "unused", hub=Molhub(BUNDLED))) == 130831


class TestLocatorsPinAVersion:
    """A locator that does not pin a version silently follows upstream's next
    release. Figshare article ids are the trap: they are not version-specific.
    A GitHub branch name is the same trap in a different spelling."""

    def _github_raw_ref(self, locator: Locator) -> str | None:
        """The ref a GitHub raw-content locator names, or ``None`` for any other host.

        The shape is ``<host>/<owner>/<repo>/<ref>/<path…>``. Anything shorter
        cannot name a file at all, and comes back as ``""`` so a malformed URL
        fails the pin check rather than slipping past it.
        """
        host, _, rest = locator.path.partition("/")
        if locator.scheme not in {"http", "https"} or host != GITHUB_RAW_HOST:
            return None
        segments = rest.split("/")
        return segments[2] if len(segments) >= 4 else ""

    def test_no_bare_figshare_article_id(self):
        offenders = [
            f"{coord} [{role}] {locator}"
            for coord, role, locator in bundled_locators()
            if locator.scheme == "figshare"
            and not any(p.startswith("v") and p[1:].isdigit() for p in locator.path.split("/"))
        ]
        assert offenders == [], f"unpinned Figshare locators: {offenders}"

    def test_github_raw_locators_pin_a_commit(self):
        """`.../BOTNet-datasets/main/f.xyz` and `.../29e6d467…/f.xyz` differ by one
        word in review and by everything in meaning."""
        offenders = [
            f"{coord} [{role}] {locator}"
            for coord, role, locator in bundled_locators()
            if (ref := self._github_raw_ref(locator)) is not None and not COMMIT_ID.fullmatch(ref)
        ]
        assert offenders == [], (
            "A GitHub raw locator must pin a full 40-hex commit id. A branch such "
            "as `main` or `master` serves whatever was pushed last, so the manifest "
            "starts meaning something else with nothing in the diff to show it; a "
            "tag can be force-moved, and an abbreviated sha can turn ambiguous. A "
            "commit id is a content hash and names these exact bytes for good. "
            "Write https://raw.githubusercontent.com/<owner>/<repo>/<40-hex commit>/<path> "
            "— `git ls-remote https://github.com/<owner>/<repo> <branch>` prints the "
            f"id to paste. Unpinned: {offenders}"
        )

    @staticmethod
    def _hf_revision(locator: Locator) -> str | None:
        """The revision an ``hf://`` locator names, or ``None`` for another scheme.

        The driver splits the path as ``org/repo[@revision]/file…``
        (``huggingface.py:179``), so the revision rides on the second segment
        and an absent one defaults to ``main``. A path too short to be a valid
        locator comes back as ``""`` so it fails the check rather than being
        skipped.
        """
        if locator.scheme != "hf":
            return None
        segments = locator.path.split("/")
        if len(segments) < 3:
            return ""
        _, _, revision = segments[1].partition("@")
        return revision

    def test_hf_locators_pin_a_commit(self):
        """`hf://org/repo/f.bin` silently means revision `main`.

        Held to the same standard as the GitHub guard above, and for the same
        reason: `@main` is not a pin, and a tag can be force-moved. Only a
        commit id names bytes permanently. The bundled registry has no
        HuggingFace locator yet — this exists so the first one cannot arrive
        unpinned.
        """
        offenders = [
            f"{coord} [{role}] {locator}"
            for coord, role, locator in bundled_locators()
            if (rev := self._hf_revision(locator)) is not None and not COMMIT_ID.fullmatch(rev)
        ]
        assert offenders == [], (
            "A HuggingFace locator must pin a full 40-hex commit id: write "
            "hf://<org>/<repo>@<commit>/<path>. Omitting `@<rev>` resolves to "
            "`main`, and a branch or tag moves. Get the id from the repo's "
            f"commit history or `huggingface_hub.HfApi().repo_info(...)`. Unpinned: {offenders}"
        )

    def test_every_bundled_manifest_records_a_doi(self):
        missing = [
            Manifest.from_path(p).coordinate.canonical
            for p in RegistrySource(BUNDLED).manifest_paths()
            if Manifest.from_path(p).doi is None
        ]
        assert missing == [], f"manifests without a DOI: {missing}"


class TestLocatorsUseAKnownScheme:
    """A mistyped scheme survives every other check in this file.

    ``zendo://14980914/x.csv`` parses, validates against the schema, matches
    the locator pattern, and loads into the registry without a murmur. Nothing
    consults the driver table until :meth:`Drivers.for_scheme` runs inside a
    real fetch — so the first thing that notices is a user's download.

    The check is scoped to the *bundled* registry against the *built-in* drivers,
    deliberately. Schemes are pluggable through the ``molhub.sources``
    entry-point group, so a scheme molhub has never heard of is perfectly legal
    in someone else's registry — rejecting unknown schemes at parse time would
    break the extension mechanism. But what molhub ships must be resolvable by
    what molhub ships, with nothing else installed.
    """

    def test_every_bundled_locator_has_a_builtin_driver(self):
        known = set(Drivers.builtin().schemes())
        offenders = [
            f"{coord} [{role}] {locator}"
            for coord, role, locator in bundled_locators()
            if locator.scheme not in known
        ]
        assert offenders == [], (
            f"Bundled locators must use a scheme one of molhub's own drivers claims "
            f"({', '.join(sorted(known))}). These do not, which almost always means a "
            f"typo — nothing would notice until a user tried to fetch: {offenders}"
        )
