"""Registry — the registry of manifests a client resolves coordinates against.

The built-in catalog is Python: each dataset module declares a ``MANIFEST``
and :meth:`Registry.builtin` collects them. A fresh install therefore
resolves the built-in datasets with no config file and no network.

``$MOLHUB_REGISTRY`` still names an optional directory of extra YAML
manifests (tests and a local overlay). The project itself ships none.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from molhub.coordinate import Coordinate
from molhub.manifest import Manifest

__all__ = ["RegistrySource", "Registry", "UnknownArtifact"]

ENV_VAR = "MOLHUB_REGISTRY"


class UnknownArtifact(KeyError):
    """No manifest in the registry matches the requested coordinate."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self._message = message

    def __str__(self) -> str:
        return self._message


class RegistrySource:
    """A directory of manifests laid out as ``<kind>/<namespace>/<name>/<version>.yaml``.

    Args:
        root: Directory to read from.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser()

    @classmethod
    def resolve(cls, root: str | Path | None = None) -> "RegistrySource":
        """Pick a YAML overlay: explicit path, then ``$MOLHUB_REGISTRY``.

        There is no bundled YAML directory. The package catalog is
        :meth:`Registry.builtin`.
        """
        if root is not None:
            return cls(root)
        if configured := os.environ.get(ENV_VAR):
            return cls(configured)
        raise FileNotFoundError(
            f"{ENV_VAR} is unset. The package catalog is Registry.builtin(); "
            "a directory path is only needed for a local YAML overlay."
        )

    @property
    def root(self) -> Path:
        """The directory this source reads."""
        return self._root

    def path_for(self, coordinate: Coordinate) -> Path:
        """Where *coordinate*'s manifest would live, whether or not it exists."""
        return self._root / coordinate.relative_path()

    def manifest_paths(self) -> Iterator[Path]:
        """Yield every manifest file in the source, in sorted order."""
        if not self._root.is_dir():
            return
        yield from sorted(self._root.rglob("*.yaml"))

    def __repr__(self) -> str:
        return f"RegistrySource({str(self._root)!r})"


class Registry:
    """Every manifest a source offers, loaded and queryable.

    Args:
        manifests: The manifests to serve, keyed by canonical coordinate.
    """

    def __init__(self, manifests: dict[str, Manifest] | None = None) -> None:
        self._by_coordinate: dict[str, Manifest] = dict(manifests or {})

    @classmethod
    def builtin(cls) -> "Registry":
        """The package catalog: every ``MANIFEST`` declared in Python."""
        from molhub.catalog import builtin_manifests

        return cls({manifest.coordinate.canonical: manifest for manifest in builtin_manifests()})

    def snapshot(self) -> dict[str, object]:
        """JSON-serialisable aggregate for the frontend and other non-Python clients.

        Built from :meth:`Manifest.to_entry`. The Web build calls this through
        the Python package — it does not walk a directory of YAML.
        """
        return {
            "schema_version": 1,
            "entries": [manifest.to_entry() for manifest in self.search()],
        }

    @classmethod
    def load(cls, source: Registry | RegistrySource | str | Path | None = None) -> "Registry":
        """Load a registry.

        Args:
            source: An already-built :class:`Registry` (returned as-is), an
                :class:`RegistrySource`, a directory of extra YAML manifests,
                or ``None``. ``None`` uses ``$MOLHUB_REGISTRY`` when set,
                otherwise :meth:`builtin`.

        Returns:
            The loaded registry; empty when a given source directory is absent.

        Raises:
            InvalidManifest: If any YAML overlay in *source* is malformed.
        """
        if isinstance(source, Registry):
            return source
        if source is None:
            if not os.environ.get(ENV_VAR):
                return cls.builtin()
            source = RegistrySource.resolve()
        if not isinstance(source, RegistrySource):
            source = RegistrySource.resolve(source)
        manifests = {}
        for path in source.manifest_paths():
            manifest = Manifest.from_path(path)
            manifests[manifest.coordinate.canonical] = manifest
        return cls(manifests)

    def get(self, coordinate: Coordinate | str) -> Manifest:
        """Return the manifest for *coordinate*.

        Raises:
            UnknownArtifact: If the registry has no such coordinate. The message
                suggests other versions of the same artifact when they exist,
                since a stale version pin is the likeliest cause.
        """
        coord = Coordinate.coerce(coordinate)
        try:
            return self._by_coordinate[coord.canonical]
        except KeyError:
            raise UnknownArtifact(self._not_found_message(coord)) from None

    def versions(self, unversioned: str) -> tuple[str, ...]:
        """Every version this registry declares for one artifact.

        The scan :meth:`get`'s not-found message already performs, said out
        loud: defaulting a revision means asking which versions exist, and a
        caller that asked before the miss should get the same answer the miss
        would have suggested.

        Args:
            unversioned: An artifact without its version, in
                :attr:`Coordinate.unversioned` form — ``dataset:themol/mbis``.
                Not a :class:`~molhub.coordinate.Coordinate`, which cannot be
                built without the version this asks about.

        Returns:
            The declared version labels, sorted lexically; empty when the
            registry declares none. Ordering versions *meaningfully* is the
            caller's problem — :class:`~molhub.loader.naming.DatasetName` does
            it numerically and refuses when it cannot — so this reports rather
            than ranks.
        """
        return tuple(
            sorted(
                manifest.coordinate.version
                for manifest in self._by_coordinate.values()
                if manifest.coordinate.unversioned == unversioned
            )
        )

    def _not_found_message(self, coord: Coordinate) -> str:
        siblings = self.versions(coord.unversioned)
        if siblings:
            return (
                f"{coord.canonical} is not in the registry, but these versions are: "
                f"{', '.join(siblings)}."
            )
        return f"{coord.canonical} is not in the registry ({len(self)} artifacts loaded)."

    def search(self, *, kind: str | None = None, query: str | None = None) -> list[Manifest]:
        """Return matching manifests, ordered by coordinate.

        Args:
            kind: Restrict to one artifact kind.
            query: Case-insensitive substring over coordinate, title,
                description and declared graph-level targets.
        """
        found = [
            manifest
            for manifest in self._by_coordinate.values()
            if (kind is None or manifest.coordinate.kind == kind)
            and (query is None or manifest.matches(query))
        ]
        return sorted(found, key=lambda manifest: manifest.coordinate.canonical)

    def __len__(self) -> int:
        return len(self._by_coordinate)

    def __iter__(self) -> Iterator[Manifest]:
        return iter(self.search())

    def __contains__(self, coordinate: Coordinate | str) -> bool:
        try:
            return Coordinate.coerce(coordinate).canonical in self._by_coordinate
        except ValueError:
            return False
