"""Read-only single-file LMDB table.

On disk: one file (``subdir=False``). Keys are ASCII. Reserved keys are
``nextid``, ``deleted_ids``, ``metadata``. Every other key is an integer
row id. Values are zlib-compressed JSON. NumPy arrays are stored as
``{"__ndarray__": [shape, dtype, flat_data]}``.

This is the layout FairChem ships as ``*.aselmdb``. The reader does not
import ASE and does not reconstruct Atoms.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["Lmdb", "RESERVED_KEYS"]

RESERVED_KEYS = frozenset({"nextid", "deleted_ids", "metadata"})


def _require_lmdb():
    try:
        import lmdb as _lmdb
    except ImportError as error:
        raise ImportError(
            "Reading this table needs the lmdb package. Install with `pip install lmdb`."
        ) from error
    return _lmdb


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


def decode_value(raw: bytes) -> Any:
    """zlib + UTF-8 JSON, with the published ndarray hook."""
    return json.loads(zlib.decompress(raw).decode("utf-8"), object_hook=_json_object)


class Lmdb:
    """One LMDB file as ``row_id → dict``.

    Args:
        path: Single-file LMDB (not a directory).
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        backend = _require_lmdb()
        self._env = backend.open(
            str(self.path),
            subdir=False,
            meminit=False,
            readonly=True,
            lock=False,
            readahead=True,
        )
        self.ids = tuple(self._load_ids())

    def close(self) -> None:
        """Close the environment."""
        self._env.close()

    def __enter__(self) -> Lmdb:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __len__(self) -> int:
        return len(self.ids)

    def __iter__(self) -> Iterator[int]:
        return iter(self.ids)

    def get(self, row_id: int) -> dict[str, Any]:
        """Return the decoded record for *row_id*."""
        with self._env.begin(write=False) as txn:
            raw = txn.get(str(int(row_id)).encode("ascii"))
        if raw is None:
            raise KeyError(row_id)
        record = decode_value(raw)
        if not isinstance(record, Mapping):
            raise TypeError(f"lmdb row {row_id} is {type(record).__name__}, not a dict")
        out = dict(record)
        out["id"] = int(row_id)
        return out

    def _get_reserved(self, name: str) -> Any | None:
        with self._env.begin(write=False) as txn:
            raw = txn.get(name.encode("ascii"))
        if raw is None:
            return None
        return decode_value(raw)

    def _load_ids(self) -> list[int]:
        nextid = self._get_reserved("nextid")
        deleted = self._get_reserved("deleted_ids")
        gone = {int(i) for i in (deleted or ())}
        if nextid is None:
            ids: list[int] = []
            with self._env.begin(write=False) as txn:
                cursor = txn.cursor()
                for key, _ in cursor:
                    name = key.decode("ascii")
                    if name in RESERVED_KEYS:
                        continue
                    ids.append(int(name))
            ids.sort()
            return ids
        return [i for i in range(1, int(nextid)) if i not in gone]
