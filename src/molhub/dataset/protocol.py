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

from molpy.core.frame import Frame

# ---------------------------------------------------------------------------
# Sample — a molpy Frame
# ---------------------------------------------------------------------------

Sample = Frame
"""A single dataset sample is a :class:`molpy.core.frame.Frame`.

The ``atoms`` block carries per-atom data (``element``, ``x``, ``y``, ``z``,
``number``, and optionally ``fx``, ``fy``, ``fz`` for forces).
Graph-level targets (e.g. energy) live in ``frame.metadata``.
"""


# ---------------------------------------------------------------------------
# TargetSchema — declares which targets are graph-level vs atom-level
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetSchema:
    """Declares how targets are organised in a :data:`Sample`.

    ``graph_level`` targets (e.g. energy) are stored in ``frame.metadata``.
    ``atom_level`` targets (e.g. forces) are stored as columns in the
    ``atoms`` block (``fx``, ``fy``, ``fz``).

    Dataset source classes expose their schema as a class attribute
    (e.g. :attr:`QM9Source.TARGET_SCHEMA`) so downstream batching logic
    knows how to collate each target key.
    """

    graph_level: frozenset[str] = field(default_factory=lambda: frozenset({"energy"}))
    atom_level: frozenset[str] = field(default_factory=lambda: frozenset({"forces"}))


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
    """

    def __init__(self, source: MapDataset, indices: list[int]) -> None:
        self._source = source
        self._indices = indices
        idx_hash = hashlib.sha256(str(sorted(indices)).encode()).hexdigest()[:12]
        self._source_id = f"{source.source_id}:subset={idx_hash}"

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
