"""LMDB environment: keys and values, nothing about what the bytes mean.

A collection, an ASE row file, and a row cache all open one of these and
decide their own keys. This module does not import a format.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

__all__ = ["Lmdb"]

_MAP_SIZE = 1 << 40
_SHARED: dict[str, tuple[Any, int]] = {}
_SHARED_LOCK = threading.Lock()


def _backend():
    try:
        import lmdb
    except ImportError as error:
        raise ImportError(
            "This store needs the lmdb package. Install with `pip install lmdb`."
        ) from error
    return lmdb


class Lmdb:
    """One single-file LMDB environment.

    Args:
        path: The file. A directory environment is not this class.
        readonly: Open without a writer lock when True.
        create: Create the file and its parent. Refuses to imply creation
            from a missing file on a read.
        share: Reuse the environment this process already opened at *path*.
            LMDB refuses a second ``open`` of a file the process holds, which
            is what a cache meets when a dataset is unpickled beside the one
            that filled it. Workers are new processes and open their own.
        map_size: Address-space reservation, not an allocation.
        lock: Process lock. Defaults to True for a writer and False for a
            readonly open.
        max_readers: Reader slots. A worker pool stages several reads at once.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        readonly: bool = True,
        create: bool = False,
        share: bool = False,
        map_size: int = _MAP_SIZE,
        lock: bool | None = None,
        max_readers: int = 126,
    ) -> None:
        self.path = Path(path).expanduser()
        if not readonly:
            self.path = self.path.resolve()
        else:
            self.path = self.path.resolve()
            if not self.path.is_file() and not create:
                raise FileNotFoundError(self.path)
        self.readonly = bool(readonly)
        self.create = bool(create)
        self.share = bool(share)
        self.map_size = int(map_size)
        self.lock = (not self.readonly) if lock is None else bool(lock)
        self.max_readers = int(max_readers)
        self._env: Any = None
        self._opened: str | None = None
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def _open(self) -> Any:
        env = self._env
        if env is not None:
            return env
        path = str(self.path)
        if not self.share:
            self._env = _backend().open(
                path,
                subdir=False,
                readonly=self.readonly,
                lock=self.lock,
                map_size=self.map_size,
                create=self.create,
                max_readers=self.max_readers,
                readahead=self.readonly,
                meminit=False,
            )
            self._opened = path
            return self._env
        with _SHARED_LOCK:
            if self._env is not None:
                return self._env
            found = _SHARED.get(path)
            if found is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                env = _backend().open(
                    path,
                    subdir=False,
                    readonly=self.readonly,
                    lock=self.lock,
                    map_size=self.map_size,
                    create=True,
                    max_readers=self.max_readers,
                    sync=False,
                    metasync=False,
                    readahead=False,
                    meminit=False,
                )
                _SHARED[path] = (env, 1)
            else:
                env, count = found
                _SHARED[path] = (env, count + 1)
            self._env = env
            self._opened = path
            return env

    def begin(self, *, write: bool = False, buffers: bool = False) -> Any:
        """A transaction. The caller closes it."""
        return self._open().begin(write=write, buffers=buffers)

    def get(self, key: bytes) -> bytes | None:
        """Copy the value out of a read transaction, or None when *key* is absent."""
        with self.begin() as txn:
            raw = txn.get(key)
        return None if raw is None else bytes(raw)

    def put(self, key: bytes, value: bytes) -> None:
        """Store *value* at *key*. A second put replaces it."""
        with self.begin(write=True) as txn:
            txn.put(key, value)

    def delete(self, key: bytes) -> None:
        """Remove *key* when it is present."""
        with self.begin(write=True) as txn:
            txn.delete(key)

    def sync(self) -> None:
        """Flush the environment."""
        self._open().sync(True)

    def keys(self) -> Iterator[bytes]:
        """Every key, copied out of one read transaction."""
        with self.begin() as txn:
            cursor = txn.cursor()
            found = [bytes(key) for key, _ in cursor]
        return iter(found)

    def close(self) -> None:
        """Drop this handle. A shared environment closes with its last handle."""
        env = self._env
        path = self._opened
        self._env = None
        self._opened = None
        if env is None:
            return
        if not self.share or path is None:
            env.close()
            return
        with _SHARED_LOCK:
            found = _SHARED.get(path)
            if found is None or found[0] is not env:
                return
            count = found[1] - 1
            if count <= 0:
                _SHARED.pop(path, None)
                env.close()
            else:
                _SHARED[path] = (env, count)

    def __enter__(self) -> Lmdb:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __getstate__(self) -> dict[str, Any]:
        state = dict(self.__dict__)
        state["_env"] = None
        state["_opened"] = None
        return state

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
