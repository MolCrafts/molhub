"""Tests for coordinate parsing."""

from __future__ import annotations

import pytest

from molhub.coordinate import Coordinate, InvalidCoordinate


class TestParseFullForm:
    def test_all_segments(self):
        coord = Coordinate.parse("dataset:molcrafts/qm9@v2")
        assert (coord.kind, coord.namespace, coord.name, coord.version) == (
            "dataset",
            "molcrafts",
            "qm9",
            "v2",
        )

    @pytest.mark.parametrize("kind", ["dataset", "model", "plugin"])
    def test_every_kind(self, kind):
        assert Coordinate.parse(f"{kind}:ns/name@1").kind == kind

    def test_hyphenated_names(self):
        coord = Coordinate.parse("model:molcrafts/mace-mp-0@1.0")
        assert coord.name == "mace-mp-0"

    @pytest.mark.parametrize("version", ["v2", "1.0", "0.3.1", "2024-05-01", "abc_1"])
    def test_version_character_set(self, version):
        assert Coordinate.parse(f"dataset:ns/n@{version}").version == version


class TestParseShorthand:
    def test_bare_name_and_version(self):
        assert Coordinate.parse("qm9@v2") == Coordinate.parse("dataset:molcrafts/qm9@v2")

    def test_namespace_without_kind(self):
        assert Coordinate.parse("molcrafts/qm9@v2").kind == "dataset"

    def test_kind_without_namespace(self):
        assert Coordinate.parse("plugin:molvis-render@0.3.1").namespace == "molcrafts"

    def test_shorthand_and_full_form_are_the_same_object(self):
        """Otherwise the shorthand is a second syntax, not an abbreviation."""
        assert Coordinate.parse("qm9@v2").canonical == "dataset:molcrafts/qm9@v2"


class TestParseRejection:
    def test_missing_version_is_rejected(self):
        with pytest.raises(InvalidCoordinate, match="@version"):
            Coordinate.parse("dataset:molcrafts/qm9")

    def test_missing_version_message_explains_why(self):
        with pytest.raises(InvalidCoordinate, match="immutable"):
            Coordinate.parse("qm9")

    @pytest.mark.parametrize(
        "bad",
        ["", "   ", "qm9@", "dataset:molcrafts/@v2", "dataset:/qm9@v2"],
    )
    def test_empty_segments(self, bad):
        with pytest.raises(InvalidCoordinate):
            Coordinate.parse(bad)

    def test_unknown_kind(self):
        with pytest.raises(InvalidCoordinate, match="Unknown kind"):
            Coordinate.parse("notebook:ns/n@1")

    @pytest.mark.parametrize("name", ["QM9", "qm 9", "-qm9", "qm.9", "qm_9"])
    def test_name_character_set_is_enforced(self, name):
        with pytest.raises(InvalidCoordinate, match="name"):
            Coordinate.parse(f"dataset:ns/{name}@1")

    def test_namespace_character_set_is_enforced(self):
        with pytest.raises(InvalidCoordinate, match="namespace"):
            Coordinate.parse("dataset:MolCrafts/qm9@1")

    def test_error_names_the_offending_segment(self):
        with pytest.raises(InvalidCoordinate, match="version"):
            Coordinate.parse("dataset:ns/n@!bad")


class TestCoordinateValue:
    def test_is_frozen(self):
        coord = Coordinate.parse("qm9@v2")
        with pytest.raises(Exception):
            coord.version = "v3"  # type: ignore[misc]

    def test_equality_by_value(self):
        assert Coordinate.parse("qm9@v2") == Coordinate.parse("dataset:molcrafts/qm9@v2")

    def test_versions_are_distinct(self):
        assert Coordinate.parse("qm9@v2") != Coordinate.parse("qm9@v3")

    def test_hashable(self):
        assert len({Coordinate.parse("qm9@v2"), Coordinate.parse("qm9@v2")}) == 1

    def test_str_is_canonical(self):
        assert str(Coordinate.parse("qm9@v2")) == "dataset:molcrafts/qm9@v2"

    def test_canonical_reparses_to_itself(self):
        coord = Coordinate.parse("qm9@v2")
        assert Coordinate.parse(coord.canonical) == coord

    def test_coerce_passes_through_a_coordinate(self):
        coord = Coordinate.parse("qm9@v2")
        assert Coordinate.coerce(coord) is coord

    def test_coerce_parses_a_string(self):
        assert Coordinate.coerce("qm9@v2") == Coordinate.parse("qm9@v2")


class TestCoordinateDerivations:
    def test_unversioned_groups_releases(self):
        assert Coordinate.parse("qm9@v2").unversioned == "dataset:molcrafts/qm9"

    def test_unversioned_is_shared_across_versions(self):
        a, b = Coordinate.parse("qm9@v2"), Coordinate.parse("qm9@v3")
        assert a.unversioned == b.unversioned

    def test_relative_path_matches_the_registry_layout(self):
        assert Coordinate.parse("qm9@v2").relative_path() == "dataset/molcrafts/qm9/v2.yaml"

    def test_cache_path_matches_the_documented_layout(self):
        assert Coordinate.parse("qm9@v2").cache_path() == "dataset/molcrafts/qm9@v2"

    def test_cache_path_keeps_kind_and_namespace_apart(self):
        # The canonical form joins them with ':', which is not a path separator;
        # building the cache key from it collapsed both into one segment and
        # broke the layout the TypeScript client shares on the same machine.
        assert Coordinate.parse("qm9@v2").cache_path().split("/")[:2] == ["dataset", "molcrafts"]
