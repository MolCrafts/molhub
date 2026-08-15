"""Dataset protocols (map-style and iterable-style).

Copied surface, no third-party dataset framework:

* :class:`Dataset` — ``__len__`` and ``__getitem__``.
* :class:`IterableDataset` — ``__iter__``.

A sample is a :class:`molpy.Frame` (one geometry) or a
:class:`molpy.Trajectory` (one multi-frame sampling unit). Graph-level fields
live in ``frame.meta``. Concrete helpers may also expose ``source_id``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterator, Protocol, runtime_checkable

from molpy import Frame, Trajectory

# ---------------------------------------------------------------------------
# Sample — a molpy Frame or Trajectory
# ---------------------------------------------------------------------------

Sample = Frame | Trajectory
"""A sample is a :class:`molpy.Frame` or a :class:`molpy.Trajectory`.

One geometry is a ``Frame``: per-atom data (including per-atom supervision such
as ``atomic_charge``) lives in its ``atoms`` block, matrices in named COO blocks
such as ``hessian{row,col,value}``, index tuples in valence-style blocks, and
scalars in ``frame.meta``.

A sampling unit that is inseparable but multi-frame — a relaxation trajectory, a
complete torsion profile — is a ``Trajectory`` of such frames, each carrying its
own scalars in its own ``meta``. There is no wrapper object on top of ``Frame``.

Widened from ``Frame`` alone on 2026-08-15 by the operator note recorded in
``.claude/notes/notes.md`` (``mol:note:topic:hf-style-api``, "Records ARE molpy
objects") and implemented by the spec ``hf-facade-02-frame-records`` (D10). The
matching CLAUDE.md "What must never change casually" bullet was amended in the
same change.
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
        ``load_dataset`` return a declared ``Dataset``.

        Returns:
            A :class:`molpy.Frame` or :class:`molpy.Trajectory`.

        Raises:
            IndexError: If *index* is out of range.
        """
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
            An iterator over :class:`molpy.Frame` / :class:`molpy.Trajectory`
            objects.
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

    @property
    def source_id(self) -> str:
        return f"memory:{self._name}:{len(self._frames)}"

    def __len__(self) -> int:
        return len(self._frames)

    def __getitem__(self, idx: int) -> Frame:
        return self._frames[idx]


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
        source: Dataset,
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

    def __getitem__(self, idx: int) -> Sample:
        """The parent's sample, whichever of the two kinds the parent yields."""
        return self._source[self._indices[idx]]


__all__ = [
    "Dataset",
    "IterableDataset",
    "Sample",
    "TargetSchema",
    "InMemoryDataset",
    "SubsetDataset",
]
