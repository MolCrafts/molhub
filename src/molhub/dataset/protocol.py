"""Dataset protocols (map-style and iterable-style).

Copied surface, no third-party dataset framework:

* :class:`Dataset` — ``__len__`` and ``__getitem__`` (one sample is
  ``Sequence[Frame]``).
* :class:`StatisticMixin` — ``get_distrib(*fields)`` (one scan); mixed in
  *beside* :class:`Dataset` (``class QM9(Dataset, StatisticMixin)``), not
  inside it.
* :class:`IterableDataset` — ``__iter__``.

A sample is ``Sequence[Frame]``. Graph-level fields live in each frame's
``meta``. Concrete helpers may also expose ``source_id``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Iterator, Protocol, runtime_checkable

from molpy import Frame

from molhub.dataset.definition import DatasetManifest
from molhub.dataset.statistic import StatisticMixin

# One geometry is a length-1 sequence. A sampling unit that is inseparable but
# multi-frame — a relaxation, a complete torsion profile — is a longer sequence.
# Every frame carries its own scalars in its own ``meta``.


# ---------------------------------------------------------------------------
# TargetSchema — declares which targets are graph-level vs atom-level
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetSchema:
    """Declares how targets are organised in one ``Sequence[Frame]``.

    Layout axis (collate / storage):

    * ``graph_level`` targets (e.g. energy) are stored in ``frame.meta``.
    * ``atom_level`` targets (e.g. forces) are stored as columns in the
      ``atoms`` block (``fx``, ``fy``, ``fz``).

    Meaning axis (optional semantic families; empty by default so legacy
    datasets remain compatible):

    * ``chemical_perception`` — discrete typing / perception labels
      (e.g. GAFF ``atom_type``).
    * ``mm`` — molecular-mechanics energies / forces / parameters.
    * ``qm`` — quantum-mechanical labels.

    Dataset source classes expose their schema as a class attribute
    (e.g. :attr:`QM9.TARGET_SCHEMA`) so downstream batching logic
    knows how to collate each target key.
    """

    graph_level: frozenset[str] = field(default_factory=lambda: frozenset({"energy"}))
    atom_level: frozenset[str] = field(default_factory=lambda: frozenset({"forces"}))
    chemical_perception: frozenset[str] = field(default_factory=frozenset)
    mm: frozenset[str] = field(default_factory=frozenset)
    qm: frozenset[str] = field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# Map-style dataset
# ---------------------------------------------------------------------------


@runtime_checkable
class Dataset(Protocol):
    """Map-style dataset: ``__len__`` and ``__getitem__``.

    Extra attributes such as ``source_id`` are optional and are *not* part of
    this protocol.
    """

    def __len__(self) -> int:
        """Total number of samples available."""
        ...

    def __getitem__(self, index: int, /) -> Sequence[Frame]:
        """Return the sample at integer *index*.

        The parameter is **positional-only**: ``ds[i]`` never passes it by
        keyword, and requiring a spelling would make every implementation that
        happens to call it ``idx`` — which is all of them, including
        :class:`InMemoryDataset` and :class:`SubsetDataset` below — fail to
        satisfy this protocol statically while passing ``isinstance``. That
        divergence was invisible until ``hf-facade-03-builder-info`` made
        ``load`` return a declared ``Dataset``.

        Returns:
            ``Sequence[Frame]``.

        Raises:
            IndexError: If *index* is out of range.
        """
        ...


@runtime_checkable
class IdentifiedDataset(Dataset, Protocol):
    """A :class:`Dataset` that also carries a stable ``source_id``.

    ``source_id`` stays out of :class:`Dataset` on purpose (it is optional
    there); consumers that *require* it — :class:`SubsetDataset` derives its
    own id from the parent's — take this narrower protocol instead of reading
    an attribute the wider one never promised.
    """

    @property
    def source_id(self) -> str:
        """Stable identifier folded into cache keys."""
        ...


@runtime_checkable
class DeclaredDataset(Dataset, Protocol):
    """A :class:`Dataset` that also carries the manifest its definition declared.

    Like :class:`IdentifiedDataset`, this stays out of :class:`Dataset` because
    it is optional there — a hand-built dataset of Frames declares nothing. A
    consumer that needs to know **what the data is** (its units, above all)
    takes this protocol rather than reading an attribute the wider one never
    promised.

    Why it matters that a *loaded* dataset answers this, and not only the
    definition class: a consumer holding the loaded object and unable to ask it
    must restate the unit at the call site, and a restated unit drifts. A
    ``kcal/mol`` dataset read through an ``eV`` default scaled every label by
    23.06 — silently, the result still being a plausible energy (molnex
    ``ClassIPrepare``, 2026-09-17).
    """

    @property
    def manifest(self) -> DatasetManifest:
        """What the dataset definition declared — units, blocks, identity."""
        ...


# ---------------------------------------------------------------------------
# Iterable-style dataset
# ---------------------------------------------------------------------------


@runtime_checkable
class IterableDataset(Protocol):
    """Streaming dataset: ``__iter__``.

    ``source_id`` is optional and is not required for ``isinstance``.
    """

    def __iter__(self) -> Iterator[Sequence[Frame]]:
        """Yield samples in streaming order.

        Returns:
            An iterator over ``Sequence[Frame]`` records.
        """
        ...


# ---------------------------------------------------------------------------
# Built-in concrete helpers
# ---------------------------------------------------------------------------


class InMemoryDataset(IdentifiedDataset, StatisticMixin):
    """A :class:`Dataset` wrapping an in-memory list of :class:`Frame` objects.

    Args:
        frames: List of :class:`Frame` objects.
        name: Human-readable identifier folded into :attr:`source_id`.
    """

    def __init__(self, frames: list[Frame], *, name: str = "memory") -> None:
        self._frames = frames
        self._name = name
        # Published named-view assignment, installed by loaders that build
        # this dataset from named parts (molhub.loader.builder) and read
        # back through split_assignment(); None when nothing was published.
        self._assignment: dict[str, list[int]] | None = None

    @property
    def source_id(self) -> str:
        return f"memory:{self._name}:{len(self._frames)}"

    def __len__(self) -> int:
        return len(self._frames)

    def __getitem__(self, idx: int) -> Sequence[Frame]:
        return (self._frames[idx],)


class SubsetDataset(IdentifiedDataset, StatisticMixin):
    """A :class:`Dataset` exposing a subset of another by index list.

    Args:
        source: Parent :class:`Dataset`.
        indices: List of 0-based indices into *source*.
        name: Optional named view. When set, :attr:`source_id` uses the
            ``#split={name}`` qualifier (ThreeBPA/QM9 view convention).
            When omitted, the historical ``:subset=<12-hex>`` suffix is
            preserved so existing caches keep their keys.
    """

    def __init__(
        self,
        source: IdentifiedDataset,
        indices: list[int],
        *,
        name: str | None = None,
    ) -> None:
        self._source = source
        self._indices = list(indices)
        self._name = name
        if name is not None:
            self._source_id = f"{source.source_id}#split={name}"
        else:
            idx_hash = hashlib.sha256(str(sorted(indices)).encode()).hexdigest()[:12]
            self._source_id = f"{source.source_id}:subset={idx_hash}"

    @property
    def name(self) -> str | None:
        """Named view identifier, or ``None`` for the hash-form subset."""
        return self._name

    @property
    def source(self) -> IdentifiedDataset:
        """Parent dataset this view indexes."""
        return self._source

    @property
    def indices(self) -> list[int]:
        """Copy of the parent indices this view exposes."""
        return list(self._indices)

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def manifest(self) -> DatasetManifest:
        """The parent's declaration — a subset publishes the same data.

        Read *through* rather than copied, for the same reason
        :attr:`source_id` is derived from the parent's: one fact, one owner. A
        subset that could not answer this would push its consumers into walking
        :attr:`source` themselves, and a consumer that cannot ask a dataset for
        its units ends up restating them (:class:`DeclaredDataset`).

        Raises:
            AttributeError: The parent declares nothing — a hand-built dataset
                of Frames, for instance. There is no manifest to read, and
                inventing one is what this protocol exists to prevent.
        """
        # Read defensively rather than declaring `_source: DeclaredDataset`: the
        # parent only has to be an `IdentifiedDataset`, and most are not
        # declared. The explicit raise says which type came up short, where a
        # bare attribute error would only name `manifest`.
        manifest = getattr(self._source, "manifest", None)
        if manifest is None:
            raise AttributeError(
                f"{type(self._source).__name__} declares no manifest, so this "
                "subset cannot state its units either. Only a dataset built from "
                "an @dataset(...) definition carries one; a hand-built dataset of "
                "Frames declares nothing and there is none to infer."
            )
        return manifest

    def __len__(self) -> int:
        return len(self._indices)

    def __getitem__(self, idx: int) -> Sequence[Frame]:
        """The parent's collection at this view's *idx*."""
        return self._source[self._indices[idx]]

    def __getitems__(self, indices: Sequence[int]) -> list[Sequence[Frame]]:
        """The parent's batch fetch, on this view's indices.

        Torch calls this once per batch. Forwarding the parent indices keeps
        a parent's ``__getitems__`` — its staging pool and its row cache — on
        the path the loader actually reads. A parent without one is read a
        row at a time.
        """
        parent = [self._indices[int(index)] for index in indices]
        fetch = getattr(self._source, "__getitems__", None)
        if callable(fetch):
            return list(fetch(parent))
        return [self._source[index] for index in parent]


def assignment(dataset: object) -> dict[str, list[int]]:
    """Published name → indices into *dataset*.

    PyTorch split: a list of integers, applied with :class:`SubsetDataset`.
    ``load`` does not take a split name.

    Raises:
        TypeError: *dataset* has no published assignment.
    """
    from collections.abc import Mapping

    method = getattr(dataset, "assignment", None)
    if callable(method):
        result = method()
        if isinstance(result, Mapping):
            return {str(name): list(index) for name, index in result.items()}
    stored = getattr(dataset, "_assignment", None)
    if isinstance(stored, Mapping):
        return {str(name): list(index) for name, index in stored.items()}
    raise TypeError(
        f"{type(dataset).__name__} has no published assignment. "
        "Build your own index list and wrap it with SubsetDataset."
    )


__all__ = [
    "Dataset",
    "IterableDataset",
    "TargetSchema",
    "InMemoryDataset",
    "SubsetDataset",
    "assignment",
]
