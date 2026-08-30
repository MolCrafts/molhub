"""Shared aselmdb fixture writer for the io test package.

Import by package path (``from tests.test_io.conftest import write_aselmdb``);
``tests/test_dataset/test_omol25.py`` reuses it to synthesise OMol25 extracts.
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path

import lmdb
import numpy as np


def _encode(obj: object) -> bytes:
    def default(item: object) -> object:
        if isinstance(item, np.ndarray):
            return {"__ndarray__": [list(item.shape), str(item.dtype), item.ravel().tolist()]}
        if isinstance(item, np.integer):
            return int(item)
        if isinstance(item, np.floating):
            return float(item)
        raise TypeError(type(item))

    return zlib.compress(json.dumps(obj, default=default).encode("utf-8"))


def write_aselmdb(
    path: Path,
    rows: dict[int, dict],
    *,
    nextid: int,
    deleted: list[int] | None = None,
) -> None:
    """Write a synthetic ``*.aselmdb`` file in the published OMol25 layout."""
    env = lmdb.open(str(path), subdir=False, map_size=1 << 20)
    with env.begin(write=True) as txn:
        for row_id, record in rows.items():
            txn.put(str(row_id).encode("ascii"), _encode(record))
        txn.put(b"nextid", _encode(nextid))
        if deleted is not None:
            txn.put(b"deleted_ids", _encode(deleted))
    env.close()
