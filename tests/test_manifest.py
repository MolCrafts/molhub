"""Tests for manifest parsing."""

from __future__ import annotations

import textwrap

import pytest

from molhub.manifest import InvalidManifest, Manifest

from .conftest import MAIN_MD5, manifest_yaml


class TestManifestFields:
    @pytest.fixture
    def manifest(self):
        return Manifest.from_yaml(manifest_yaml())

    def test_coordinate(self, manifest):
        assert manifest.coordinate.canonical == "dataset:molcrafts/qm9@v2"

    def test_descriptive_fields(self, manifest):
        assert manifest.title.startswith("QM9")
        assert manifest.license == "CC0-1.0"
        assert manifest.doi == "10.1038/sdata.2014.22"

    def test_targets(self, manifest):
        assert manifest.targets.graph_level == ("U0", "gap", "homo")
        assert manifest.targets.atom_level == ()

    def test_artifacts_are_keyed_by_role(self, manifest):
        assert set(manifest.artifacts) == {"main", "exclude"}

    def test_digest_is_the_platforms_published_value(self, manifest):
        digest = manifest.artifact("main").digest
        assert digest.algorithm == "md5"
        assert digest.hexdigest == MAIN_MD5

    def test_locators_keep_their_order(self, manifest):
        assert [str(loc) for loc in manifest.artifact("main").locators] == [
            "fake://main",
            "fake://main-backup",
        ]

    def test_size_is_optional(self, manifest):
        assert manifest.artifact("exclude").size is None

    def test_comments_do_not_reach_the_parsed_result(self, manifest):
        """Manifests are reviewed by people; explaining a mirror must be free."""
        without_comments = "\n".join(
            line for line in manifest_yaml().splitlines() if not line.strip().startswith("#")
        )
        assert Manifest.from_yaml(without_comments) == manifest

    def test_unknown_role_names_the_alternatives(self, manifest):
        with pytest.raises(KeyError, match="exclude"):
            manifest.artifact("nope")


class TestManifestRejection:
    def test_a_digest_is_optional(self):
        """Some platforms publish none; molhub does not invent one."""
        without = textwrap.dedent("""
            schema_version: 1
            kind: dataset
            namespace: molcrafts
            name: qm9
            version: v2
            title: QM9
            artifacts:
              - role: main
                filename: qm9.tar.bz2
                locators: [fake://main]
        """)
        assert Manifest.from_yaml(without).artifact("main").digest is None

    def test_malformed_digest_is_refused(self):
        bad = manifest_yaml().replace(f'"md5:{MAIN_MD5}"', '"not-a-digest"')
        with pytest.raises(InvalidManifest, match="digest"):
            Manifest.from_yaml(bad)

    def test_error_says_which_artifact_is_at_fault(self):
        bad = manifest_yaml().replace(f'"md5:{MAIN_MD5}"', '"md5:zz"', 1)
        with pytest.raises(InvalidManifest, match="'main'"):
            Manifest.from_yaml(bad)

    @pytest.mark.parametrize("field", ["kind", "namespace", "name", "version", "title"])
    def test_missing_required_field(self, field):
        lines = [ln for ln in manifest_yaml().splitlines() if not ln.startswith(f"{field}:")]
        with pytest.raises(InvalidManifest, match=field):
            Manifest.from_yaml("\n".join(lines))

    def test_unknown_schema_version(self):
        with pytest.raises(InvalidManifest, match="schema_version"):
            Manifest.from_yaml(manifest_yaml(schema_version=99))

    def test_missing_schema_version(self):
        lines = [ln for ln in manifest_yaml().splitlines() if not ln.startswith("schema_version:")]
        with pytest.raises(InvalidManifest, match="schema_version"):
            Manifest.from_yaml("\n".join(lines))

    def test_no_artifacts(self):
        bad = manifest_yaml().split("artifacts:")[0] + "artifacts: []\n"
        with pytest.raises(InvalidManifest, match="artifacts"):
            Manifest.from_yaml(bad)

    def test_artifact_without_locators(self):
        bad = manifest_yaml().replace("    locators:\n", "    locators: []\n", 1)
        bad = bad.replace("      - fake://main          # preferred mirror\n", "")
        bad = bad.replace("      - fake://main-backup\n", "")
        with pytest.raises(InvalidManifest, match="locators"):
            Manifest.from_yaml(bad)

    def test_duplicate_roles(self):
        doubled = manifest_yaml().replace("  - role: exclude", "  - role: main", 1)
        with pytest.raises(InvalidManifest, match="twice"):
            Manifest.from_yaml(doubled)

    def test_broken_yaml(self):
        with pytest.raises(InvalidManifest, match="not valid YAML"):
            Manifest.from_yaml("artifacts: [unclosed\n")

    def test_non_mapping_document(self):
        with pytest.raises(InvalidManifest, match="mapping"):
            Manifest.from_yaml("- just\n- a\n- list\n")

    def test_error_carries_the_file_path(self, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text("schema_version: 1\n")
        with pytest.raises(InvalidManifest, match="broken.yaml"):
            Manifest.from_path(path)


class TestManifestSearchMatching:
    @pytest.fixture
    def manifest(self):
        return Manifest.from_yaml(manifest_yaml())

    @pytest.mark.parametrize("query", ["qm9", "QM9", "molecules", "U0", "molcrafts", "sdata"])
    def test_matches_across_the_searchable_fields(self, manifest, query):
        assert manifest.matches(query)

    def test_does_not_match_unrelated_text(self, manifest):
        assert not manifest.matches("revmd17")
