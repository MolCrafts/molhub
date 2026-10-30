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

from molhub import Molhub, snapshot
from molhub.manifest import Manifest
from molhub.registry import Registry
from molhub.sources import Drivers, Locator

SCHEMA = Path(__file__).resolve().parents[1] / "src" / "molhub" / "schema" / "manifest.schema.yaml"

GITHUB_RAW_HOST = "raw.githubusercontent.com"
COMMIT_ID = re.compile(r"[0-9a-fA-F]{40}")


def bundled_locators():
    """Yield ``(coordinate, role, locator)`` for every locator in the Python catalog."""
    for manifest in Registry.builtin():
        for role, artifact in manifest.artifacts.items():
            for locator in artifact.locators:
                yield manifest.coordinate.canonical, role, locator


class TestBundledRegistryIsUsable:
    def test_it_is_not_empty(self):
        assert len(Registry.builtin()) >= 1

    def test_a_fresh_hub_finds_it_without_configuration(self, monkeypatch):
        monkeypatch.delenv("MOLHUB_REGISTRY", raising=False)
        assert len(Molhub()) >= 1

    def test_snapshot_lists_every_catalog_entry(self):
        registry = Registry.builtin()
        document = snapshot()
        assert document["schema_version"] == 1
        assert len(document["entries"]) == len(registry)

    def test_artifacts_api_returns_the_python_catalog(self):
        import molhub

        files = molhub.artifacts("qm9@v2")
        assert set(files) == {"main", "exclude"}
        assert str(files["main"].locators[0]).startswith("figshare://")

    def test_every_manifest_validates_against_the_shipped_schema(self):
        jsonschema = pytest.importorskip("jsonschema")
        schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for manifest in Registry.builtin():
            validator.validate(manifest.to_mapping())


# Zenodo's own version label, DOI, locator, published md5, and size.
# One row per record of concept 10.5281/zenodo.14980913. v5–v7 share a checksum;
# they stay separate coordinates because the records are not the same DOI.
POLYMER_TG_RELEASES = (
    (
        "v1",
        "10.5281/zenodo.14980914",
        "zenodo://14980914/LAMALAB_CURATED_Tg_structured.csv",
        "md5:ce2c7b2a879450cbbfff4d7ccea648f9",
        6_024_335,
    ),
    (
        "v2",
        "10.5281/zenodo.15209940",
        "zenodo://15209940/LAMALAB_CURATED_Tg_structured_polymerclass.csv",
        "md5:833ca70192089b0613b3292394b91c57",
        5_296_460,
    ),
    (
        "v3",
        "10.5281/zenodo.15210011",
        "zenodo://15210011/LAMALAB_CURATED_Tg_structured.csv",
        "md5:833ca70192089b0613b3292394b91c57",
        5_296_460,
    ),
    (
        "v4",
        "10.5281/zenodo.15210035",
        "zenodo://15210035/LAMALAB_CURATED_Tg_structured_polymerclass.csv",
        "md5:833ca70192089b0613b3292394b91c57",
        5_296_460,
    ),
    (
        "v5",
        "10.5281/zenodo.15781175",
        "zenodo://15781175/LAMALAB_CURATED_Tg_structured_polymerclass_with_embeddings.csv",
        "md5:31400a5f499394e3a6e0658488a464bb",
        43_615_282,
    ),
    (
        "v6",
        "10.5281/zenodo.15783761",
        "zenodo://15783761/LAMALAB_CURATED_Tg_structured_polymerclass_with_embeddings.csv",
        "md5:31400a5f499394e3a6e0658488a464bb",
        43_615_282,
    ),
    (
        "v7",
        "10.5281/zenodo.15789599",
        "zenodo://15789599/LAMALAB_CURATED_Tg_structured_polymerclass_with_embeddings.csv",
        "md5:31400a5f499394e3a6e0658488a464bb",
        43_615_282,
    ),
)


class TestPolymerTgEntry:
    @pytest.mark.parametrize(("version", "doi", "locator", "digest", "size"), POLYMER_TG_RELEASES)
    def test_each_zenodo_version_is_pinned(self, version, doi, locator, digest, size):
        manifest = Molhub().resolve(f"dataset:molcrafts/polymer-tg@{version}")
        artifact = manifest.artifact("main")
        assert manifest.title.startswith("LAMALAB")
        assert manifest.doi == doi
        assert str(artifact.locators[0]) == locator
        assert str(artifact.digest) == digest
        assert artifact.digest.algorithm == "md5"
        assert artifact.size == size
        assert manifest.targets.graph_level == ("labels.Exp_Tg(K)",)

    def test_the_unlabeled_version_is_gone(self):
        from molhub.registry import UnknownArtifact

        with pytest.raises(UnknownArtifact, match="v1"):
            Molhub().resolve("dataset:molcrafts/polymer-tg@1")

    def test_an_omitted_revision_is_refused(self):
        from molhub.loader.naming import AmbiguousRevision, DatasetName

        with pytest.raises(AmbiguousRevision, match="v7"):
            DatasetName("polymer-tg").resolve(Registry.builtin())

    def test_an_explicit_revision_resolves(self):
        from molhub.loader.naming import DatasetName

        resolved = DatasetName("polymer-tg", revision="v7").resolve(Registry.builtin())
        assert resolved.canonical == "dataset:molcrafts/polymer-tg@v7"


class TestTHEMolMbisEntry:
    """The bundled MBIS manifest must name the columns a reader actually finds.

    ``targets.atom_level`` is not decoration: when a dataset class carries no
    ``TARGET_SCHEMA``, ``DatasetBuilder._target_schema``
    (``src/molhub/loader/builder.py``) builds the schema straight out of this
    yaml block, so whatever is written here is what a user sees in
    ``DatasetInfo``. The grouped spellings this manifest was generated with
    (``atomic_dipole`` / ``atomic_quadrupole`` / ``mbis_parameters``) match no
    column of any MBIS sample — the frame carries ``dipole_<axis>`` and
    ``quadrupole_<axis><axis>`` columns instead, and the Slater parameters are
    not an ``atoms`` column at all.

    **Where the Slater parameters are, and why this list names none of them.**
    The source ``parameters`` array is ``(S, 3)`` — one row per MBIS Slater
    *shell*, and a shell is not an atom: hydrogen carries one, most heavy atoms
    two, a third-period atom can carry three, so ``S > N`` and the rows line up
    with atoms in no arity whatsoever. The reader carries them as the
    shell-major ``mbis_shells`` block on the frame, three columns wide (``atom``
    / ``population`` / ``inverse_width``, ``src/molhub/dataset/themol.py``),
    which is a place an ``atom_level`` list has no way to name — so it names
    none of them, on purpose. ``mbis_parameter_<slot>`` columns are not "not
    declared yet": they are a shape no published record has, which the reader
    emitted until the probe recorded in ``tests/test_dataset/test_themol.py``
    showed 0 of 43 sampled indices were readable.

    The fourteen names are written out as literals rather than imported from
    ``_MBIS_ATOM_COLUMNS``, so drift on *either* side trips this pin.
    """

    #: The atom-level target names the MBIS format fixes. The Slater parameters
    #: are deliberately absent, and not for want of a spelling: they are
    #: shell-level ``(S, 3)`` rows carried as the ``mbis_shells`` block, so this
    #: list — which can only name ``atoms`` columns — has nothing per-atom to
    #: name (see the ``THEMolMBIS`` docstring).
    ATOM_LEVEL = frozenset(
        {
            "atomic_charge",
            "atomic_volume",
            "dipole_x",
            "dipole_y",
            "dipole_z",
            "quadrupole_xx",
            "quadrupole_xy",
            "quadrupole_xz",
            "quadrupole_yx",
            "quadrupole_yy",
            "quadrupole_yz",
            "quadrupole_zx",
            "quadrupole_zy",
            "quadrupole_zz",
        }
    )

    #: The pre-dissolution names, kept only so their return is loud.
    GROUPED = frozenset({"atomic_dipole", "atomic_quadrupole", "mbis_parameters"})

    @pytest.fixture
    def manifest(self) -> Manifest:
        return Molhub().resolve("dataset:themol/mbis@1")

    def test_atom_level_targets_are_the_fourteen_real_column_names(
        self, manifest: Manifest
    ) -> None:
        declared = frozenset(manifest.targets.atom_level)
        assert declared == self.ATOM_LEVEL, (
            "the bundled MBIS manifest declares atom-level targets that are not "
            f"the columns on a record — unexpected: {sorted(declared - self.ATOM_LEVEL)}, "
            f"missing: {sorted(self.ATOM_LEVEL - declared)}"
        )
        assert len(manifest.targets.atom_level) == 14
        assert manifest.targets.graph_level == (), "every MBIS target is per atom"

    def test_no_grouped_or_parameter_name_survives(self, manifest: Manifest) -> None:
        """A grouped name promises one column and delivers three, nine, or none."""
        declared = frozenset(manifest.targets.atom_level)
        assert not [name for name in declared if "mbis_parameter" in name], (
            "the Slater parameters are shell-level rows carried as the mbis_shells "
            "block, so no atom-level column names them: "
            f"{sorted(n for n in declared if 'mbis_parameter' in n)}"
        )
        assert declared & self.GROUPED == frozenset(), (
            f"pre-dissolution grouped target names are back: {sorted(declared & self.GROUPED)}"
        )

    def test_the_manifest_and_the_adapter_declare_the_same_targets(
        self, manifest: Manifest
    ) -> None:
        """Two sources of the same fact; this is what keeps them one fact.

        The loader falls back to the manifest only when a dataset class has no
        ``TARGET_SCHEMA``, so a disagreement is invisible until the day someone
        reads the yaml instead of the class.
        """
        from molhub.dataset.themol import THEMolMBIS

        assert frozenset(manifest.targets.atom_level) == frozenset(
            THEMolMBIS.TARGET_SCHEMA.atom_level
        ), (
            "the bundled manifest and THEMolMBIS.TARGET_SCHEMA disagree about the "
            f"atom-level targets — manifest: {sorted(manifest.targets.atom_level)}, "
            f"class: {sorted(THEMolMBIS.TARGET_SCHEMA.atom_level)}"
        )
        assert frozenset(manifest.targets.graph_level) == frozenset(
            THEMolMBIS.TARGET_SCHEMA.graph_level
        )


@pytest.mark.network
class TestAgainstRealUpstream:
    def test_fetching_the_bundled_dataset_verifies(self, tmp_path):
        """End-to-end against Zenodo: resolve, transfer, verify, cache.

        Run with ``pytest -m network``.
        """
        from molhub.config import config

        previous = config.home_dir
        try:
            config.home_dir = tmp_path
            paths = Molhub().fetch("dataset:molcrafts/polymer-tg@v1")
        finally:
            config.home_dir = previous
        assert paths["main"].stat().st_size == 6024335
        assert paths["main"].read_text(encoding="utf-8").startswith("PSMILES")


@pytest.mark.network
class TestQM9AgainstRealUpstream:
    """The dataset whose silent corruption motivated this whole layer."""

    def test_fetch_verifies_both_artifacts(self, tmp_path):
        from molhub.config import config

        previous = config.home_dir
        try:
            config.home_dir = tmp_path
            paths = Molhub().fetch("dataset:molcrafts/qm9@v2")
        finally:
            config.home_dir = previous
        assert paths["main"].stat().st_size == 86144227
        assert paths["exclude"].stat().st_size == 486752

    def test_the_exclusion_list_is_not_empty(self, tmp_path):
        """A 0-byte exclusion list is exactly what used to get cached."""
        from molhub.config import config
        from molhub.dataset.qm9 import _load_exclusion_list

        previous = config.home_dir
        try:
            config.home_dir = tmp_path
            paths = Molhub().fetch("dataset:molcrafts/qm9@v2", roles=["exclude"])
        finally:
            config.home_dir = previous
        assert len(_load_exclusion_list(paths["exclude"])) == 3054

    def test_source_loads_the_documented_sample_count(self, tmp_path):
        """133,885 raw minus 3,054 uncharacterized is the 130,831 README promises."""
        from molhub.config import config
        from molhub.dataset import QM9

        previous = config.home_dir
        try:
            config.home_dir = tmp_path
            n = len(QM9(tmp_path / "unused", hub=Molhub()).load())
        finally:
            config.home_dir = previous
        assert n == 130831


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
            manifest.coordinate.canonical for manifest in Registry.builtin() if manifest.doi is None
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
