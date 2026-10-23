"""ASE AtomsRow bytes.

The published value is zlib-compressed UTF-8 JSON. Arrays travel as
``{"__ndarray__": [shape, dtype, flat]}``. The container that holds those
values is not this module: a caller passes the raw value, or an :class:`Lmdb`
whose keys are the decimal row ids ASE writes.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from molhub.io.lmdb import Lmdb

__all__ = ["AseRows", "RESERVED_KEYS", "decode_row", "encode_row"]

RESERVED_KEYS = frozenset({"nextid", "deleted_ids", "metadata"})


def _json_object(dct: dict[str, Any]) -> Any:
    """Restore arrays. Ignore foreign type tags; leave the rest as a dict."""
    packed = dct.get("__ndarray__")
    if packed is not None:
        shape, dtype, data = packed
        return np.asarray(data, dtype=dtype).reshape(shape)
    if "__complex__" in dct:
        real, imag = dct["__complex__"]
        return complex(real, imag)
    dct.pop("__ase_objtype__", None)
    dct.pop("__datetime__", None)
    return dct


def decode_row(raw: bytes) -> Any:
    """One ASE value: zlib, then UTF-8 JSON, with the ndarray hook."""
    return json.loads(zlib.decompress(raw).decode("utf-8"), object_hook=_json_object)


def encode_row(value: Any) -> bytes:
    """The inverse of :func:`decode_row` for a JSON-ready document."""

    def default(item: object) -> object:
        if isinstance(item, np.ndarray):
            return {"__ndarray__": [list(item.shape), str(item.dtype), item.ravel().tolist()]}
        if isinstance(item, np.integer):
            return int(item)
        if isinstance(item, np.floating):
            return float(item)
        raise TypeError(type(item))

    return zlib.compress(json.dumps(value, default=default).encode("utf-8"))


class AseRows:
    """ASE row ids stored in one :class:`Lmdb`.

    Args:
        store: An open environment whose keys are ASCII decimal row ids plus
            the reserved names in :data:`RESERVED_KEYS`.
    """

    def __init__(self, store: Lmdb) -> None:
        self.store = store
        self.path = store.path
        self.ids = tuple(self._load_ids())

    @classmethod
    def open(cls, path: str | Path) -> AseRows:
        """Open *path* read-only. The environment closes with :meth:`close`."""
        return cls(Lmdb(path, readonly=True, lock=False))

    def close(self) -> None:
        """Close the environment."""
        self.store.close()

    def __enter__(self) -> AseRows:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __len__(self) -> int:
        return len(self.ids)

    def __iter__(self) -> Iterator[int]:
        return iter(self.ids)

    def get(self, row_id: int) -> dict[str, Any]:
        """The decoded record for *row_id*, with ``id`` set to that row."""
        raw = self.store.get(str(int(row_id)).encode("ascii"))
        if raw is None:
            raise KeyError(row_id)
        record = decode_row(raw)
        if not isinstance(record, dict):
            raise TypeError(f"ASE row {row_id} is {type(record).__name__}, not a dict")
        out = dict(record)
        out["id"] = int(row_id)
        return out

    def _reserved(self, name: str) -> Any | None:
        raw = self.store.get(name.encode("ascii"))
        if raw is None:
            return None
        return decode_row(raw)

    def _load_ids(self) -> list[int]:
        nextid = self._reserved("nextid")
        deleted = self._reserved("deleted_ids")
        gone = {int(i) for i in (deleted or ())}
        if nextid is None:
            ids: list[int] = []
            for key in self.store.keys():
                name = key.decode("ascii")
                if name in RESERVED_KEYS:
                    continue
                ids.append(int(name))
            ids.sort()
            return ids
        return [i for i in range(1, int(nextid)) if i not in gone]
