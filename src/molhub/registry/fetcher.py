"""Fetcher — ordered fallback across locators, with mandatory verification.

The guarantee this class exists to provide: **a path it returns holds bytes
whose sha256 equals the digest you asked for.** Everything else — which mirror
answered, how many were tried — is an implementation detail.

Failure handling is deliberate. A bad status or a digest mismatch moves on to
the next locator; a mismatch in particular is *not* retried against the same
locator, because it means that mirror is serving the wrong content.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from molhub.registry.blobs import BlobStore
from molhub.registry.digest import Digest
from molhub.registry.drivers import Drivers
from molhub.registry.errors import AllLocatorsFailed, DigestMismatch, RegistryError
from molhub.registry.locator import Locator

__all__ = ["Fetcher"]


class Fetcher:
    """Retrieves verified artifact bytes into the content-addressed store.

    Args:
        drivers: Drivers to resolve locators with. Defaults to
            :meth:`Drivers.discover`.
        blobs: Where verified bytes land. Defaults to a store rooted at
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
        """The store verified bytes are written to."""
        return self._blobs

    def fetch(self, locators: Sequence[str | Locator], digest: Digest) -> Path:
        """Return a local path holding the bytes matching *digest*.

        Tries each locator in order and returns as soon as one yields bytes
        that verify. A cached blob short-circuits the whole thing without any
        network access.

        Args:
            locators: Candidate sources, most-preferred first.
            digest: The digest the bytes must have.

        Returns:
            Path to the verified blob inside the store.

        Raises:
            AllLocatorsFailed: If no locator produced verifying bytes. The
                message carries every locator with its own reason.
        """
        if self._blobs.has(digest):
            return self._blobs.path_for(digest)

        reasons: list[tuple[str, BaseException]] = []
        for candidate in locators:
            locator = Locator.coerce(candidate)
            try:
                return self._fetch_one(locator, digest)
            except RegistryError as error:
                reasons.append((str(locator), error))
            except OSError as error:
                reasons.append((str(locator), error))
        raise AllLocatorsFailed(reasons)

    def _fetch_one(self, locator: Locator, digest: Digest) -> Path:
        """Resolve, transfer, verify, and store one locator's bytes."""
        driver = self._drivers.for_scheme(locator.scheme)
        remotes = driver.resolve(locator)
        if not remotes:
            raise RegistryError(f"{locator} resolved to no files.")

        partial = self._blobs.temp_path(digest)
        partial.parent.mkdir(parents=True, exist_ok=True)
        try:
            driver.fetch(remotes[0], partial)
            actual = Digest.of_file(partial)
            if not actual.matches(digest):
                raise DigestMismatch(
                    f"{locator} served bytes with digest {actual}, expected {digest}. "
                    "The mirror is serving the wrong content; not retrying it."
                )
            return self._blobs.put(partial, digest)
        finally:
            partial.unlink(missing_ok=True)
