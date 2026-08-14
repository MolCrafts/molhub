"""Python-native dataset declaration: manifest, decorator, and catalog.

This module is the L3 declaration surface. It attaches a frozen bibliographic
manifest to a class and lets a caller keep an immutable catalog of those
classes. It does not fetch bytes, parse frames, or talk to the registry.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from molhub.coordinate import Coordinate, InvalidCoordinate

__all__ = [
    "DatasetManifest",
    "UnknownDataset",
    "dataset",
    "Datasets",
]


class UnknownDataset(KeyError):
    """The catalog has no class for the requested coordinate.

    Args:
        message: Explanation listing known canonical coordinates.
    """

    def __str__(self) -> str:
        return self.args[0] if self.args else super().__str__()


@dataclass(frozen=True)
class DatasetManifest:
    """Frozen bibliographic record for one dataset class.

    The identity is a :class:`~molhub.coordinate.Coordinate` with ``kind``
    fixed to ``dataset``. Layout of scientific targets is *not* stored here;
    classes keep using :class:`~molhub.dataset.protocol.TargetSchema`.

    Args:
        coordinate: Canonical identity. Must have ``kind="dataset"``.
        description: Short prose description.
        license: SPDX id or other license label, if known.
        homepage: Project homepage URL, if known.
        citation: Citation text or DOI URL, if known.
        tags: Subject tags; stored as a tuple.

    Raises:
        InvalidCoordinate: If ``coordinate.kind`` is not ``dataset``.
    """

    coordinate: Coordinate
    description: str = ""
    license: str | None = None
    homepage: str | None = None
    citation: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.coordinate.kind != "dataset":
            raise InvalidCoordinate(
                f"DatasetManifest requires kind 'dataset', got {self.coordinate.kind!r}."
            )
        object.__setattr__(self, "tags", tuple(self.tags))

    @property
    def canonical(self) -> str:
        """Forwarded :attr:`Coordinate.canonical`; not part of ``asdict``."""
        return self.coordinate.canonical


def dataset(
    *,
    name: str,
    namespace: str,
    version: str,
    description: str = "",
    license: str | None = None,
    homepage: str | None = None,
    citation: str | None = None,
    tags: Iterable[str] = (),
):
    """Attach a :class:`DatasetManifest` to a class as ``Cls.manifest``.

    Keyword-only. ``kind`` is not a parameter; identity is always
    ``dataset:<namespace>/<name>@<version>``. The class is returned unchanged
    (same object); ``__init__`` is not wrapped. Decorating does no IO.

    Args:
        name: Artifact name segment (Coordinate rules).
        namespace: Owner segment (Coordinate rules).
        version: Version label (Coordinate rules).
        description: Short prose description.
        license: SPDX id or other license label.
        homepage: Project homepage URL.
        citation: Citation text or DOI URL.
        tags: Subject tags.

    Returns:
        A class decorator that sets ``manifest`` and returns the class.

    Raises:
        InvalidCoordinate: If any identity segment fails Coordinate rules.
    """

    def decorate(cls: type) -> type:
        coordinate = Coordinate(
            kind="dataset",
            namespace=namespace,
            name=name,
            version=version,
        )
        cls.manifest = DatasetManifest(
            coordinate=coordinate,
            description=description,
            license=license,
            homepage=homepage,
            citation=citation,
            tags=tuple(tags),
        )
        return cls

    return decorate


class Datasets:
    """Immutable catalog of decorated dataset classes, keyed by canonical.

    Later :meth:`with_dataset` wins for the same canonical. The receiver is
    never mutated. The decorator does not write into a process-global table.

    Args:
        classes: Decorated classes (or any type with a ``DatasetManifest``
            class attribute).
    """

    def __init__(self, classes: Iterable[type] = ()) -> None:
        by_canonical: dict[str, type] = {}
        order: list[Coordinate] = []
        for cls in classes:
            self._insert(by_canonical, order, cls)
        self._by_canonical = by_canonical
        self._order = tuple(order)

    @staticmethod
    def _manifest_of(cls: type) -> DatasetManifest:
        manifest = getattr(cls, "manifest", None)
        if not isinstance(manifest, DatasetManifest):
            raise TypeError(f"{cls!r} has no DatasetManifest; decorate it with @dataset.")
        if manifest.coordinate.kind != "dataset":
            raise InvalidCoordinate(
                f"Datasets only accept kind 'dataset', got {manifest.coordinate.kind!r}."
            )
        return manifest

    def _insert(
        self,
        by_canonical: dict[str, type],
        order: list[Coordinate],
        cls: type,
    ) -> None:
        manifest = self._manifest_of(cls)
        key = manifest.coordinate.canonical
        if key in by_canonical:
            by_canonical[key] = cls
            return
        by_canonical[key] = cls
        order.append(manifest.coordinate)

    @classmethod
    def of(cls, *classes: type) -> Datasets:
        """Build a catalog from the given classes, in order."""
        return cls(classes)

    def with_dataset(self, cls: type) -> Datasets:
        """Return a **new** catalog with *cls* added or overriding.

        The receiver is left unchanged.
        """
        return Datasets([self._by_canonical[c.canonical] for c in self._order] + [cls])

    def resolve(self, coordinate: str | Coordinate) -> type:
        """Return the class registered for *coordinate*.

        Args:
            coordinate: Full form, shorthand, or a Coordinate. ``kind`` other
                than ``dataset`` is rejected.

        Returns:
            The decorated class.

        Raises:
            InvalidCoordinate: If *coordinate* is malformed or not a dataset.
            UnknownDataset: If this catalog has no such class.
        """
        coord = Coordinate.coerce(coordinate)
        if coord.kind != "dataset":
            raise InvalidCoordinate(
                f"Datasets.resolve only accepts kind 'dataset', got {coord.kind!r}."
            )
        try:
            return self._by_canonical[coord.canonical]
        except KeyError:
            available = ", ".join(c.canonical for c in self._order) or "none"
            raise UnknownDataset(
                f"{coord.canonical} is not in the catalog. Available: {available}."
            ) from None

    def coordinates(self) -> tuple[Coordinate, ...]:
        """Coordinates in insertion order (later-write-wins keeps first slot)."""
        return self._order
