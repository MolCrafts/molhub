"""Fetcher — ordered fallback across locators, with an optional version check.

What this class guarantees, always: **a path it returns holds a complete file
that the server returned with a 200.** Truncated and error responses never
reach it — that comes from the transport contract in
:mod:`molhub.sources.drivers.https`, not from any digest.

When the caller supplies a digest, it is additionally checked. A digest here is
the platform's own published value, and the question it answers is "does
upstream still serve the version this manifest names?". A mismatch means
upstream changed and the manifest needs updating, so the fetcher stops using
that mirror rather than retrying it. Platforms that publish nothing simply get
no check.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from molhub.sources.blobs import BlobStore
from molhub.sources.digest import Digest
from molhub.sources.drivers import Drivers
from molhub.sources.errors import AllLocatorsFailed, DigestMismatch, SourceError
from molhub.sources.locator import Locator

__all__ = ["Fetcher"]


class Fetcher:
    """Retrieves artifact bytes into the local cache.

    Args:
        drivers: Drivers to resolve locators with. Defaults to
            :meth:`Drivers.discover`.
        blobs: Where fetched bytes land. Defaults to a store rooted at
            ``$MOLHUB_HOME``.
    """

    def __init__(
        self,
        *,
        drivers: Drivers | None = None,
        blobs: BlobStore | None = None,
    ) -> None:
        self._drivers = drivers or Drivers.discover()
        self._blobs = blobs or BlobStore()

    @property
    def blobs(self) -> BlobStore:
        """The store fetched bytes are written to."""
        return self._blobs

    def fetch(
        self,
        locators: Sequence[str | Locator],
        key: str,
        *,
        digest: Digest | str | None = None,
    ) -> Path:
        """Return a local path holding the artifact's bytes.

        Tries each locator in order and returns as soon as one succeeds. A file
        already in the cache short-circuits the whole thing without any network
        access.

        Args:
            locators: Candidate sources, most-preferred first.
            key: Cache key identifying this file — in practice a coordinate
                plus a role, so re-fetching the same manifest entry is free.
            digest: The platform's published digest for this file, if it
                publishes one. When given, transferred bytes must match it;
                when omitted, no digest check happens.

        Returns:
            Path to the cached file.

        Raises:
            AllLocatorsFailed: If no locator produced a usable file. The
                message carries every locator with its own reason.
        """
        cached = self._blobs.path_for(key)
        if self._blobs.has(key):
            return cached

        expected = Digest.parse(digest) if isinstance(digest, str) else digest
        reasons: list[tuple[str, BaseException]] = []
        for candidate in locators:
            locator = Locator.coerce(candidate)
            try:
                return self._fetch_one(locator, key, expected)
            except (SourceError, OSError) as error:
                reasons.append((str(locator), error))
        raise AllLocatorsFailed(reasons)

    def _fetch_one(self, locator: Locator, key: str, expected: Digest | None) -> Path:
        """Resolve, transfer, optionally verify, and store one locator's bytes."""
        driver = self._drivers.for_scheme(locator.scheme)
        remotes = driver.resolve(locator)
        if not remotes:
            raise SourceError(f"{locator} resolved to no files.")

        partial = self._blobs.temp_path(key)
        partial.parent.mkdir(parents=True, exist_ok=True)
        try:
            driver.fetch(remotes[0], partial)
            if expected is not None:
                actual = Digest.of_file(partial, algorithm=expected.algorithm)
                if not actual.matches(expected):
                    raise DigestMismatch(
                        f"{locator} served a file whose {expected.algorithm} is "
                        f"{actual.hexdigest}, but the manifest names the version with "
                        f"{expected.hexdigest}. Upstream changed — update the manifest "
                        "rather than this mirror."
                    )
            return self._blobs.put(partial, key)
        finally:
            partial.unlink(missing_ok=True)
