"""Tests for Fetcher — ordered fallback, cache reuse, optional version check.

Two guarantees, and they are separate on purpose:

* Always — a returned path holds a complete file from a 200 response. This
  comes from the transport contract and holds with no digest in sight.
* When a digest is supplied — the file also matches it, confirming upstream
  still serves the version the manifest names.
"""

from __future__ import annotations

import hashlib

import pytest

from molhub.sources.blobs import BlobStore
from molhub.sources.digest import Digest
from molhub.sources.drivers import Drivers
from molhub.sources.errors import AllLocatorsFailed
from molhub.sources.fetcher import Fetcher

from .conftest import FakeSource

_GOOD = b"good bytes"
_MD5 = f"md5:{hashlib.md5(_GOOD).hexdigest()}"
KEY = "dataset:molcrafts/qm9@v2/main"


def _fetcher(fake: FakeSource, home) -> Fetcher:
    return Fetcher(drivers=Drivers.of(fake), blobs=BlobStore(root=home))


class TestFetcherSuccess:
    def test_returns_the_cache_path_for_the_key(self, molhub_home):
        fake = FakeSource(bodies={"a": _GOOD})
        path = _fetcher(fake, molhub_home).fetch(["fake://a"], KEY)
        assert path == BlobStore(root=molhub_home).path_for(KEY)

    def test_content_is_correct(self, molhub_home):
        fake = FakeSource(bodies={"a": _GOOD})
        assert _fetcher(fake, molhub_home).fetch(["fake://a"], KEY).read_bytes() == _GOOD

    def test_works_with_no_digest_at_all(self, molhub_home):
        """Platforms that publish nothing still get a usable fetch."""
        fake = FakeSource(bodies={"a": _GOOD})
        assert _fetcher(fake, molhub_home).fetch(["fake://a"], KEY).exists()

    def test_accepts_locator_objects(self, molhub_home):
        from molhub.sources.locator import Locator

        fake = FakeSource(bodies={"a": _GOOD})
        assert _fetcher(fake, molhub_home).fetch([Locator.parse("fake://a")], KEY).exists()

    def test_stops_at_the_first_success(self, molhub_home):
        fake = FakeSource(bodies={"a": _GOOD, "b": _GOOD})
        _fetcher(fake, molhub_home).fetch(["fake://a", "fake://b"], KEY)
        assert fake.network_calls == 1


class TestFetcherCache:
    def test_second_fetch_makes_no_network_call(self, molhub_home):
        fake = FakeSource(bodies={"a": _GOOD})
        fetcher = _fetcher(fake, molhub_home)
        first = fetcher.fetch(["fake://a"], KEY)
        calls = fake.network_calls
        assert fetcher.fetch(["fake://a"], KEY) == first
        assert fake.network_calls == calls

    def test_a_fresh_fetcher_also_hits_the_shared_cache(self, molhub_home):
        _fetcher(FakeSource(bodies={"a": _GOOD}), molhub_home).fetch(["fake://a"], KEY)
        cold = FakeSource(bodies={"a": _GOOD})
        _fetcher(cold, molhub_home).fetch(["fake://a"], KEY)
        assert cold.network_calls == 0

    def test_a_different_key_is_fetched_separately(self, molhub_home):
        fake = FakeSource(bodies={"a": _GOOD})
        fetcher = _fetcher(fake, molhub_home)
        fetcher.fetch(["fake://a"], "dataset:x/y@1/main")
        fetcher.fetch(["fake://a"], "dataset:x/y@1/exclude")
        assert fake.network_calls == 2


class TestFetcherFallback:
    def test_falls_through_a_bad_status(self, molhub_home):
        fake = FakeSource(bodies={"a": 202, "b": _GOOD})
        assert (
            _fetcher(fake, molhub_home).fetch(["fake://a", "fake://b"], KEY).read_bytes() == _GOOD
        )

    def test_order_is_honoured(self, molhub_home):
        fake = FakeSource(bodies={"a": _GOOD, "b": _GOOD})
        _fetcher(fake, molhub_home).fetch(["fake://b", "fake://a"], KEY)
        assert fake.fetch_calls == ["fake://b"]

    def test_nothing_partial_is_left_behind(self, molhub_home):
        fake = FakeSource(bodies={"a": 202})
        with pytest.raises(AllLocatorsFailed):
            _fetcher(fake, molhub_home).fetch(["fake://a"], KEY)
        assert [p for p in molhub_home.rglob("*") if p.is_file()] == []


class TestFetcherExhaustion:
    def test_raises_when_every_locator_fails(self, molhub_home):
        fake = FakeSource(bodies={"a": 202, "b": 500})
        with pytest.raises(AllLocatorsFailed):
            _fetcher(fake, molhub_home).fetch(["fake://a", "fake://b"], KEY)

    def test_message_names_every_locator_and_reason(self, molhub_home):
        fake = FakeSource(bodies={"a": 202, "b": 500})
        with pytest.raises(AllLocatorsFailed) as excinfo:
            _fetcher(fake, molhub_home).fetch(["fake://a", "fake://b"], KEY)
        message = str(excinfo.value)
        assert "fake://a" in message and "fake://b" in message
        assert "202" in message and "500" in message

    def test_unknown_scheme_is_reported_not_raised_bare(self, molhub_home):
        fake = FakeSource(bodies={"b": _GOOD})
        assert _fetcher(fake, molhub_home).fetch(["nosuch://a", "fake://b"], KEY).exists()

    def test_empty_locator_list_raises(self, molhub_home):
        with pytest.raises(AllLocatorsFailed):
            _fetcher(FakeSource(), molhub_home).fetch([], KEY)


class TestVersionCheck:
    """A digest is the platform's own published value. It answers one question:
    does upstream still serve the version this manifest names?"""

    def test_matching_digest_passes(self, molhub_home):
        fake = FakeSource(bodies={"a": _GOOD})
        assert _fetcher(fake, molhub_home).fetch(["fake://a"], KEY, digest=_MD5).exists()

    def test_accepts_a_digest_object(self, molhub_home):
        fake = FakeSource(bodies={"a": _GOOD})
        digest = Digest.parse(_MD5)
        assert _fetcher(fake, molhub_home).fetch(["fake://a"], KEY, digest=digest).exists()

    def test_sha256_digest_is_equally_acceptable(self, molhub_home):
        """HuggingFace publishes sha256; the field takes whatever upstream gives."""
        fake = FakeSource(bodies={"a": _GOOD})
        sha = f"sha256:{hashlib.sha256(_GOOD).hexdigest()}"
        assert _fetcher(fake, molhub_home).fetch(["fake://a"], KEY, digest=sha).exists()

    def test_mismatch_is_rejected(self, molhub_home):
        fake = FakeSource(bodies={"a": b"a different version"})
        with pytest.raises(AllLocatorsFailed):
            _fetcher(fake, molhub_home).fetch(["fake://a"], KEY, digest=_MD5)

    def test_mismatched_file_is_not_cached(self, molhub_home):
        fake = FakeSource(bodies={"a": b"a different version"})
        with pytest.raises(AllLocatorsFailed):
            _fetcher(fake, molhub_home).fetch(["fake://a"], KEY, digest=_MD5)
        assert [p for p in molhub_home.rglob("*") if p.is_file()] == []

    def test_message_says_the_manifest_is_what_needs_updating(self, molhub_home):
        fake = FakeSource(bodies={"a": b"a different version"})
        with pytest.raises(AllLocatorsFailed) as excinfo:
            _fetcher(fake, molhub_home).fetch(["fake://a"], KEY, digest=_MD5)
        assert "update the manifest" in str(excinfo.value)

    def test_a_second_locator_is_still_tried(self, molhub_home):
        fake = FakeSource(bodies={"a": b"stale", "b": _GOOD})
        path = _fetcher(fake, molhub_home).fetch(["fake://a", "fake://b"], KEY, digest=_MD5)
        assert path.read_bytes() == _GOOD


class TestFetcherExtensibility:
    def test_a_third_party_driver_needs_no_molhub_change(self, molhub_home):
        custom = FakeSource(scheme="dataverse", bodies={"doi/10.1/x": _GOOD})
        fetcher = Fetcher(
            drivers=Drivers.discover().with_driver(custom),
            blobs=BlobStore(root=molhub_home),
        )
        assert fetcher.fetch(["dataverse://doi/10.1/x"], KEY).read_bytes() == _GOOD
