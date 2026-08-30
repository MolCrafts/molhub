"""Read-only LMDB table — synthetic files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from tests.test_io.conftest import write_aselmdb as _write

from molhub.io.lmdb import Lmdb


class TestLmdb:
    def test_reads_json_row_and_ndarray(self, tmp_path: Path) -> None:
        path = tmp_path / "one.lmdb"
        pos = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float64)
        _write(
            path,
            {
                1: {
                    "numbers": np.array([1, 8], dtype=np.int64),
                    "positions": pos,
                    "energy": -1.5,
                    "forces": np.zeros((2, 3), dtype=np.float64),
                    "data": {"charge": 0, "spin": 1, "data_id": "x"},
                }
            },
            nextid=2,
        )
        with Lmdb(path) as table:
            assert list(table.ids) == [1]
            row = table.get(1)
        assert row["energy"] == pytest.approx(-1.5)
        assert np.array_equal(row["numbers"], [1, 8])
        assert row["positions"].shape == (2, 3)
        assert row["data"]["data_id"] == "x"
        assert row["id"] == 1

    def test_skips_deleted_ids(self, tmp_path: Path) -> None:
        path = tmp_path / "gap.lmdb"
        _write(
            path,
            {1: {"energy": 0.0}, 3: {"energy": 1.0}},
            nextid=4,
            deleted=[2],
        )
        with Lmdb(path) as table:
            assert list(table.ids) == [1, 3]

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            Lmdb(tmp_path / "nope.lmdb")
