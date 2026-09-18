"""Per-dataset statistics from a live Frame scan — not the snapshot cache.

``get_distrib(*fields)`` walks ``__getitem__`` **once** and reads every
requested key off the sample Frame. Snapshot ``dataset.cache`` is disabled
until a scan is a measured bottleneck — then turn it back on in code, not
with an environment variable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from molpy import Frame

__all__ = [
    "Distrib",
    "Field",
    "StatisticMixin",
    "frame_field",
]


@dataclass(frozen=True, slots=True)
class Field:
    """One Frame location, named the way the Frame is named.

    * ``graph.natoms`` is ``frame["atoms"].nrows``.
    * ``graph.<name>`` is the unwrapped ``frame.meta[name]`` scalar.
    * a bare block name (``bonds``, ``angles``, …) is that block's ``nrows``.

    A new quantity is a new Frame column or meta key. This type does not
    grow a parallel vocabulary (LMDB records, aliases, caches).
    """

    key: str

    def read(self, frame: Frame) -> object:
        """Return this field's per-sample value from *frame*."""
        key = self.key
        if key == "graph.natoms":
            return int(frame["atoms"].nrows)
        if key.startswith("graph."):
            name = key.removeprefix("graph.")
            meta = getattr(frame, "meta", None) or {}
            if name not in meta:
                raise ValueError(f"Frame has no field {key!r}")
            value = meta[name]
            return getattr(value, "value", value)
        try:
            return int(frame[key].nrows)
        except (KeyError, TypeError, AttributeError):
            pass
        meta = getattr(frame, "meta", None) or {}
        if key in meta:
            value = meta[key]
            return getattr(value, "value", value)
        # Bare block name with no block: zero rows.
        if "." not in key:
            return 0
        raise ValueError(f"Frame has no field {key!r}")


def frame_field(frame: Frame, field: str) -> object:
    """Read *field* from *frame*. See :class:`Field`."""
    return Field(field).read(frame)


@dataclass(frozen=True, slots=True)
class Distrib:
    """Raw per-row values plus basic reductions.

    *raw* is the scan vector (one entry per sample). Feed it to matplotlib
    (``plt.hist(distrib)`` / ``plt.hist(distrib.raw)``) for anything beyond
    min/max/mean/std. No invented field aliases; *field* is the Frame name
    that was scanned.
    """

    field: str
    raw: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", np.asanyarray(self.raw))

    def __array__(self, dtype: np.dtype | None = None, copy: bool | None = None) -> np.ndarray:
        arr = np.asarray(self.raw, dtype=dtype)
        if copy:
            return np.array(arr, copy=True)
        return arr

    def __len__(self) -> int:
        return int(self.raw.size)

    @property
    def n(self) -> int:
        return int(self.raw.size)

    @property
    def min(self) -> float:
        return float(np.min(self.raw)) if self.raw.size else float("nan")

    @property
    def max(self) -> float:
        return float(np.max(self.raw)) if self.raw.size else float("nan")

    @property
    def mean(self) -> float:
        return float(np.mean(self.raw)) if self.raw.size else float("nan")

    @property
    def std(self) -> float:
        return float(np.std(self.raw)) if self.raw.size else float("nan")

    @property
    def sum(self) -> float:
        return float(np.sum(self.raw)) if self.raw.size else 0.0


def _first_frame(sample: object) -> Frame:
    if isinstance(sample, Frame):
        return sample
    if isinstance(sample, Sequence) and sample and isinstance(sample[0], Frame):
        return sample[0]
    raise TypeError(f"StatisticMixin expected a Frame or Sequence[Frame], got {type(sample)!r}")


def _as_distribs(
    fields: tuple[str, ...], columns: dict[str, list[object]]
) -> Distrib | tuple[Distrib, ...]:
    out = tuple(Distrib(field=field, raw=np.asarray(columns[field])) for field in fields)
    if len(out) == 1:
        return out[0]
    return out


class StatisticMixin:
    """Scan ``self[i]`` once; read every requested key from the sample Frame.

    Requires ``__len__`` / ``__getitem__``. Does not infer bonds, convert
    units, or write labels — those belong to a prepare, not to stats.
    """

    if TYPE_CHECKING:
        # The docstring above states the requirement in prose; these state it to
        # the type checker. A mixin that calls `len(self)` and `self[i]` is
        # asking its host for them, and declaring that here is the fix. What this
        # replaces was a per-call-site mypy-style suppression comment, which `ty`
        # does not honour — so the errors stood while the comments suggested they
        # had been considered. (Spelling that directive out in prose is itself a
        # diagnostic: `ty` parses it wherever it appears, comments included.)
        def __len__(self) -> int: ...

        def __getitem__(self, index: int) -> Sequence[Frame]: ...

    def get_distrib(self, *fields: str) -> Distrib | tuple[Distrib, ...]:
        """Collect *fields* from every sample in one pass.

        A single field returns :class:`Distrib`. Two or more return a tuple
        of :class:`Distrib` in the same order, still from one walk of
        ``self[i]``. Each key is read with :meth:`Field.read`.

        Args:
            *fields: Frame keys, e.g. ``graph.natoms``, ``graph.energy``.
        """
        if not fields:
            raise TypeError("get_distrib() needs at least one field")
        n = len(self)
        readers = tuple(Field(field) for field in fields)
        columns: dict[str, list[object]] = {field: [] for field in fields}
        for i in range(n):
            frame = _first_frame(self[i])
            for reader in readers:
                columns[reader.key].append(reader.read(frame))
        return _as_distribs(fields, columns)
