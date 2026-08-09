"""Coordinate — molhub's own, permanently stable name for an artifact.

    <kind>:<namespace>/<name>@<version>

    dataset:molcrafts/qm9@v2
    model:molcrafts/mace-mp-0@1.0
    plugin:molcrafts/molvis-render@0.3.1

The whole point of this layer is that a coordinate outlives the locators it
resolves to. Upstream can rename a repository, add a mirror, or gate a file;
the manifest changes and the coordinate does not, so user code does not either.

The version is **not** optional. Omitting it would make "reproducible" a
promise molhub cannot keep, and tightening the rule later would be a breaking
change — so it is rejected from the start.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["Coordinate", "InvalidCoordinate"]

DEFAULT_KIND = "dataset"
DEFAULT_NAMESPACE = "molcrafts"

KINDS: frozenset[str] = frozenset({"dataset", "model", "plugin"})

_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class InvalidCoordinate(ValueError):
    """A coordinate string does not match ``kind:namespace/name@version``."""


@dataclass(frozen=True)
class Coordinate:
    """A stable identifier for one version of one artifact.

    Attributes:
        kind: ``dataset``, ``model``, or ``plugin``.
        namespace: Owner segment, e.g. ``molcrafts``.
        name: Artifact name within the namespace.
        version: Version label; opaque to molhub beyond its character set.
    """

    kind: str
    namespace: str
    name: str
    version: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise InvalidCoordinate(f"Unknown kind {self.kind!r}; expected one of {sorted(KINDS)}.")
        for label, value in (("namespace", self.namespace), ("name", self.name)):
            if not _SEGMENT.match(value):
                raise InvalidCoordinate(
                    f"Invalid {label} {value!r}; expected lower-case letters, "
                    "digits and hyphens, starting with a letter or digit."
                )
        if not _VERSION.match(self.version):
            raise InvalidCoordinate(
                f"Invalid version {self.version!r}; expected letters, digits, "
                "dot, underscore or hyphen, starting with a letter or digit."
            )

    @classmethod
    def parse(cls, text: str) -> "Coordinate":
        """Parse a coordinate, expanding the shorthand form.

        ``qm9@v2`` is shorthand for ``dataset:molcrafts/qm9@v2``. The shorthand
        exists to be pleasant day to day; the full form exists to be
        unambiguous. Both parse to the same object — otherwise the shorthand
        would be a second syntax rather than an abbreviation of the first.

        Args:
            text: Full or shorthand coordinate.

        Returns:
            The parsed :class:`Coordinate`.

        Raises:
            InvalidCoordinate: If any segment is missing or malformed. In
                particular, a coordinate without ``@version`` is rejected.
        """
        candidate = text.strip()
        if not candidate:
            raise InvalidCoordinate("Coordinate must not be empty.")

        kind, separator, rest = candidate.partition(":")
        if not separator:
            kind, rest = DEFAULT_KIND, candidate

        body, at, version = rest.rpartition("@")
        if not at:
            raise InvalidCoordinate(
                f"Coordinate {text!r} is missing @version. A version is required "
                "so that a coordinate always names one immutable artifact."
            )
        if not version:
            raise InvalidCoordinate(f"Coordinate {text!r} has an empty version.")

        namespace, slash, name = body.partition("/")
        if not slash:
            namespace, name = DEFAULT_NAMESPACE, body
        if not name:
            raise InvalidCoordinate(f"Coordinate {text!r} has an empty name.")

        return cls(kind=kind, namespace=namespace, name=name, version=version)

    @classmethod
    def coerce(cls, value: "str | Coordinate") -> "Coordinate":
        """Return *value* as a :class:`Coordinate`, parsing it when it is a string.

        The check is against :class:`Coordinate`, not ``cls``: narrowing on a
        subclass would send an already-parsed base ``Coordinate`` down the
        string branch and fail on ``text.strip()``.
        """
        return value if isinstance(value, Coordinate) else cls.parse(value)

    @property
    def canonical(self) -> str:
        """The unambiguous full form, always with every segment spelled out."""
        return f"{self.kind}:{self.namespace}/{self.name}@{self.version}"

    @property
    def unversioned(self) -> str:
        """Everything but the version, for grouping an artifact's releases."""
        return f"{self.kind}:{self.namespace}/{self.name}"

    def relative_path(self) -> str:
        """Where this coordinate's manifest lives inside a registry directory."""
        return f"{self.kind}/{self.namespace}/{self.name}/{self.version}.yaml"

    def cache_path(self) -> str:
        """Where this coordinate's files live inside the cache: ``<kind>/<ns>/<name>@<ver>``.

        Deliberately not :attr:`canonical`. The canonical form contains a ``:``,
        which is not a path separator, so filing bytes under it would collapse
        ``dataset:molcrafts`` into one directory segment. The layout below
        ``$MOLHUB_HOME/files/`` is a contract the TypeScript client reads on the
        same machine — a client that built the path from its parts would never
        find what a client that used the canonical string had written.
        """
        return f"{self.kind}/{self.namespace}/{self.name}@{self.version}"

    def __str__(self) -> str:
        return self.canonical
