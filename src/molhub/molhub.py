"""Molhub — the one class a user needs to know.

It composes rather than implements: :class:`~molhub.registry.Registry` says where an
artifact's bytes are, and :class:`~molhub.sources.fetcher.Fetcher` gets them
under the transport contract, checking the manifest's digest when it records
one. This class sends no HTTP requests of its own and performs no checking of
its own; if it did, the transport contract would have two implementations and
only one of them would be tested.
"""

from __future__ import annotations

from pathlib import Path

from molhub.coordinate import Coordinate
from molhub.manifest import Manifest
from molhub.registry import Registry, RegistrySource
from molhub.sources import Fetcher

__all__ = ["Molhub"]


class Molhub:
    """Resolve, search, and fetch artifacts by coordinate.

    Args:
        registry: Where manifests come from. Accepts an :class:`Registry`, an
            :class:`RegistrySource`, a directory path, or ``None`` to use
            ``$MOLHUB_REGISTRY`` and then the bundled snapshot.
        fetcher: How bytes are retrieved. Defaults to a :class:`Fetcher` with
            the discovered drivers and the shared cache under ``$MOLHUB_HOME``,
            which files each artifact by coordinate and role.

    Example::

        hub = Molhub()
        paths = hub.fetch("dataset:molcrafts/qm9@v2")
        print(paths["main"])
    """

    def __init__(
        self,
        registry: Registry | RegistrySource | str | Path | None = None,
        *,
        fetcher: Fetcher | None = None,
    ) -> None:
        self._registry = registry if isinstance(registry, Registry) else Registry.load(registry)
        self._fetcher = fetcher or Fetcher()

    @property
    def registry(self) -> Registry:
        """The loaded registry."""
        return self._registry

    def resolve(self, coordinate: str | Coordinate) -> Manifest:
        """Return the manifest for *coordinate* without downloading anything.

        Args:
            coordinate: Full or shorthand coordinate.

        Returns:
            The :class:`~molhub.manifest.Manifest`.

        Raises:
            InvalidCoordinate: If the coordinate is malformed.
            UnknownArtifact: If the registry has no such coordinate.
        """
        return self._registry.get(coordinate)

    def fetch(
        self, coordinate: str | Coordinate, *, roles: list[str] | None = None
    ) -> dict[str, Path]:
        """Retrieve an artifact's files, verified, and return them by role.

        When the manifest records the platform's published digest, the
        transferred file is checked against it — that confirms upstream still
        serves the version this manifest names. A cached file is returned
        without any network access.

        Args:
            coordinate: Full or shorthand coordinate.
            roles: Restrict to these roles; ``None`` fetches every one.

        Returns:
            Mapping of role to the local path holding that file's bytes.

        Raises:
            UnknownArtifact: If the registry has no such coordinate.
            KeyError: If a requested role is not declared by the manifest.
            AllLocatorsFailed: If no locator for some file yielded a usable
                transfer.
        """
        manifest = self.resolve(coordinate)
        wanted = list(manifest.artifacts) if roles is None else roles
        fetched = {}
        for role in wanted:
            artifact = manifest.artifact(role)
            fetched[role] = self._fetcher.fetch(
                artifact.locators,
                f"{manifest.coordinate.cache_path()}/{role}",
                digest=artifact.digest,
            )
        return fetched

    def search(self, *, kind: str | None = None, query: str | None = None) -> list[Manifest]:
        """Return matching manifests, ordered by coordinate.

        Args:
            kind: Restrict to ``dataset``, ``model``, or ``plugin``.
            query: Case-insensitive substring over coordinate, title,
                description and declared targets.
        """
        return self._registry.search(kind=kind, query=query)

    def __len__(self) -> int:
        return len(self._registry)

    def __repr__(self) -> str:
        return f"Molhub({len(self._registry)} artifacts)"
