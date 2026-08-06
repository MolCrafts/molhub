"""Tests for the immutable Drivers collection."""

from __future__ import annotations

import pytest

from molhub.registry.drivers import Drivers
from molhub.registry.errors import UnknownScheme

from ..conftest import FakeRegistry


class TestDriversConstruction:
    def test_of_accepts_varargs(self):
        drivers = Drivers.of(FakeRegistry(scheme="a"), FakeRegistry(scheme="b"))
        assert set(drivers.schemes()) == {"a", "b"}

    def test_empty_collection(self):
        assert Drivers.of().schemes() == ()

    def test_discover_includes_the_builtin_schemes(self):
        schemes = set(Drivers.discover().schemes())
        assert {"https", "zenodo", "figshare", "hf", "molhub"} <= schemes

    def test_discover_is_repeatable(self):
        assert set(Drivers.discover().schemes()) == set(Drivers.discover().schemes())


class TestDriversLookup:
    def test_for_scheme_returns_the_driver(self):
        fake = FakeRegistry(scheme="a")
        assert Drivers.of(fake).for_scheme("a") is fake

    def test_unknown_scheme_raises(self):
        with pytest.raises(UnknownScheme, match="nope"):
            Drivers.of(FakeRegistry(scheme="a")).for_scheme("nope")

    def test_error_lists_the_available_schemes(self):
        with pytest.raises(UnknownScheme, match="a"):
            Drivers.of(FakeRegistry(scheme="a")).for_scheme("nope")

    def test_lookup_is_case_insensitive_like_locator_schemes(self):
        fake = FakeRegistry(scheme="a")
        assert Drivers.of(fake).for_scheme("A") is fake


class TestDriversImmutability:
    def test_with_driver_returns_a_new_collection(self):
        base = Drivers.of(FakeRegistry(scheme="a"))
        extended = base.with_driver(FakeRegistry(scheme="b"))
        assert extended is not base

    def test_original_does_not_gain_the_new_scheme(self):
        base = Drivers.of(FakeRegistry(scheme="a"))
        base.with_driver(FakeRegistry(scheme="b"))
        with pytest.raises(UnknownScheme):
            base.for_scheme("b")

    def test_new_collection_keeps_the_original_drivers(self):
        first = FakeRegistry(scheme="a")
        extended = Drivers.of(first).with_driver(FakeRegistry(scheme="b"))
        assert extended.for_scheme("a") is first
        assert extended.for_scheme("b").scheme == "b"

    def test_later_driver_overrides_an_earlier_one_for_the_same_scheme(self):
        first, second = FakeRegistry(scheme="a"), FakeRegistry(scheme="a")
        assert Drivers.of(first).with_driver(second).for_scheme("a") is second

    def test_discover_result_is_not_mutated_by_with_driver(self):
        discovered = Drivers.discover()
        before = set(discovered.schemes())
        discovered.with_driver(FakeRegistry(scheme="brand-new"))
        assert set(discovered.schemes()) == before
