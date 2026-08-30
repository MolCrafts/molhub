"""Dataset protocols (map-style and iterable-style).

Copied surface, no third-party dataset framework:

* :class:`Dataset` — ``__len__`` and ``__getitem__``.
* :class:`IterableDataset` — ``__iter__``.

A sample is a :data:`~molpy.FrameCollection` — ``Sequence[Frame]``. Graph-level
fields live in each frame's ``meta``. Concrete helpers may also expose
``source_id``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Iterator, Protocol, runtime_checkable

from molpy import Frame

type FrameCollection = Sequence[Frame]
"""``Sequence[Frame]`` — one record of trajectory-like data.

molpy ≥0.14 exports a plain alias of the same shape, but the PyPI 0.13 wheel
does not, and molpy's lazy module ``__getattr__`` makes checkers resolve a
missing name as ``ModuleType``. Declared locally as a PEP 695 alias it is
checker-solid on both — and it keeps its ``__name__``, which is what
``DatasetInfo.record_type`` reads off a definition's generic argument.
"""

# ---------------------------------------------------------------------------
# Sample — one FrameCollection
# ---------------------------------------------------------------------------

type Sample = FrameCollection
"""A sample is a :data:`FrameCollection` (``Sequence[Frame]``).

One geometry is a length-1 collection. A sampling unit that is inseparable but
multi-frame — a relaxation, a complete torsion profile — is a longer collection.
Every frame carries its own scalars in its own ``meta``. There is no second
record type and no :class:`~molpy.Trajectory` on this surface.
"""


# ---------------------------------------------------------------------------
# TargetSchema — declares which targets are graph-level vs atom-level
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetSchema:
    """Declares how targets are organised in a :data:`Sample`.

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

    def __getitem__(self, index: int, /) -> Sample:
        """Return the sample at integer *index*.

        The parameter is **positional-only**: ``ds[i]`` never passes it by
        keyword, and requiring a spelling would make every implementation that
        happens to call it ``idx`` — which is all of them, including
        :class:`InMemoryDataset` and :class:`SubsetDataset` below — fail to
        satisfy this protocol statically while passing ``isinstance``. That
        divergence was invisible until ``hf-facade-03-builder-info`` made
        ``load`` return a declared ``Dataset``.

        Returns:
            A :data:`~molpy.FrameCollection` (``Sequence[Frame]``).

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


# ---------------------------------------------------------------------------
# Iterable-style dataset
# ---------------------------------------------------------------------------


@runtime_checkable
class IterableDataset(Protocol):
    """Streaming dataset: ``__iter__``.

    ``source_id`` is optional and is not required for ``isinstance``.
    """

    def __iter__(self) -> Iterator[Sample]:
        """Yield samples in streaming order.

        Returns:
            An iterator over :data:`~molpy.FrameCollection` records.
        """
        ...


# ---------------------------------------------------------------------------
# Built-in concrete helpers
# ---------------------------------------------------------------------------


class InMemoryDataset:
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

    def __getitem__(self, idx: int) -> FrameCollection:
        return (self._frames[idx],)


class SubsetDataset:
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
    def indices(self) -> list[int]:
        """Copy of the parent indices this view exposes."""
        return list(self._indices)

    @property
    def source_id(self) -> str:
        return self._source_id

    def __len__(self) -> int:
        return len(self._indices)

    def __getitem__(self, idx: int) -> FrameCollection:
        """The parent's collection at this view's *idx*."""
        return self._source[self._indices[idx]]


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
    "FrameCollection",
    "IterableDataset",
    "Sample",
    "TargetSchema",
    "InMemoryDataset",
    "SubsetDataset",
    "assignment",
]
