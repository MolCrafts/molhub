"""ASE-row LMDB files as a map-style dataset.

One row is one frame. The bytes are :class:`~molhub.io.ase.AseRows` on an
:class:`~molhub.io.lmdb.Lmdb`. This is not an mrec collection and it does not
subclass :class:`~molhub.dataset.lmdb.LmdbDataset`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from molpy import Block, Box, Frame

from molhub.dataset.prefetch import Prefetch
from molhub.dataset.protocol import Dataset
from molhub.io.ase import AseRows
from molhub.io.collection import instance_lock
from molhub.io.lmdb import Lmdb

__all__ = ["AseDataset"]


def _box_of(row: dict[str, Any]) -> Box | None:
    """ASE ``cell`` / ``pbc`` as a :class:`~molpy.Box` when any axis is periodic.

    ASE stores lattice vectors as rows. :class:`~molpy.Box` takes them as columns.
    """
    cell = row.get("cell")
    pbc = row.get("pbc")
    if cell is None or pbc is None:
        return None
    flags = np.asarray(pbc, dtype=bool).reshape(-1)
    if flags.size != 3 or not bool(flags.any()):
        return None
    matrix = np.asarray(cell, dtype=np.float64)
    if matrix.shape == (3,):
        matrix = np.diag(matrix)
    elif matrix.size == 9:
        matrix = matrix.reshape(3, 3).T
    else:
        raise ValueError(f"ASE cell has shape {np.shape(cell)}; expected (3,) or (3, 3)")
    return Box(matrix, pbc=flags)


def _row_frame(row: dict[str, Any]) -> Frame:
    """One ASE ``AtomsRow`` dict on molrec's conventions.

    ``numbers`` -> ``atoms.atomic_number``; ``positions`` -> ``x/y/z``;
    ``forces`` -> ``fx/fy/fz``; ``energy`` -> ``pe``. ``cell`` / ``pbc`` become
    ``frame.box`` when any axis is periodic. ``key_value_pairs`` and the scalar
    entries of ``data`` become frame meta (``charge`` -> ``total_charge``); a
    ``data`` array with one row per atom becomes an ``atoms`` column.
    """
    numbers = np.asarray(row["numbers"]).reshape(-1).astype(np.uint64)
    n = numbers.shape[0]
    positions = np.asarray(row["positions"], dtype=np.float64).reshape(n, 3)
    columns: dict[str, np.ndarray] = {
        "atomic_number": numbers,
        "x": positions[:, 0],
        "y": positions[:, 1],
        "z": positions[:, 2],
    }
    if row.get("forces") is not None:
        forces = np.asarray(row["forces"], dtype=np.float64).reshape(n, 3)
        columns.update(fx=forces[:, 0], fy=forces[:, 1], fz=forces[:, 2])
    meta: dict[str, Any] = {}
    data = dict(row.get("data") or {})
    for key, value in data.items():
        array = np.asarray(value)
        if array.ndim >= 1 and array.shape[0] == n and array.dtype.kind in "biufU":
            columns[key] = array
        elif array.ndim == 0:
            meta["total_charge" if key == "charge" else key] = array.item()
    meta.update(dict(row.get("key_value_pairs") or {}))
    if row.get("energy") is not None:
        meta["pe"] = float(row["energy"])
    if "charge" in row and "total_charge" not in meta:
        meta["total_charge"] = row["charge"]
    frame = Frame()
    frame["atoms"] = Block(columns)
    frame.meta = meta
    box = _box_of(row)
    if box is not None:
        frame.box = box
    return frame


class AseDataset(Prefetch, Dataset):
    """ASE-row LMDB files, one row (frame) per index.

    ASE stores Å, eV and eV/Å whatever produced the row, so :attr:`units` is
    fixed rather than read from the file. :meth:`stage` reads the row dict and
    :meth:`realize` builds the frame.

    Instances pickle: open environments are dropped and reopened lazily in the
    receiving process.

    Args:
        paths: The database files, in order.
        source_id: This dataset's identity. A capped view (``max_rows``) must
            state a different one than the full set.
        max_rows: Index at most this many rows across the files.

    Raises:
        FileNotFoundError: No rows under *paths*.
    """

    UNITS = {"length": "angstrom", "energy": "eV", "force": "eV/angstrom", "charge": "e"}

    def __init__(
        self, paths: Sequence[str | Path], *, source_id: str, max_rows: int | None = None
    ) -> None:
        self._paths = tuple(Path(p).expanduser().resolve() for p in paths)
        self._source_id = str(source_id)
        self.max_rows = None if max_rows is None else int(max_rows)
        self._tables: list[AseRows | None] = []
        parts: list[np.ndarray] = []
        total = 0
        for table_idx, path in enumerate(self._paths):
            table = AseRows.open(path)
            self._tables.append(table)
            ids = np.asarray(table.ids, dtype=np.int64)
            if self.max_rows is not None:
                ids = ids[: max(self.max_rows - total, 0)]
            part = np.empty((ids.shape[0], 2), dtype=np.int64)
            part[:, 0], part[:, 1] = table_idx, ids
            parts.append(part)
            total += int(ids.shape[0])
            if self.max_rows is not None and total >= self.max_rows:
                break
        if total == 0:
            raise FileNotFoundError(f"no ASE LMDB rows under {[str(p) for p in self._paths]}")
        self._rows = np.concatenate(parts)

    @property
    def path(self) -> Path:
        return self._paths[0]

    @property
    def units(self) -> dict[str, str]:
        return dict(self.UNITS)

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def manifest(self) -> None:
        return None

    def __len__(self) -> int:
        return int(self._rows.shape[0])

    def _table(self, table_idx: int) -> AseRows:
        table = self._tables[table_idx]
        if table is not None:
            return table
        with instance_lock(self):
            table = self._tables[table_idx]
            if table is None:
                table = self._tables[table_idx] = AseRows(
                    Lmdb(self._paths[table_idx], readonly=True, lock=False)
                )
            return table

    def stage(self, index: int) -> tuple[dict[str, Any], str]:
        """The raw ``AtomsRow`` dict and its ``source_record_id``. No frame."""
        idx = int(index)
        if idx < 0:
            idx += len(self)
        if not 0 <= idx < len(self):
            raise IndexError(idx)
        table_idx, row_id = (int(v) for v in self._rows[idx])
        return self._table(table_idx).get(row_id), f"{table_idx}:{row_id}"

    def realize(self, staged: tuple[dict[str, Any], str]) -> tuple[Frame, ...]:
        """One frame for a :meth:`stage` result, on this thread."""
        row, source_record_id = staged
        frame = _row_frame(row)
        frame.meta = {**frame.meta, "source_record_id": source_record_id}
        return (frame,)

    def __getitem__(self, index: int, /) -> tuple[Frame, ...]:
        return self.realize(self.stage(index))

    def row(self, idx: int) -> dict[str, Any]:
        """The raw decoded ``AtomsRow`` dict at *idx*.

        Raises:
            IndexError: *idx* is out of range.
        """
        return self.stage(idx)[0]

    def keys(self) -> tuple[str, ...]:
        return tuple(f"{int(t)}:{int(r)}" for t, r in self._rows)

    def close(self) -> None:
        for i, table in enumerate(self._tables):
            if table is not None:
                table.close()
                self._tables[i] = None

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state["_tables"] = [None] * len(self._paths)
        state.pop("_lock_obj", None)
        return state
