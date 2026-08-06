"""Molhub — the one class a user needs to know.

It composes rather than implements: :class:`~molhub.index.Index` says where an
artifact's bytes are, and :class:`~molhub.registry.fetcher.Fetcher` gets them
and proves they are the right ones. This class sends no HTTP requests of its
own and performs no verification of its own; if it did, the digest guarantee
would have two implementations and only one of them would be tested.
"""

from __future__ import annotations

from pathlib import Path

from molhub.coordinate import Coordinate
from molhub.index import Index, IndexSource
from molhub.manifest import Manifest
from molhub.registry import Fetcher

__all__ = ["Molhub"]


class Molhub:
    """Resolve, search, and fetch artifacts by coordinate.

    Args:
        index: Where manifests come from. Accepts an :class:`Index`, an
            :class:`IndexSource`, a directory path, or ``None`` to use
            ``$MOLHUB_INDEX`` and then the bundled snapshot.
        fetcher: How bytes are retrieved. Defaults to a :class:`Fetcher` with
            the discovered drivers and the shared content-addressed cache.

    Example::

        hub = Molhub()
        paths = hub.fetch("dataset:molcrafts/qm9@v2")
        print(paths["main"])
    """

    def __init__(
        self,
        index: Index | IndexSource | str | Path | None = None,
        *,
        fetcher: Fetcher | None = None,
    ) -> None:
        self._index = index if isinstance(index, Index) else Index.load(index)
        self._fetcher = fetcher or Fetcher()

    @property
    def index(self) -> Index:
        """The loaded catalogue."""
        return self._index

    def resolve(self, coordinate: str | Coordinate) -> Manifest:
        """Return the manifest for *coordinate* without downloading anything.

        Args:
            coordinate: Full or shorthand coordinate.

        Returns:
            The :class:`~molhub.manifest.Manifest`.

        Raises:
            InvalidCoordinate: If the coordinate is malformed.
            UnknownArtifact: If the index has no such coordinate.
        """
        return self._index.get(coordinate)

    def fetch(
        self, coordinate: str | Coordinate, *, roles: list[str] | None = None
    ) -> dict[str, Path]:
        """Retrieve an artifact's files, verified, and return them by role.

        Each file is checked against the sha256 in its manifest **and** against
        whatever digest the publisher declared, before it is stored. A cached
        file is returned without any network access.

        Args:
            coordinate: Full or shorthand coordinate.
            roles: Restrict to these roles; ``None`` fetches every one.

        Returns:
            Mapping of role to the local path holding that file's bytes.

        Raises:
            UnknownArtifact: If the index has no such coordinate.
            KeyError: If a requested role is not declared by the manifest.
            AllLocatorsFailed: If no locator for some file yielded bytes that
                match its declared digest.
        """
        manifest = self.resolve(coordinate)
        wanted = list(manifest.artifacts) if roles is None else roles
        fetched = {}
        for role in wanted:
            artifact = manifest.artifact(role)
            fetched[role] = self._fetcher.fetch(
                artifact.locators,
                artifact.digest,
                upstream_digest=artifact.upstream_digest,
            )
        return fetched

    def search(self, *, kind: str | None = None, query: str | None = None) -> list[Manifest]:
        """Return matching manifests, ordered by coordinate.

        Args:
            kind: Restrict to ``dataset``, ``model``, or ``plugin``.
            query: Case-insensitive substring over coordinate, title,
                description and declared targets.
        """
        return self._index.search(kind=kind, query=query)

    def __len__(self) -> int:
        return len(self._index)

    def __repr__(self) -> str:
        return f"Molhub({len(self._index)} artifacts)"
