"""Index — the catalogue of manifests a client resolves coordinates against.

Static files, no service. A directory of YAML manifests is a complete, usable
index; the published CDN bundle is the same content aggregated for convenience.
That is what keeps early operating cost near zero and what makes offline use —
common on compute clusters — work without a special mode.

Sources are tried in order:

1. ``$MOLHUB_INDEX`` — a local directory. Offline work, development, and the
   test suite all use this.
2. The bundled snapshot shipped inside the package, so a fresh install can
   resolve the built-in datasets with no network at all.

A remote CDN source belongs here too and is deliberately absent until there is
a published index to point at; adding it is one more entry in this list.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from molhub.coordinate import Coordinate
from molhub.manifest import Manifest

__all__ = ["IndexSource", "Index", "UnknownArtifact"]

ENV_VAR = "MOLHUB_INDEX"
_BUNDLED = Path(__file__).parent / "index_data"


class UnknownArtifact(KeyError):
    """No manifest in the index matches the requested coordinate."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self._message = message

    def __str__(self) -> str:
        return self._message


class IndexSource:
    """A directory of manifests laid out as ``<kind>/<namespace>/<name>/<version>.yaml``.

    Args:
        root: Directory to read from.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser()

    @classmethod
    def resolve(cls, root: str | Path | None = None) -> "IndexSource":
        """Pick an index source: explicit path, then ``$MOLHUB_INDEX``, then bundled."""
        if root is not None:
            return cls(root)
        if configured := os.environ.get(ENV_VAR):
            return cls(configured)
        return cls(_BUNDLED)

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
        return f"IndexSource({str(self._root)!r})"


class Index:
    """Every manifest a source offers, loaded and queryable.

    Args:
        manifests: The manifests to serve, keyed by canonical coordinate.
    """

    def __init__(self, manifests: dict[str, Manifest] | None = None) -> None:
        self._by_coordinate: dict[str, Manifest] = dict(manifests or {})

    @classmethod
    def load(cls, source: IndexSource | str | Path | None = None) -> "Index":
        """Load every manifest from *source*.

        Args:
            source: An :class:`IndexSource`, a directory path, or ``None`` to
                use :meth:`IndexSource.resolve`.

        Returns:
            The loaded index; empty when the source directory is absent.

        Raises:
            InvalidManifest: If any manifest in the source is malformed. A bad
                entry fails loudly rather than being skipped — a silently
                dropped dataset is worse than a broken index.
        """
        if not isinstance(source, IndexSource):
            source = IndexSource.resolve(source)
        manifests = {}
        for path in source.manifest_paths():
            manifest = Manifest.from_path(path)
            manifests[manifest.coordinate.canonical] = manifest
        return cls(manifests)

    def get(self, coordinate: Coordinate | str) -> Manifest:
        """Return the manifest for *coordinate*.

        Raises:
            UnknownArtifact: If the index has no such coordinate. The message
                suggests other versions of the same artifact when they exist,
                since a stale version pin is the likeliest cause.
        """
        coord = Coordinate.coerce(coordinate)
        try:
            return self._by_coordinate[coord.canonical]
        except KeyError:
            raise UnknownArtifact(self._not_found_message(coord)) from None

    def _not_found_message(self, coord: Coordinate) -> str:
        siblings = sorted(
            manifest.coordinate.version
            for manifest in self._by_coordinate.values()
            if manifest.coordinate.unversioned == coord.unversioned
        )
        if siblings:
            return (
                f"{coord.canonical} is not in the index, but these versions are: "
                f"{', '.join(siblings)}."
            )
        return f"{coord.canonical} is not in the index ({len(self)} artifacts loaded)."

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
