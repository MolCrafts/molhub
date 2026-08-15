"""The HuggingFace spelling of a name, resolved to one pinned coordinate.

``load_dataset("themol/mbis")`` names an *artifact*; a
:class:`~molhub.coordinate.Coordinate` names one **version** of one artifact,
and always has to. :class:`DatasetName` is the one step between them: it reads
the shorthand, takes ``revision`` — HF's spelling of ``@version``, and never a
git sha — and asks the registry which versions exist when no revision was given.

**Why this is not a ``Coordinate`` classmethod.** ``Coordinate.parse`` rejects a
missing ``@version`` on purpose, so that a coordinate always names one immutable
artifact. Defaulting the version is a different responsibility with a different
collaborator (the registry) and a different failure mode (refusing to guess);
smuggling it into ``Coordinate`` would quietly weaken the rule the coordinate
layer exists to keep.

**Why an unorderable version set is refused rather than picked.** The default is
a numeric-aware natural order: ``2`` before ``10``, ``v2`` before ``v3``. When
two labels first differ at a *text* segment — ``v2`` against ``beta`` — no
ordering of them means anything, and choosing one anyway would silently pin a
run to a version nobody asked for. :class:`AmbiguousRevision` names every
declared revision instead, because typing one of them is the only useful next
step.

Reference:
    ``.claude/specs/hf-facade-03-builder-info.md`` § Design (D4), under the
    2026-08-15 operator override recorded in ``.claude/notes/notes.md``
    (``mol:note:topic:hf-style-api``).
"""

from __future__ import annotations

import re

from molhub.coordinate import (
    DEFAULT_KIND,
    DEFAULT_NAMESPACE,
    Coordinate,
    InvalidCoordinate,
)
from molhub.registry import Registry, UnknownArtifact

__all__ = ["AmbiguousRevision", "DatasetName"]

# One version label, split into its digit runs and its text runs, so that the
# comparison can tell "differs by a number" from "differs by a word".
_SEGMENTS = re.compile(r"\d+|\D+")


class AmbiguousRevision(ValueError):
    """The declared versions of an artifact do not order, and none was given.

    Raised by :meth:`DatasetName.resolve` when the newest version cannot be
    decided by a numeric segment. The message lists every declared revision:
    the caller has to pick one, and a locator that pinned itself would break the
    promise that a coordinate names one immutable artifact.
    """


class DatasetName:
    """A dataset name in HuggingFace spelling, plus the revision to resolve it at.

    Args:
        text: ``"namespace/name"``, or just ``"name"`` for the default
            namespace ``molcrafts`` — the same shorthand
            :meth:`Coordinate.parse` reads, minus the ``@version`` it requires.
        revision: The version to pin, when the caller knows it. ``None`` asks
            the registry for the newest declared one.

    Raises:
        InvalidCoordinate: If *text* is not a well-formed name, or carries an
            ``@version`` — the version belongs in *revision*, so that one name
            has one spelling.
    """

    def __init__(self, text: str, *, revision: str | None = None) -> None:
        candidate = text.strip()
        if "@" in candidate:
            raise InvalidCoordinate(
                f"Dataset name {text!r} carries an @version. The version is the revision= "
                "argument here, so that one artifact has one spelling on this path; pass "
                "the name alone and the revision beside it."
            )
        kind, separator, rest = candidate.partition(":")
        if not separator:
            kind, rest = DEFAULT_KIND, candidate
        namespace, slash, name = rest.partition("/")
        if not slash:
            namespace, name = DEFAULT_NAMESPACE, rest
        self._kind = kind
        self._namespace = namespace
        self._name = name
        self._revision = revision
        # Validates every segment through the one type that owns those rules.
        # A placeholder version is used because this name has none yet; the
        # object is thrown away and only its refusals are kept.
        Coordinate(kind=kind, namespace=namespace, name=name, version=revision or "0")

    @property
    def revision(self) -> str | None:
        """The revision this name was constructed with, if any."""
        return self._revision

    @property
    def unversioned(self) -> str:
        """The artifact this name addresses, without a version.

        Returns:
            ``kind:namespace/name`` — what
            :meth:`~molhub.registry.Registry.versions` is asked about.
        """
        return f"{self._kind}:{self._namespace}/{self._name}"

    def resolve(self, registry: Registry) -> Coordinate:
        """Return the one coordinate this name and revision address.

        Args:
            registry: The registry whose declarations decide the default
                revision. An explicit revision is honoured without consulting
                it — whether that version exists is the registry's own answer,
                given when the manifest is asked for.

        Returns:
            The pinned :class:`~molhub.coordinate.Coordinate`, which
            :attr:`~molhub.loader.info.DatasetInfo.coordinate` echoes so a run
            can record what it actually read.

        Raises:
            AmbiguousRevision: If no revision was given and the declared
                versions do not order numerically.
            UnknownArtifact: If no revision was given and the registry declares
                no version of this artifact at all.
        """
        return Coordinate(
            kind=self._kind,
            namespace=self._namespace,
            name=self._name,
            version=self._revision if self._revision is not None else self._newest(registry),
        )

    def __repr__(self) -> str:
        return f"DatasetName({self.unversioned!r}, revision={self._revision!r})"

    def _newest(self, registry: Registry) -> str:
        """The newest declared version, or a refusal to guess which that is."""
        declared = registry.versions(self.unversioned)
        if not declared:
            raise UnknownArtifact(
                f"{self.unversioned} is not in the registry ({len(registry)} artifacts "
                f"loaded), so there is no revision to default to.{self._namespace_hint(registry)}"
            )
        if len(declared) == 1:
            return declared[0]
        if not self._orders(declared):
            raise AmbiguousRevision(
                f"{self.unversioned} declares revisions {', '.join(declared)}, which do "
                "not order numerically, so no one of them is 'the newest'. Pass an "
                "explicit revision= — a silently picked version is not a pinned one."
            )
        return max(declared, key=self._key)

    def _namespace_hint(self, registry: Registry) -> str:
        """What to suggest when the name typed is really a namespace.

        ``molhub info themol`` reads as "tell me about themol" and resolves as
        ``molcrafts/themol``, which nothing declares — while the registry knows
        perfectly well what the ``themol`` namespace holds. Reporting only the
        coordinate the user never typed makes the miss look like a broken
        registry; handing over the names under it is the next step they wanted.

        Args:
            registry: The registry that has just declared no such artifact.

        Returns:
            A sentence listing the datasets published under a namespace of this
            name, or ``""`` when the name is not one.
        """
        under = sorted(
            f"{manifest.coordinate.namespace}/{manifest.coordinate.name}"
            for manifest in registry.search(kind=self._kind)
            if manifest.coordinate.namespace == self._name
        )
        if not under:
            return ""
        return (
            f" {self._name!r} is a namespace rather than a dataset; it publishes "
            f"{', '.join(dict.fromkeys(under))}. Name one of those."
        )

    @classmethod
    def _orders(cls, declared: tuple[str, ...]) -> bool:
        """Whether every pair of *declared* is decided by a numeric segment."""
        keys = [cls._key(version) for version in declared]
        return all(
            cls._decided_numerically(first, second)
            for index, first in enumerate(keys)
            for second in keys[index + 1 :]
        )

    @staticmethod
    def _key(version: str) -> tuple[int | str, ...]:
        """*version* as digit runs (ints) and text runs (lower-cased strings)."""
        return tuple(
            int(part) if part.isdigit() else part.lower() for part in _SEGMENTS.findall(version)
        )

    @staticmethod
    def _decided_numerically(first: tuple[int | str, ...], second: tuple[int | str, ...]) -> bool:
        """Whether two version keys first differ at a number rather than a word.

        A shared prefix (``1`` against ``1.1``) is decided by length, which is
        an ordering; ``v2`` against ``beta`` differs at a word, which is not.
        """
        for left, right in zip(first, second, strict=False):
            if left == right:
                continue
            return isinstance(left, int) and isinstance(right, int)
        return True
