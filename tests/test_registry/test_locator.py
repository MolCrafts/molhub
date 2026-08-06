"""Tests for Locator parsing."""

from __future__ import annotations

import pytest

from molhub.registry.errors import InvalidLocator
from molhub.registry.locator import Locator


class TestLocatorParse:
    @pytest.mark.parametrize(
        ("text", "scheme", "path"),
        [
            ("zenodo://14980914", "zenodo", "14980914"),
            ("zenodo://14980914/data.csv", "zenodo", "14980914/data.csv"),
            ("figshare://3195389", "figshare", "3195389"),
            ("hf://MolCrafts/qm9/qm9.tar.bz2", "hf", "MolCrafts/qm9/qm9.tar.bz2"),
            ("https://example.org/a/b.csv", "https", "example.org/a/b.csv"),
            (
                "molhub://plugins/molvis-render/0.3.1.zip",
                "molhub",
                "plugins/molvis-render/0.3.1.zip",
            ),
        ],
    )
    def test_splits_scheme_from_path(self, text, scheme, path):
        loc = Locator.parse(text)
        assert loc.scheme == scheme
        assert loc.path == path

    def test_scheme_is_lowercased(self):
        assert Locator.parse("ZENODO://1").scheme == "zenodo"

    def test_roundtrips_through_str(self):
        for text in ("zenodo://14980914/data.csv", "https://example.org/x"):
            assert str(Locator.parse(text)) == text

    def test_parse_is_idempotent_on_a_locator(self):
        loc = Locator.parse("zenodo://1")
        assert Locator.parse(str(loc)) == loc

    @pytest.mark.parametrize(
        "bad",
        ["", "no-scheme", "://empty-scheme", "zenodo://", "zenodo:/single-slash", "  "],
    )
    def test_rejects_malformed(self, bad):
        with pytest.raises(InvalidLocator):
            Locator.parse(bad)

    def test_error_quotes_the_offending_text(self):
        with pytest.raises(InvalidLocator, match="no-scheme"):
            Locator.parse("no-scheme")


class TestLocatorValue:
    def test_is_frozen(self):
        loc = Locator.parse("zenodo://1")
        with pytest.raises(Exception):
            loc.scheme = "hf"  # type: ignore[misc]

    def test_equality_by_value(self):
        assert Locator.parse("zenodo://1") == Locator.parse("zenodo://1")
        assert Locator.parse("zenodo://1") != Locator.parse("zenodo://2")

    def test_hashable(self):
        assert len({Locator.parse("zenodo://1"), Locator.parse("zenodo://1")}) == 1
