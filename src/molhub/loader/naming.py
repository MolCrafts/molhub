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

**A name nobody declares is a name problem, not a revision problem.** The
default-revision lookup is where a misspelled name is first noticed — the
registry declares no version of it — but the reader typed
``load_dataset("themol/mbsi", split="train")`` and has a spelling problem, so the
refusal leads with the name that missed and names the verb that lists the ones
that did not (``molhub search``). It says nothing about revisions: there is no
revision of a dataset nobody publishes. The *ordering* refusal below is a
different sentence about a real revision problem and still says so.

**The refusal reports what was typed, never what was defaulted.** A name with no
``namespace/`` takes ``molcrafts``, which is the right rule and the wrong
sentence: ``dataset:molcrafts/mbis is not in the registry`` names a coordinate
the reader never typed and never meant, for a dataset that is published one
segment away under ``themol``, and it reads like a registry that lost the
dataset rather than a name that needs its namespace. So a bare name is echoed
bare, a namespaced one is echoed in full, and when exactly **one** published
artifact carries the bare name, the refusal hands over its full ``ns/name``.
Exactly one, because two candidates are a choice the reader has to make and
listing both is what :meth:`~molhub.registry.Registry.search` is for.

**Why an unorderable version set is refused rather than picked.** The default is
a numeric-aware natural order: ``2`` before ``10``, ``v2`` before ``v3``. When
two labels first differ at a *text* segment — ``v2`` against ``beta`` — no
ordering of them means anything, and choosing one anyway would silently pin a
run to a version nobody asked for. :class:`AmbiguousRevision` names every
declared revision instead, because typing one of them is the only useful next
step.

**``polymer-tg`` refuses even though ``v1``–``v7`` order.** Those labels are
Zenodo's versions of one concept, and the files are not successive cuts of one
table. Picking ``v7`` because it sorts last would download a different file
from the one a caller who omitted the version had in mind. The refusal is the
same type: name a revision.

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

# Revisions that sort, but must not be defaulted. Each label is one upstream
# record, and the bytes are not one series. See polymer_tg.MANIFESTS.
_PINNED_REVISION = frozenset({"dataset:molcrafts/polymer-tg"})


class AmbiguousRevision(ValueError):
    """No revision was given, and molhub will not pick one.

    Raised by :meth:`DatasetName.resolve` when the newest version cannot be
    decided by a numeric segment, and when an artifact publishes one file per
    upstream record (``polymer-tg``). The message lists every declared revision:
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
        self._namespaced = bool(slash)
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
                f"{self._addressed} is not in the registry ({len(registry)} artifacts "
                f"loaded). Check the spelling, or list what is published with "
                f"'molhub search'.{self._near_miss(registry)}{self._namespace_hint(registry)}"
            )
        if len(declared) == 1:
            return declared[0]
        if self.unversioned in _PINNED_REVISION:
            raise AmbiguousRevision(
                f"{self.unversioned} publishes revisions {', '.join(declared)}, one "
                "Zenodo record each. Pass an explicit revision=; these files are not "
                "one table, so none of them is the default."
            )
        if not self._orders(declared):
            raise AmbiguousRevision(
                f"{self.unversioned} declares revisions {', '.join(declared)}, which do "
                "not order numerically, so no one of them is 'the newest'. Pass an "
                "explicit revision= — a silently picked version is not a pinned one."
            )
        return max(declared, key=self._key)

    @property
    def _addressed(self) -> str:
        """This name as the reader typed it, never as this class defaulted it.

        Returns:
            ``kind:namespace/name`` for a name that carried a namespace, and the
            bare name for one that did not — because ``molcrafts`` is then
            molhub's own defaulting, and reporting it back describes a call the
            reader never made.
        """
        return self.unversioned if self._namespaced else self._name

    def _near_miss(self, registry: Registry) -> str:
        """The one published artifact this bare name would have hit, if there is one.

        ``load_dataset("mbis")`` is one namespace away from working, and the
        registry can see that: exactly one artifact is called ``mbis``. Holding
        that back and reporting a defaulted coordinate instead is the same
        failure :meth:`_namespace_hint` fixes from the other direction.

        Args:
            registry: The registry that has just declared no such artifact.

        Returns:
            A sentence naming the full ``namespace/name`` to type, or ``""``
            when the name was already namespaced, or when the number of
            published artifacts carrying it is not exactly one — two candidates
            are a choice only the reader can make, and ``molhub search`` (which
            the refusal already names) is what lists them.
        """
        if self._namespaced:
            return ""
        matches = sorted(
            {
                f"{manifest.coordinate.namespace}/{manifest.coordinate.name}"
                for manifest in registry.search(kind=self._kind)
                if manifest.coordinate.name == self._name
            }
        )
        if len(matches) != 1:
            return ""
        return (
            f" One published dataset is called {self._name!r}: {matches[0]}. "
            "Names take a namespace; a bare one is read under 'molcrafts'."
        )

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
