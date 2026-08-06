"""Tests for Fetcher — ordered fallback, digest enforcement, cache reuse.

These cover the failure paths the whole layer exists for. The success path is
the easy part; the guarantees live in what happens when a transfer goes wrong.
"""

from __future__ import annotations

import hashlib

import pytest

from molhub.registry.blobs import BlobStore
from molhub.registry.digest import Digest
from molhub.registry.drivers import Drivers
from molhub.registry.errors import AllLocatorsFailed
from molhub.registry.fetcher import Fetcher

from .conftest import FakeRegistry

_GOOD = b"good bytes"
_GOOD_DIGEST = Digest.sha256(hashlib.sha256(_GOOD).hexdigest())


def _fetcher(fake: FakeRegistry, home) -> Fetcher:
    return Fetcher(drivers=Drivers.of(fake), blobs=BlobStore(root=home))


class TestFetcherSuccess:
    def test_returns_the_canonical_blob_path(self, molhub_home):
        fake = FakeRegistry(bodies={"a": _GOOD})
        path = _fetcher(fake, molhub_home).fetch(["fake://a"], _GOOD_DIGEST)
        assert path == BlobStore(root=molhub_home).path_for(_GOOD_DIGEST)

    def test_content_is_correct(self, molhub_home):
        fake = FakeRegistry(bodies={"a": _GOOD})
        assert _fetcher(fake, molhub_home).fetch(["fake://a"], _GOOD_DIGEST).read_bytes() == _GOOD

    def test_accepts_locator_objects_as_well_as_strings(self, molhub_home):
        from molhub.registry.locator import Locator

        fake = FakeRegistry(bodies={"a": _GOOD})
        path = _fetcher(fake, molhub_home).fetch([Locator.parse("fake://a")], _GOOD_DIGEST)
        assert path.read_bytes() == _GOOD

    def test_stops_at_the_first_success(self, molhub_home):
        fake = FakeRegistry(bodies={"a": _GOOD, "b": _GOOD})
        _fetcher(fake, molhub_home).fetch(["fake://a", "fake://b"], _GOOD_DIGEST)
        assert fake.network_calls == 1


class TestFetcherCache:
    def test_second_fetch_makes_no_network_call(self, molhub_home):
        fake = FakeRegistry(bodies={"a": _GOOD})
        fetcher = _fetcher(fake, molhub_home)
        first = fetcher.fetch(["fake://a"], _GOOD_DIGEST)
        calls_after_first = fake.network_calls
        second = fetcher.fetch(["fake://a"], _GOOD_DIGEST)
        assert second == first
        assert fake.network_calls == calls_after_first

    def test_a_fresh_fetcher_also_hits_the_shared_cache(self, molhub_home):
        _fetcher(FakeRegistry(bodies={"a": _GOOD}), molhub_home).fetch(["fake://a"], _GOOD_DIGEST)
        cold = FakeRegistry(bodies={"a": _GOOD})
        _fetcher(cold, molhub_home).fetch(["fake://a"], _GOOD_DIGEST)
        assert cold.network_calls == 0


class TestFetcherFallback:
    def test_falls_through_a_bad_status(self, molhub_home):
        fake = FakeRegistry(bodies={"a": 202, "b": _GOOD})
        path = _fetcher(fake, molhub_home).fetch(["fake://a", "fake://b"], _GOOD_DIGEST)
        assert path.read_bytes() == _GOOD
        assert fake.network_calls == 2

    def test_falls_through_a_digest_mismatch(self, molhub_home):
        fake = FakeRegistry(bodies={"a": b"wrong bytes", "b": _GOOD})
        path = _fetcher(fake, molhub_home).fetch(["fake://a", "fake://b"], _GOOD_DIGEST)
        assert path.read_bytes() == _GOOD

    def test_mismatched_bytes_never_reach_the_store(self, molhub_home):
        fake = FakeRegistry(bodies={"a": b"wrong bytes", "b": _GOOD})
        _fetcher(fake, molhub_home).fetch(["fake://a", "fake://b"], _GOOD_DIGEST)
        blobs = list((molhub_home / "blobs").rglob("*"))
        assert [p for p in blobs if p.is_file() and p.read_bytes() == b"wrong bytes"] == []

    def test_does_not_retry_the_same_locator_after_a_mismatch(self, molhub_home):
        fake = FakeRegistry(bodies={"a": b"wrong bytes", "b": _GOOD})
        _fetcher(fake, molhub_home).fetch(["fake://a", "fake://b"], _GOOD_DIGEST)
        assert fake.fetch_calls == ["fake://a", "fake://b"]

    def test_order_is_honoured(self, molhub_home):
        fake = FakeRegistry(bodies={"a": _GOOD, "b": _GOOD})
        _fetcher(fake, molhub_home).fetch(["fake://b", "fake://a"], _GOOD_DIGEST)
        assert fake.fetch_calls == ["fake://b"]


class TestFetcherExhaustion:
    def test_raises_when_every_locator_fails(self, molhub_home):
        fake = FakeRegistry(bodies={"a": 202, "b": 500, "c": b"wrong"})
        with pytest.raises(AllLocatorsFailed):
            _fetcher(fake, molhub_home).fetch(["fake://a", "fake://b", "fake://c"], _GOOD_DIGEST)

    def test_message_names_every_locator(self, molhub_home):
        fake = FakeRegistry(bodies={"a": 202, "b": 500, "c": b"wrong"})
        with pytest.raises(AllLocatorsFailed) as excinfo:
            _fetcher(fake, molhub_home).fetch(["fake://a", "fake://b", "fake://c"], _GOOD_DIGEST)
        message = str(excinfo.value)
        assert "fake://a" in message and "fake://b" in message and "fake://c" in message

    def test_message_carries_each_reason(self, molhub_home):
        fake = FakeRegistry(bodies={"a": 202, "c": b"wrong"})
        with pytest.raises(AllLocatorsFailed) as excinfo:
            _fetcher(fake, molhub_home).fetch(["fake://a", "fake://c"], _GOOD_DIGEST)
        message = str(excinfo.value)
        assert "202" in message
        assert "digest" in message.lower()

    def test_nothing_is_left_in_the_store(self, molhub_home):
        fake = FakeRegistry(bodies={"a": 202})
        with pytest.raises(AllLocatorsFailed):
            _fetcher(fake, molhub_home).fetch(["fake://a"], _GOOD_DIGEST)
        assert [p for p in molhub_home.rglob("*") if p.is_file()] == []

    def test_unknown_scheme_is_reported_not_raised_bare(self, molhub_home):
        fake = FakeRegistry(bodies={"b": _GOOD})
        path = _fetcher(fake, molhub_home).fetch(["nosuch://a", "fake://b"], _GOOD_DIGEST)
        assert path.read_bytes() == _GOOD

    def test_empty_locator_list_raises(self, molhub_home):
        with pytest.raises(AllLocatorsFailed):
            _fetcher(FakeRegistry(), molhub_home).fetch([], _GOOD_DIGEST)


class TestFetcherExtensibility:
    def test_a_third_party_driver_needs_no_molhub_change(self, molhub_home):
        """Registering a driver for a novel scheme is enough to fetch with it."""
        custom = FakeRegistry(scheme="dataverse", bodies={"doi/10.1/x": _GOOD})
        fetcher = Fetcher(
            drivers=Drivers.discover().with_driver(custom),
            blobs=BlobStore(root=molhub_home),
        )
        path = fetcher.fetch(["dataverse://doi/10.1/x"], _GOOD_DIGEST)
        assert path.read_bytes() == _GOOD


class TestUpstreamDigestEnforcement:
    """molhub's sha256 is derived, not quoted — Figshare and Zenodo publish
    only md5. Re-checking the publisher's own number on every fetch is what
    stops that derivation from being a self-referential note about one
    download."""

    def test_matching_upstream_digest_passes(self, molhub_home):
        fake = FakeRegistry(bodies={"a": _GOOD})
        upstream = f"md5:{hashlib.md5(_GOOD).hexdigest()}"
        path = _fetcher(fake, molhub_home).fetch(
            ["fake://a"], _GOOD_DIGEST, upstream_digest=upstream
        )
        assert path.read_bytes() == _GOOD

    def test_wrong_upstream_digest_is_rejected(self, molhub_home):
        """Even when the sha256 matches: the publisher disagrees, so stop."""
        fake = FakeRegistry(bodies={"a": _GOOD})
        with pytest.raises(AllLocatorsFailed):
            _fetcher(fake, molhub_home).fetch(
                ["fake://a"], _GOOD_DIGEST, upstream_digest=f"md5:{'0' * 32}"
            )

    def test_rejected_bytes_are_not_stored(self, molhub_home):
        fake = FakeRegistry(bodies={"a": _GOOD})
        with pytest.raises(AllLocatorsFailed):
            _fetcher(fake, molhub_home).fetch(
                ["fake://a"], _GOOD_DIGEST, upstream_digest=f"md5:{'0' * 32}"
            )
        assert [p for p in molhub_home.rglob("*") if p.is_file()] == []

    def test_failure_names_the_algorithm_and_both_values(self, molhub_home):
        fake = FakeRegistry(bodies={"a": _GOOD})
        with pytest.raises(AllLocatorsFailed) as excinfo:
            _fetcher(fake, molhub_home).fetch(
                ["fake://a"], _GOOD_DIGEST, upstream_digest=f"md5:{'0' * 32}"
            )
        message = str(excinfo.value)
        assert "md5" in message and "0" * 32 in message
        assert hashlib.md5(_GOOD).hexdigest() in message

    def test_absent_upstream_digest_skips_the_check(self, molhub_home):
        fake = FakeRegistry(bodies={"a": _GOOD})
        assert _fetcher(fake, molhub_home).fetch(["fake://a"], _GOOD_DIGEST).exists()

    def test_a_driver_reported_digest_is_checked_too(self, molhub_home):
        """The API's live number counts even when the caller supplied none."""
        fake = FakeRegistry(bodies={"a": _GOOD})
        fake.upstream_digest = f"md5:{'0' * 32}"
        with pytest.raises(AllLocatorsFailed, match="publisher"):
            _fetcher(fake, molhub_home).fetch(["fake://a"], _GOOD_DIGEST)

    def test_upstream_check_accepts_a_digest_object(self, molhub_home):
        fake = FakeRegistry(bodies={"a": _GOOD})
        upstream = Digest.parse(f"md5:{hashlib.md5(_GOOD).hexdigest()}")
        assert (
            _fetcher(fake, molhub_home)
            .fetch(["fake://a"], _GOOD_DIGEST, upstream_digest=upstream)
            .exists()
        )
