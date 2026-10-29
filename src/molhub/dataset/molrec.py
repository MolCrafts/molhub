"""A labelled-configuration ``*.mrec`` trajectory, read as a dataset.

A *labelled-configuration record* is an ordinary :class:`~molpy.Trajectory`
written through :mod:`molpy.io.mrec`. There is no ``molpy.Record`` /
``MolRec`` bag:

* **Conformers** are the trajectory frames. Frames may hold different
  molecules, so atom counts vary.
* **Teacher labels** live on those frames, keyed ``"<teacher>.<name>"``.
  Scalars sit in ``frame.meta``; vector labels (forces) are atom columns
  ``"<teacher>.fx"`` / ``fy`` / ``fz`` (any other vector is
  ``"<teacher>.<name>_x"`` / ``_y`` / ``_z``).
* One trajectory may carry several teachers, so a :class:`MolRecDataset` is
  pinned to exactly one at construction and exposes only that teacher's
  labels, with the prefix stripped.

Unlike the published benchmarks this package also adapts, a record is a local
artifact a user wrote — it has no registry coordinate and no frozen class-level
target schema. The schema is derived per instance from whichever labels the
selected teacher actually carries: scalars are graph-level targets, vectors
are atom-level ones.

Usage::

    from molhub.dataset.molrec import MolRecDataset

    source = MolRecDataset("qm9_rec.mrec", teacher_id="teacherA")
    source.target_schema.graph_level   # frozenset({"U0", "gap"})
    frames = source.load()
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from molpy import Block, Element, Frame
from molpy.io import mrec as _mrec

from molhub.dataset.protocol import InMemoryDataset, TargetSchema

__all__ = ["MolRecDataset"]

#: Column names for a per-atom vector target. ``forces`` uses the ``fx``/``fy``
#: /``fz`` columns every other adapter in this package writes; any other vector
#: observable is spelled ``<name>_x`` / ``_y`` / ``_z`` rather than dropped.
_FORCE_COLUMNS = ("fx", "fy", "fz")
_XYZ_SUFFIXES = ("_x", "_y", "_z")


def _plain(value: object) -> object:
    """Python scalar from a molpy 0.14 ``MetaValue`` (or the value itself)."""
    return getattr(value, "value", value)


def _plain_float(value: object, *, key: str) -> float:
    """:func:`_plain` narrowed to a float, naming the key when it is not one.

    ``_plain`` returns ``object`` because a ``MetaValue`` can hold anything, so
    handing its result straight to ``float()`` is untyped and, on a string or a
    JSON blob, raises with no clue which meta key was at fault.
    """
    plain = _plain(value)
    if isinstance(plain, (int, float)):
        return float(plain)
    if isinstance(plain, str):
        return float(plain)
    raise TypeError(
        f"meta key {key!r} holds {type(plain).__name__}, which is not a scalar this "
        "adapter can write as a float"
    )


def _axis_columns(stem: str) -> tuple[str, str, str]:
    """The three per-axis column names for *stem*, as an exact 3-tuple.

    Written out rather than comprehended: a generator gives ``tuple[str, ...]``,
    which does not satisfy the ``tuple[str, str, str]`` these feed, and the axis
    count is not a variable — it is three, named by :data:`_XYZ_SUFFIXES`.
    """
    x, y, z = _XYZ_SUFFIXES
    return (f"{stem}{x}", f"{stem}{y}", f"{stem}{z}")


def _teacher_columns(name: str) -> tuple[str, str, str]:
    """Atom-column names this adapter writes for a vector target *name*."""
    if name == "forces":
        return _FORCE_COLUMNS
    return _axis_columns(name)


class MolRecDataset:
    """One teacher's view of a labelled-configuration ``*.mrec`` trajectory.

    The record is read at construction, because that is what makes an unknown
    teacher or an unlabelled record fail immediately rather than at the first
    sample. :meth:`load` then materialises the conformers as frames.

    Args:
        record_path: Path to the ``*.mrec`` store written by
            :class:`molpy.io.mrec.MrecWriter`.
        teacher_id: Which teacher's labels to expose. Selects the
            ``"<teacher_id>."``-prefixed meta keys and atom columns; the
            prefix is stripped from the target names.
        total: Keep only the leading *total* conformers (smoke runs). Folded
            into :attr:`source_id`, so a subset and the whole record never
            share a cache key.

    Raises:
        FileNotFoundError: *record_path* does not exist.
        ValueError: *teacher_id* matches no label — the message lists the
            teacher prefixes the record does carry — or the trajectory is empty.
    """

    def __init__(
        self,
        record_path: str | Path,
        *,
        teacher_id: str,
        total: int | None = None,
    ) -> None:
        self.record_path = Path(record_path).expanduser()
        self.teacher_id = teacher_id
        self.total = total
        if not self.record_path.exists():
            raise FileNotFoundError(f"MolRec record not found: {self.record_path}")

        self._trajectory = _mrec.MrecReader(self.record_path)
        if len(self._trajectory) == 0:
            raise ValueError(
                f"Record {self.record_path} carries labels but no trajectory, so there "
                "are no conformers to label."
            )

        prefix = f"{teacher_id}."
        scalars: dict[str, list[object]] = {}
        vectors: dict[str, tuple[str, str, str]] = {}
        available: set[str] = set()
        for frame in self._trajectory:
            for key in frame.meta:
                if "." in key:
                    available.add(key.split(".", 1)[0])
                if key.startswith(prefix):
                    scalars.setdefault(key[len(prefix) :], [])
            if "atoms" not in frame:
                continue
            columns = set(frame["atoms"].keys())
            for column in columns:
                if "." in column:
                    available.add(column.split(".", 1)[0])
            if all(f"{prefix}{axis}" in columns for axis in _FORCE_COLUMNS):
                fx, fy, fz = _FORCE_COLUMNS
                vectors["forces"] = (f"{prefix}{fx}", f"{prefix}{fy}", f"{prefix}{fz}")
            stems: set[str] = set()
            for column in columns:
                if not column.startswith(prefix):
                    continue
                rest = column[len(prefix) :]
                for suffix in _XYZ_SUFFIXES:
                    if rest.endswith(suffix) and rest != f"forces{suffix}":
                        stems.add(rest[: -len(suffix)])
                        break
            for stem in stems:
                names = _axis_columns(f"{prefix}{stem}")
                if all(name in columns for name in names):
                    vectors[stem] = names

        if not scalars and not vectors:
            raise ValueError(
                f"teacher_id {teacher_id!r} matches no observable in {self.record_path}. "
                f"Available teacher prefixes: {sorted(available)}."
            )

        self._scalar_names = frozenset(scalars)
        self._vectors = vectors

    @property
    def target_schema(self) -> TargetSchema:
        """Target names this teacher exposes: scalars graph-level, vectors atom-level."""
        return TargetSchema(
            graph_level=self._scalar_names,
            atom_level=frozenset(self._vectors),
        )

    @property
    def source_id(self) -> str:
        """Cache identity: the record's name, the teacher, and any subset.

        The teacher is the whole reason this needs a qualifier — two teachers
        over one record are two datasets, and a cache that cannot tell them
        apart will serve one teacher's labels for the other. Nothing local
        (byte size, frame count) goes in: molnex folded those in, which made
        the identity unaddressable from any other machine.
        """
        source_id = f"molrec:{self.record_path.stem}#teacher={self.teacher_id}"
        if self.total is not None:
            source_id += f",total={self.total}"
        return source_id

    def __len__(self) -> int:
        """Number of conformers this view exposes."""
        count = len(self._trajectory)
        return count if self.total is None else min(count, self.total)

    def load(self) -> InMemoryDataset:
        """Materialise the selected conformers as frames.

        Returns:
            A map-style :class:`~molhub.dataset.protocol.Dataset` of
            :class:`molpy.Frame` samples in record order, each carrying this
            teacher's scalar targets in ``frame.meta`` and its vector targets
            as ``atoms`` columns.
        """
        frames = [self._frame(index) for index in range(len(self))]
        return InMemoryDataset(frames, name=f"{self.record_path.stem}#teacher={self.teacher_id}")

    def _frame(self, index: int) -> Frame:
        """Build one conformer: geometry from the trajectory, labels from the teacher."""
        source = self._trajectory[index]
        source_atoms = source["atoms"]
        symbols = [str(symbol) for symbol in np.asarray(source_atoms["element"])]
        prefix = f"{self.teacher_id}."

        atoms = Block()
        atoms["element"] = np.asarray(symbols, dtype="U3")
        for axis in ("x", "y", "z"):
            atoms[axis] = np.asarray(source_atoms[axis], dtype=np.float64)
        atoms["number"] = np.asarray(
            [Element.by_symbol(symbol).z for symbol in symbols], dtype=np.int64
        )
        for name, columns in self._vectors.items():
            for dest, column in zip(_teacher_columns(name), columns, strict=True):
                atoms[dest] = np.asarray(source_atoms[column], dtype=np.float64)

        frame = Frame()
        frame["atoms"] = atoms
        if source.box is not None:
            frame.box = source.box
        frame.meta = {
            name: _plain_float(source.meta[f"{prefix}{name}"], key=f"{prefix}{name}")
            for name in self._scalar_names
        }
        return frame
