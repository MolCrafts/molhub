"""Opaque bytes in one LMDB file, keyed by a fingerprint of the sources.

The fingerprint is the file's name, size and mtime, plus the field the caller
names — the same selection :class:`~molhub.cache.counts.CountSidecar` uses.
What the bytes mean is the caller's. This module does not import a dataset
or a frame.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from molhub.cache.protocol import Cache
from molhub.io.lmdb import Lmdb

__all__ = ["LmdbCache"]

_MAX_READERS = 256


class LmdbCache(Cache):
    """One LMDB of opaque values for one field over one set of files.

    Args:
        sources: Files the values were read from. Their name, size and
            modification time make the key, together with *field*. A missing
            file contributes ``name:missing`` and does not raise.
        field: What the bytes are, including a version of the decoder that
            produced them. A new decoder is a new field.
        root: Directory the LMDB lives in. Defaults to
            :func:`~molhub.cache.local.runtime_cache_root`, which is
            node-local. An explicit root on a shared filesystem is refused.
            The environment is opened with ``lock=True``.

    The open environment stays in this process. Pickle drops it, and a
    spawned worker opens the same path itself. ``share`` only reuses an
    environment this process already holds.
    """

    def __init__(
        self,
        sources: Sequence[Path | str],
        field: str,
        *,
        root: Path | str | None = None,
    ) -> None:
        from molhub.cache.local import require_node_local, runtime_cache_root

        self.sources = tuple(Path(p) for p in sources)
        self.field = str(field)
        chosen = Path(root) if root is not None else runtime_cache_root()
        self.root = require_node_local(chosen)
        self._store: Lmdb | None = None

    @property
    def key(self) -> str:
        """Fingerprint of the sources and the field."""
        digest = hashlib.blake2b(digest_size=16)
        for path in self.sources:
            try:
                stat = path.stat()
                token = f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}"
            except OSError:
                token = f"{path.name}:missing"
            digest.update(token.encode())
            digest.update(b"\x00")
        digest.update(self.field.encode())
        return digest.hexdigest()

    @property
    def path(self) -> Path:
        """Where this cache is stored."""
        return self.root / f"{self.key}.lmdb"

    def _open(self) -> Lmdb:
        store = self._store
        if store is not None:
            return store
        store = Lmdb(
            self.path,
            readonly=False,
            create=True,
            share=True,
            lock=True,
            max_readers=_MAX_READERS,
        )
        self._store = store
        return store

    def get(self, key: bytes) -> bytes | None:
        """The stored value at *key*, or None when it was never written."""
        return self._open().get(key)

    def put(self, key: bytes, value: bytes) -> None:
        """Store *value* at *key*. A second put replaces it."""
        self._open().put(key, value)

    def close(self) -> None:
        """Drop this handle. A shared environment closes with its last handle."""
        store = self._store
        self._store = None
        if store is not None:
            store.close()

    def __getstate__(self) -> dict[str, Any]:
        state = dict(self.__dict__)
        state["_store"] = None
        return state

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            return
