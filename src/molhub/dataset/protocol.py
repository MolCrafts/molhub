"""Dataset protocols — map-style and iterable-style interfaces for molecular data.

Provides two core protocols:

* :class:`MapDataset` — indexable dataset with ``__len__`` and ``__getitem__``.
  Suitable for datasets whose samples can be randomly accessed by integer index.

* :class:`IterableDataset` — streaming dataset with ``__iter__``.
  Suitable for datasets whose samples are generated or streamed on-the-fly.

Also provides :class:`TargetSchema` to declare target layout, plus
:class:`InMemoryDataset` and :class:`SubsetDataset` concrete helpers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterator, Protocol, runtime_checkable

from molpy import Frame

# ---------------------------------------------------------------------------
# Sample — a molpy Frame
# ---------------------------------------------------------------------------

Sample = Frame
"""A single dataset sample is a :class:`molpy.Frame`.

The ``atoms`` block carries per-atom data (``element``, ``x``, ``y``, ``z``,
``number``, and optionally ``fx``, ``fy``, ``fz`` for forces).
Graph-level targets (e.g. energy) live in ``frame.meta`` as typed
``MetaValue`` entries; read them as plain Python values with
:class:`molhub.dataset.Targets`.
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
    (e.g. :attr:`QM9Dataset.TARGET_SCHEMA`) so downstream batching logic
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
class MapDataset(Protocol):
    """Protocol for index-addressable (map-style) datasets.

    A map-style dataset supports random access by integer index and reports
    its total length.

    Implementors must provide ``__len__`` and ``__getitem__``.
    """

    @property
    def source_id(self) -> str:
        """Unique, deterministic identifier for cache-key computation."""
        ...

    def __len__(self) -> int:
        """Total number of samples available."""
        ...

    def __getitem__(self, idx: int) -> Sample:
        """Return the sample at integer *idx*.

        Returns:
            A :class:`molpy.core.frame.Frame`.

        Raises:
            IndexError: If *idx* is out of range.
        """
        ...


# ---------------------------------------------------------------------------
# Iterable-style dataset
# ---------------------------------------------------------------------------


@runtime_checkable
class IterableDataset(Protocol):
    """Protocol for streaming (iterable-style) datasets.

    An iterable-style dataset yields samples via ``__iter__``.

    Use this for lazy file readers, on-the-fly generation, or datasets
    too large to index in memory.
    """

    @property
    def source_id(self) -> str:
        """Unique, deterministic identifier for cache-key computation."""
        ...

    def __iter__(self) -> Iterator[Sample]:
        """Yield samples in streaming order.

        Returns:
            An iterator over :class:`molpy.core.frame.Frame` objects.
        """
        ...


# ---------------------------------------------------------------------------
# Built-in concrete helpers
# ---------------------------------------------------------------------------


class InMemoryDataset:
    """A :class:`MapDataset` wrapping an in-memory list of :class:`Frame` objects.

    Args:
        frames: List of :class:`Frame` objects.
        name: Human-readable identifier folded into :attr:`source_id`.
    """

    def __init__(self, frames: list[Frame], *, name: str = "memory") -> None:
        self._frames = frames
        self._name = name

    @property
    def source_id(self) -> str:
        return f"memory:{self._name}:{len(self._frames)}"

    def __len__(self) -> int:
        return len(self._frames)

    def __getitem__(self, idx: int) -> Frame:
        return self._frames[idx]


class SubsetDataset:
    """A :class:`MapDataset` exposing a subset of another by index list.

    Args:
        source: Parent :class:`MapDataset`.
        indices: List of 0-based indices into *source*.
        name: Optional named view. When set, :attr:`source_id` uses the
            ``#split={name}`` qualifier (ThreeBPA/QM9 view convention).
            When omitted, the historical ``:subset=<12-hex>`` suffix is
            preserved so existing caches keep their keys.
    """

    def __init__(
        self,
        source: MapDataset,
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

    def __getitem__(self, idx: int) -> Frame:
        return self._source[self._indices[idx]]


__all__ = [
    "MapDataset",
    "IterableDataset",
    "Sample",
    "TargetSchema",
    "InMemoryDataset",
    "SubsetDataset",
]
