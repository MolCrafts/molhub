"""Tests for the Publication value object."""

from __future__ import annotations

import pytest

from molhub.registry.publication import Publication


class TestPublicationConstruction:
    def test_title_only(self):
        assert Publication(title="QM9").title == "QM9"

    def test_defaults_are_empty_not_none(self):
        pub = Publication(title="QM9")
        assert pub.description == ""
        assert pub.keywords == ()
        assert pub.license is None
        assert pub.private is False

    def test_keywords_are_normalised_to_a_tuple(self):
        assert Publication(title="x", keywords=["a", "b"]).keywords == ("a", "b")

    @pytest.mark.parametrize("bad", ["", "   ", "\n"])
    def test_blank_title_is_rejected(self, bad):
        with pytest.raises(ValueError, match="title"):
            Publication(title=bad)


class TestPublicationValue:
    def test_is_frozen(self):
        pub = Publication(title="x")
        with pytest.raises(Exception):
            pub.title = "y"  # type: ignore[misc]

    def test_equality_by_value(self):
        assert Publication(title="x") == Publication(title="x")

    def test_keywords_do_not_leak_a_mutable_reference(self):
        keywords = ["a"]
        pub = Publication(title="x", keywords=keywords)
        keywords.append("b")
        assert pub.keywords == ("a",)
