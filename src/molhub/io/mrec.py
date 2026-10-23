"""An mrec collection: one record model, addressed through :class:`Lmdb` or :class:`Hdf5`.

The bytes of a record are :mod:`molhub.io.collection`. This module only places
those bytes. LMDB keys stay ``meta``, ``index``, ``r``/``s``/``f`` plus a
big-endian record number, because molrec's codec is the arbiter of that file
and it requires the JSON tag ``layout: mrec-lmdb``. molhub's own name for the
records is ``format: mrec``. Both tags are written on LMDB. An HDF5 collection
is molhub's, so its header carries ``format`` only.

Nothing is readable until :meth:`MrecWriter.close` writes the header and
renames the partial file onto *path*.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from molhub.io import frame_bytes
from molhub.io.collection import encode_record, realize_record
from molhub.io.hdf5 import Hdf5
from molhub.io.lmdb import Lmdb

__all__ = ["MrecRecords", "MrecWriter"]

FORMAT = "mrec"
FORMAT_VERSION = 1
#: molrec's LMDB codec refuses a file without this tag. It is not molhub's format name.
MOLREC_LAYOUT = "mrec-lmdb"
MOLREC_LAYOUT_VERSION = 1
HDF5_LAYOUT = "mrec-hdf5"

_META = b"meta"
_INDEX = b"index"
_INDEX_BLOCK = "records"
_RECORD = b"r"
_SYSTEM = b"s"
_FRAME = b"f"
_BINDING = ("first_frame", "n_frames", "n_atoms")


def _key(prefix: bytes, n: int) -> bytes:
    return prefix + int(n).to_bytes(8, "big")


def _empty_schema() -> dict[str, Any]:
    return {"blocks": {}, "meta": {}}


class _LmdbSink:
    """Put records into one :class:`Lmdb`, header last."""

    def __init__(self, path: Path) -> None:
        self.store = Lmdb(path, readonly=False, create=True, lock=True)
        self.path = path

    def put_record(
        self, ordinal: int, record: int, made: Any, record_meta: Mapping[str, Any] | None
    ) -> None:
        with self.store.begin(write=True) as txn:
            txn.put(_key(_RECORD, record), json.dumps(dict(record_meta or {})).encode())
            if made.system is not None:
                txn.put(_key(_SYSTEM, record), made.system)
            for offset, blob in enumerate(made.frames):
                txn.put(_key(_FRAME, ordinal + offset), blob)

    def commit(self, header: Mapping[str, Any], index: Mapping[str, np.ndarray]) -> None:
        document = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "layout": MOLREC_LAYOUT,
            "layout_version": MOLREC_LAYOUT_VERSION,
            **dict(header),
        }
        with self.store.begin(write=True) as txn:
            txn.put(_INDEX, frame_bytes.encode({_INDEX_BLOCK: index}, {}))
            txn.put(_META, json.dumps(document).encode())
        self.store.sync()
        self.store.close()
        Path(f"{self.path}-lock").unlink(missing_ok=True)


class _Hdf5Sink:
    """Append records into one :class:`Hdf5`, header last."""

    def __init__(self, path: Path) -> None:
        self.store = Hdf5(path, mode="w")
        self._record_meta: list[str] = []

    def put_record(
        self, ordinal: int, record: int, made: Any, record_meta: Mapping[str, Any] | None
    ) -> None:
        del ordinal, record
        self.store.append("system_bytes", made.system)
        for blob in made.frames:
            self.store.append("frame_bytes", blob)
        self._record_meta.append(json.dumps(dict(record_meta or {})))

    def commit(self, header: Mapping[str, Any], index: Mapping[str, np.ndarray]) -> None:
        n = int(header["n_records"])
        for name, values in index.items():
            self.store.write_array(f"index/{name}", np.asarray(values).reshape(n))
        self.store.write_array("record_meta", np.asarray(self._record_meta, dtype=object))
        systems = self.store.offsets("system_bytes") if n else [0]
        frames = self.store.offsets("frame_bytes") if int(header["n_frames"]) else [0]
        self.store.write_array("system_offset", np.asarray(systems, dtype=np.uint64))
        self.store.write_array("frame_offset", np.asarray(frames, dtype=np.uint64))
        document = {"format": FORMAT, "format_version": FORMAT_VERSION, **dict(header)}
        self.store.write_json("meta", document)
        self.store.close()


class MrecWriter:
    """Append records, then commit them by renaming a partial file onto *path*.

    Args:
        path: The file to create. Refuses to overwrite. The collection appears
            there only when :meth:`close` commits it.
        backend: :class:`Lmdb` or :class:`Hdf5`. The class, not an open file.
        units: Quantity -> unit. Stored in the collection header.
        meta: Extra collection fields (``source_id``, ``coordinate``). ``units``
            from the argument wins when both name it.

    Example::

        with MrecWriter(path, backend=Lmdb, units={"length": "angstrom"}) as out:
            out.write_record(frames, system=system, steps=[0, 5, 9])
    """

    def __init__(
        self,
        path: str | Path,
        *,
        backend: type[Lmdb] | type[Hdf5],
        units: Mapping[str, str],
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        if backend is not Lmdb and backend is not Hdf5:
            raise TypeError(f"mrec backend {backend!r} is not Lmdb or Hdf5")
        self.path = Path(path).expanduser()
        if self.path.exists():
            raise FileExistsError(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._partial = self.path.with_name(f"{self.path.name}.{os.getpid()}.partial")
        self._partial.unlink(missing_ok=True)
        Path(f"{self._partial}-lock").unlink(missing_ok=True)
        self._collection = {**dict(meta or {}), "units": dict(units)}
        self._schema: dict[str, Any] | None = None
        self._index: dict[str, list[Any]] = {}
        self._first: list[int] = []
        self._frames: list[int] = []
        self._atoms: list[int] = []
        self._ordinal = 0
        self._sink: _LmdbSink | _Hdf5Sink | None = (
            _LmdbSink(self._partial) if backend is Lmdb else _Hdf5Sink(self._partial)
        )

    def __enter__(self) -> MrecWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def write_record(
        self,
        frames: Sequence[Any],
        *,
        system: Any | None = None,
        steps: Sequence[int] | None = None,
        index: Mapping[str, Any] | None = None,
        record_meta: Mapping[str, Any] | None = None,
    ) -> None:
        """Append one record.

        Args:
            frames: The record's frames, in order. Their meta is the per-step meta.
            system: What does not change over the record, written once.
            steps: One strictly increasing step per frame. Defaults to ``0..n-1``.
            index: Columns stored beside the record so a reader can size it
                without decoding it. The first record's columns are the collection's.
            record_meta: JSON stored with the record and not decoded into frames.

        Raises:
            ValueError: The record's declaration or index columns differ from
                the collection's, or the writer is already closed.
        """
        if self._sink is None:
            raise ValueError(f"{self.path} is already closed")
        made = encode_record(
            frames,
            system=system,
            steps=steps,
            index=index,
            schema=self._schema,
            index_names=None if not self._first else self._index.keys(),
            record_index=len(self._first),
        )
        self._schema = made.schema
        if not self._first:
            self._index = {name: [] for name in made.index}
        record = len(self._first)
        self._sink.put_record(self._ordinal, record, made, record_meta)
        self._first.append(self._ordinal)
        self._frames.append(len(made.frames))
        self._atoms.append(made.n_atoms)
        self._ordinal += len(made.frames)
        for name, value in made.index.items():
            self._index[name].append(value)

    def close(self) -> None:
        """Write the index and the header — the commit — and move the file into place."""
        sink = self._sink
        if sink is None:
            return
        self._sink = None
        n = len(self._first)
        columns: dict[str, np.ndarray] = {
            "first_frame": np.asarray(self._first, dtype=np.uint64).reshape(n),
            "n_frames": np.asarray(self._frames, dtype=np.uint64).reshape(n),
            "n_atoms": np.asarray(self._atoms, dtype=np.uint64).reshape(n),
        }
        for name, values in self._index.items():
            columns[name] = np.asarray(values).reshape(n)
        header = {
            "collection": self._collection,
            "sequence_schema": self._schema or _empty_schema(),
            "n_records": n,
            "n_frames": self._ordinal,
            "index_columns": sorted(self._index),
        }
        sink.commit(header, columns)
        if self.path.exists():
            raise FileExistsError(
                f"{self.path} appeared while this collection was being written; "
                f"it is left at {self._partial}"
            )
        os.replace(self._partial, self.path)


def _accepted(header: Mapping[str, Any], *layouts: str) -> bool:
    if header.get("format") == FORMAT:
        return True
    return header.get("layout") in layouts


class _LmdbView:
    """Read an mrec collection out of one :class:`Lmdb`."""

    def __init__(self, store: Lmdb) -> None:
        self.store = store
        self.path = store.path
        raw = store.get(_META)
        if raw is None:
            raise ValueError(f"{self.path}: no 'meta' key — not a committed collection")
        self.header = json.loads(raw)
        if not _accepted(self.header, MOLREC_LAYOUT):
            raise ValueError(
                f"{self.path}: format {self.header.get('format')!r}, "
                f"layout {self.header.get('layout')!r}; expected format {FORMAT!r}"
            )
        index = frame_bytes.decode(store.get(_INDEX) or b"").blocks[_INDEX_BLOCK]
        self.index = {name: np.array(column) for name, column in index.items()}
        self._check_prefix()

    def _check_prefix(self) -> None:
        first = self.index["first_frame"]
        counts = self.index["n_frames"]
        expected = np.concatenate([[0], np.cumsum(counts)[:-1]]) if len(counts) else first
        if not np.array_equal(first, expected) or int(counts.sum()) != int(self.header["n_frames"]):
            raise ValueError(f"{self.path}: index first_frame is not the prefix sum of n_frames")

    def stage(self, record: int) -> tuple[bytes | None, tuple[bytes, ...]]:
        first = int(self.index["first_frame"][record])
        count = int(self.index["n_frames"][record])
        with self.store.begin(buffers=True) as txn:
            raw = txn.get(_key(_SYSTEM, record))
            system = None if raw is None else bytes(raw)
            frames: list[bytes] = []
            if count:
                cursor = txn.cursor()
                if not cursor.set_key(_key(_FRAME, first)):
                    raise ValueError(f"{self.path}: frame {first} of record {record} is missing")
                for _ in range(count):
                    frames.append(bytes(cursor.value()))
                    cursor.next()
        return system, tuple(frames)

    def close(self) -> None:
        self.store.close()


class _Hdf5View:
    """Read an mrec collection out of one :class:`Hdf5`."""

    def __init__(self, store: Hdf5) -> None:
        self.store = store
        self.path = store.path
        if "meta" not in store:
            raise ValueError(f"{self.path}: no 'meta' dataset — not a committed collection")
        self.header = store.read_json("meta")
        if not _accepted(self.header, HDF5_LAYOUT):
            raise ValueError(
                f"{self.path}: format {self.header.get('format')!r}, "
                f"layout {self.header.get('layout')!r}; expected format {FORMAT!r}"
            )
        missing = [name for name in ("index", "system_offset", "frame_offset") if name not in store]
        if missing:
            raise ValueError(f"{self.path}: index is missing {missing[0]}")
        self.index = store.columns("index")
        absent = [name for name in _BINDING if name not in self.index]
        if absent:
            raise ValueError(f"{self.path}: index is missing {absent[0]}")
        self._system_offset = np.asarray(store.array("system_offset"), dtype=np.uint64)
        self._frame_offset = np.asarray(store.array("frame_offset"), dtype=np.uint64)
        n_records = int(self.header["n_records"])
        n_frames = int(self.header["n_frames"])
        if self._system_offset.shape != (n_records + 1,) or self._frame_offset.shape != (
            n_frames + 1,
        ):
            raise ValueError(f"{self.path}: offset arrays do not match the header")
        self._check_prefix()
        store.close()

    def _check_prefix(self) -> None:
        first = self.index["first_frame"]
        counts = self.index["n_frames"]
        expected = np.concatenate([[0], np.cumsum(counts)[:-1]]) if len(counts) else first
        if not np.array_equal(first, expected) or int(counts.sum()) != int(self.header["n_frames"]):
            raise ValueError(f"{self.path}: index first_frame is not the prefix sum of n_frames")

    def stage(self, record: int) -> tuple[bytes | None, tuple[bytes, ...]]:
        system_at = int(self._system_offset[record])
        system_to = int(self._system_offset[record + 1])
        system = (
            None
            if system_at == system_to
            else self.store.span("system_bytes", system_at, system_to)
        )
        first = int(self.index["first_frame"][record])
        count = int(self.index["n_frames"][record])
        frames: list[bytes] = []
        for offset in range(count):
            start = int(self._frame_offset[first + offset])
            stop = int(self._frame_offset[first + offset + 1])
            frames.append(self.store.span("frame_bytes", start, stop))
        return system, tuple(frames)

    def close(self) -> None:
        self.store.close()


class MrecRecords:
    """One mrec collection, addressed by an already-open :class:`Lmdb` or :class:`Hdf5`.

    Index ``i`` is record ``i``: :meth:`stage` copies its blobs, :meth:`realize`
    builds molpy frames on the calling thread.

    Args:
        store: The open engine. LMDB files molrec wrote are accepted when their
            header says ``layout: mrec-lmdb``. molhub's own files say
            ``format: mrec``.
    """

    def __init__(self, store: Lmdb | Hdf5) -> None:
        if isinstance(store, Lmdb):
            self._view: _LmdbView | _Hdf5View = _LmdbView(store)
        elif isinstance(store, Hdf5):
            self._view = _Hdf5View(store)
        else:
            raise TypeError(f"mrec records take an Lmdb or an Hdf5, not {type(store).__name__}")
        self.path = self._view.path
        self.header = self._view.header
        self.index = self._view.index

    @property
    def units(self) -> dict[str, str]:
        """The collection's quantity -> unit map."""
        return dict(self.header["collection"]["units"])

    @property
    def collection_meta(self) -> dict[str, Any]:
        """The collection's meta document, ``units`` included."""
        return dict(self.header["collection"])

    def __len__(self) -> int:
        return int(self.header["n_records"])

    def stage(self, index: int) -> tuple[bytes | None, tuple[bytes, ...]]:
        """Copy record *index* off the store. No molpy frames.

        Raises:
            IndexError: *index* is out of range.
        """
        record = int(index)
        n = len(self)
        if record < 0:
            record += n
        if record < 0 or record >= n:
            raise IndexError(record)
        return self._view.stage(record)

    def realize(self, staged: tuple[bytes | None, Sequence[bytes]]) -> tuple[Any, ...]:
        """Build the molpy frames for blobs returned by :meth:`stage`."""
        return realize_record(staged)

    def read_record(self, index: int) -> tuple[Any, ...]:
        """Record *index* as molpy frames."""
        return self.realize(self.stage(index))

    def __getitem__(self, index: int) -> tuple[Any, ...]:
        return self.read_record(index)

    def keys(self) -> tuple[str, ...]:
        """Each record's identifier: the index ``record_id`` column, else its position."""
        column = self.index.get("record_id")
        if column is None:
            return tuple(str(record) for record in range(len(self)))
        return tuple(str(value) for value in column)

    def atoms_per_record(self) -> np.ndarray:
        """Atom rows each record contributes: ``n_atoms × max(n_frames, 1)``."""
        n_atoms = self.index["n_atoms"].astype(np.int64)
        return n_atoms * np.maximum(self.index["n_frames"].astype(np.int64), 1)

    def molecule_index(self) -> np.ndarray:
        """Dense molecule code per record, from the index ``molecule`` column.

        Raises:
            KeyError: The collection was written without one.
        """
        return self._index_column("molecule").astype(np.int64)

    def element_mask(self) -> np.ndarray:
        """Bit ``Z`` set for each element a record carries, from the index.

        Raises:
            KeyError: The collection was written without one.
        """
        return self._index_column("element_mask").astype(np.uint64)

    def _index_column(self, name: str) -> np.ndarray:
        column = self.index.get(name)
        if column is None:
            raise KeyError(f"{self.path}: the collection index has no {name!r} column")
        return column

    def close(self) -> None:
        self._view.close()

    def __enter__(self) -> MrecRecords:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __getstate__(self) -> dict[str, Any]:
        state = dict(self.__dict__)
        state.pop("_lock_obj", None)
        return state
