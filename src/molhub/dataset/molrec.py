"""A molpy ``MolRec`` (.zarr) labelled-configuration record, read as a dataset.

A *labelled-configuration record* — the output of, say, distilling a teacher
potential over a set of conformers — is an ordinary, **unchanged**
:class:`molpy.MolRec`:

* **Conformers** live in the record's trajectory, one :class:`molpy.Frame`
  each. Frames may hold different molecules, so atom counts vary.
* **Teacher labels** live in the flat ``observables`` map, keyed
  ``"<teacher>.<name>"`` (``teacherA.energy``, ``teacherA.forces``). Scalar
  observables are per-frame; vector observables carry
  ``axes=["timestep", "atom", "component"]``.
* **Teacher provenance** lives in the record's free-form ``method`` tree.

No molpy change is needed for any of this: it is built entirely from
``MolRec``'s generic primitives. One record may carry several teachers, so a
:class:`MolRecDataset` is pinned to exactly one at construction and exposes
only that teacher's observables, with the prefix stripped.

Unlike the published benchmarks this package also adapts, a record is a local
artifact a user wrote — it has no registry coordinate and no frozen class-level
target schema. The schema is derived per instance from whichever observables
the selected teacher actually carries: scalars are graph-level targets,
vectors are atom-level ones.

Usage::

    from molhub.dataset.molrec import MolRecDataset

    source = MolRecDataset("qm9_rec.zarr", teacher_id="teacherA")
    source.target_schema.graph_level   # frozenset({"U0", "gap"})
    frames = source.load()
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from molpy import Block, Element, Frame, MolRec

from molhub.dataset._meta import write_meta
from molhub.dataset.protocol import InMemoryDataset, TargetSchema

__all__ = ["MolRecDataset"]

#: Column names for a per-atom vector target. ``forces`` uses the ``fx``/``fy``
#: /``fz`` columns every other adapter in this package writes; any other vector
#: observable is spelled ``<name>_x`` / ``_y`` / ``_z`` rather than dropped.
_FORCE_COLUMNS = ("fx", "fy", "fz")


class MolRecDataset:
    """One teacher's view of a labelled-configuration ``MolRec`` record.

    The record is read at construction, because that is what makes an unknown
    teacher or an unlabelled record fail immediately rather than at the first
    sample. :meth:`load` then materialises the conformers as frames.

    Args:
        record_path: Path to the ``.zarr`` record written by
            :meth:`molpy.MolRec.write_zarr`.
        teacher_id: Which teacher's labels to expose. Selects the
            ``"<teacher_id>."``-prefixed observables; the prefix is stripped
            from the target names.
        total: Keep only the leading *total* conformers (smoke runs). Folded
            into :attr:`source_id`, so a subset and the whole record never
            share a cache key.

    Raises:
        FileNotFoundError: *record_path* does not exist.
        ValueError: *teacher_id* matches no observable — the message lists the
            teacher prefixes the record does carry — or an observable is
            neither scalar nor vector.
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

        self._record = MolRec.read_zarr(str(self.record_path))
        prefix = f"{teacher_id}."
        keys = list(self._record.observables.keys())
        mine = [key for key in keys if key.startswith(prefix)]
        if not mine:
            available = sorted({key.split(".", 1)[0] for key in keys if "." in key})
            raise ValueError(
                f"teacher_id {teacher_id!r} matches no observable in {self.record_path}. "
                f"Available teacher prefixes: {available}."
            )

        scalars: dict[str, np.ndarray] = {}
        vectors: dict[str, np.ndarray] = {}
        for key in mine:
            name = key[len(prefix) :]
            observable = self._record.observables.get(key)
            if observable is None:
                raise ValueError(
                    f"Record {self.record_path} lists observable {key!r} but cannot read it."
                )
            if observable.kind == "scalar":
                scalars[name] = np.asarray(observable.data, dtype=np.float64)
            elif observable.kind == "vector":
                vectors[name] = np.asarray(observable.data, dtype=np.float64)
            else:
                raise ValueError(
                    f"Observable {key!r} has unsupported kind {observable.kind!r}; "
                    "MolRecDataset reads 'scalar' and 'vector' observables."
                )
        self._scalars = scalars
        self._vectors = vectors

        trajectory = self._record.trajectory
        if trajectory is None:
            raise ValueError(
                f"Record {self.record_path} carries labels but no trajectory, so there "
                "are no conformers to label."
            )
        self._trajectory = trajectory

    @property
    def target_schema(self) -> TargetSchema:
        """Targets this teacher exposes: scalars graph-level, vectors atom-level."""
        return TargetSchema(
            graph_level=frozenset(self._scalars),
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
        count = self._record.count_frames()
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
        source = self._trajectory.frames[index]
        source_atoms = source["atoms"]
        symbols = [str(symbol) for symbol in np.asarray(source_atoms["element"])]

        atoms = Block()
        atoms["element"] = np.asarray(symbols, dtype="U3")
        for axis in ("x", "y", "z"):
            atoms[axis] = np.asarray(source_atoms[axis], dtype=np.float64)
        atoms["number"] = np.asarray(
            [Element.get_atomic_number(symbol) for symbol in symbols], dtype=np.int64
        )
        for name, data in self._vectors.items():
            columns = (
                _FORCE_COLUMNS if name == "forces" else (f"{name}_x", f"{name}_y", f"{name}_z")
            )
            for component, column in enumerate(columns):
                atoms[column] = np.asarray(data[index][:, component], dtype=np.float64)

        frame = Frame()
        frame["atoms"] = atoms
        if source.box is not None:
            frame.box = source.box
        write_meta(frame, {name: float(data[index]) for name, data in self._scalars.items()})
        return frame
