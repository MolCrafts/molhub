"""HDF5 file: datasets and groups, nothing about what the arrays mean.

A collection and a THEMol shard both open one of these. The record each of
them builds from the arrays lives in its own module.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from molhub.io.collection import instance_lock

__all__ = ["Hdf5"]

_CHUNK = 1 << 20


def _require_h5py() -> None:
    return None


class _Blob:
    """A resizable ``uint8`` dataset and the start offset of each appended value."""

    def __init__(self, handle: h5py.File, name: str) -> None:
        self._data = handle.create_dataset(
            name, shape=(0,), maxshape=(None,), dtype=np.uint8, chunks=(_CHUNK,)
        )
        self._end = 0
        self.offsets = [0]

    def append(self, blob: bytes | None) -> None:
        if not blob:
            self.offsets.append(self._end)
            return
        raw = np.frombuffer(blob, dtype=np.uint8)
        end = self._end + int(raw.shape[0])
        self._data.resize((end,))
        self._data[self._end : end] = raw
        self._end = end
        self.offsets.append(self._end)


def _column(dataset: h5py.Dataset) -> np.ndarray:
    if h5py.check_string_dtype(dataset.dtype) is not None:
        return np.asarray(dataset.asstr()[:], dtype=str)
    return np.array(dataset)


def _span(dataset: h5py.Dataset, start: int, stop: int) -> bytes:
    if start == stop:
        return b""
    return np.ascontiguousarray(dataset[start:stop]).tobytes()


def _snapshot(node: Any) -> Any:
    """One group as nested dicts, one string dataset as ``str``, else an array."""
    if isinstance(node, h5py.Group):
        return {str(key): _snapshot(node[key]) for key in node.keys()}
    if h5py.check_string_dtype(node.dtype) is not None:
        value = node.asstr()[()]
        if isinstance(value, bytes):
            return value.decode("utf-8")
        if isinstance(value, str):
            return value
        return np.asarray(value)
    return np.array(node[()])


class Hdf5:
    """One HDF5 file.

    A read handle is per thread: h5py files are not shared across threads.
    ``locking=False`` lets each thread open the file itself. A file that is
    only read stays where it is, including on a shared filesystem; the lock
    is disabled because no process writes it. A write handle
    is the one this object opened, and it appears at *path* only after the
    caller renames the file into place — this class writes where it was
    pointed.

    Args:
        path: The file.
        mode: ``"r"`` or ``"w"``. ``"w"`` creates the parent and a new file.
    """

    def __init__(self, path: str | Path, *, mode: str = "r") -> None:
        _require_h5py()
        self.path = Path(path).expanduser()
        if mode not in ("r", "w"):
            raise ValueError(f"HDF5 mode {mode!r} is not 'r' or 'w'")
        self.mode = mode
        self._write: h5py.File | None = None
        self._blobs: dict[str, _Blob] = {}
        if mode == "w":
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write = h5py.File(self.path, "w")
        elif not self.path.is_file():
            raise FileNotFoundError(self.path.resolve())
        else:
            self.path = self.path.resolve()

    def file(self) -> h5py.File:
        """The handle for this thread. A writer returns the handle it created."""
        if self._write is not None:
            return self._write
        local = getattr(self, "_local", None)
        if local is None:
            with instance_lock(self):
                local = getattr(self, "_local", None)
                if local is None:
                    local = self._local = threading.local()
        handle = getattr(local, "handle", None)
        if handle is None:
            handle = local.handle = h5py.File(self.path, "r", locking=False)
        return handle

    def keys(self) -> tuple[str, ...]:
        """Names at the root, in file order."""
        return tuple(str(key) for key in self.file().keys())

    def __contains__(self, name: str) -> bool:
        return name in self.file()

    def read_json(self, name: str) -> Any:
        """A ``uint8`` dataset of UTF-8 JSON."""
        handle = self.file()
        if name not in handle:
            raise KeyError(name)
        return json.loads(np.asarray(handle[name]).tobytes())

    def columns(self, group: str) -> dict[str, np.ndarray]:
        """Every dataset in *group*, loaded."""
        node = self.file()[group]
        return {str(name): _column(node[name]) for name in node.keys()}

    def array(self, name: str) -> np.ndarray:
        """One dataset, copied."""
        return np.array(self.file()[name])

    def span(self, name: str, start: int, stop: int) -> bytes:
        """``dataset[start:stop]`` as bytes. An empty span is ``b""``."""
        return _span(self.file()[name], start, stop)

    def snapshot(self, name: str) -> Any:
        """Group *name* as nested dicts of arrays and strings. No HDF5 objects."""
        return _snapshot(self.file()[name])

    def append(self, name: str, blob: bytes | None) -> None:
        """Append *blob* to a ``uint8`` dataset, recording an empty span as a repeated offset."""
        if self._write is None:
            raise ValueError(f"{self.path} is open read-only")
        found = self._blobs.get(name)
        if found is None:
            found = self._blobs[name] = _Blob(self._write, name)
        found.append(blob)

    def offsets(self, name: str) -> list[int]:
        """Start offset of each value :meth:`append` accepted, plus the end."""
        return self._blobs[name].offsets

    def write_array(self, name: str, values: np.ndarray) -> None:
        """Create dataset *name*. A slash in *name* addresses a group member."""
        if self._write is None:
            raise ValueError(f"{self.path} is open read-only")
        if "/" in name:
            group_name, member = name.split("/", 1)
            group = self._write.require_group(group_name)
            self._write_member(group, member, values)
            return
        self._write_member(self._write, name, values)

    def _write_member(self, parent: h5py.Group, name: str, values: np.ndarray) -> None:
        array = np.asarray(values)
        if array.dtype.kind in "SUO":
            text = np.asarray([str(value) for value in array.reshape(-1)], dtype=object)
            parent.create_dataset(
                name, data=text.reshape(array.shape), dtype=h5py.string_dtype(encoding="utf-8")
            )
            return
        parent.create_dataset(name, data=array)

    def write_json(self, name: str, document: Any) -> None:
        """UTF-8 JSON as a ``uint8`` dataset. Attributes stop at 64 KiB; a header may not."""
        if self._write is None:
            raise ValueError(f"{self.path} is open read-only")
        raw = np.frombuffer(json.dumps(document).encode(), dtype=np.uint8)
        self._write.create_dataset(name, data=raw.copy())

    def close(self) -> None:
        """Close this thread's read handle, or the write handle."""
        if self._write is not None:
            self._write.close()
            self._write = None
            return
        local = getattr(self, "_local", None)
        if local is None:
            return
        handle = getattr(local, "handle", None)
        if handle is not None:
            handle.close()
            local.handle = None

    def __enter__(self) -> Hdf5:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __getstate__(self) -> dict[str, Any]:
        state = dict(self.__dict__)
        state["_write"] = None
        state.pop("_local", None)
        state.pop("_lock_obj", None)
        state["_blobs"] = {}
        return state
