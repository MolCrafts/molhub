"""``LmdbCache`` — opaque bytes stored against a file fingerprint."""

from __future__ import annotations

import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from molpy import Block, Box, Frame

from molhub.cache.lmdb import LmdbCache
from molhub.io.collection import decode_sample, encode_sample


def _source(tmp_path, name: str = "shard.h5", payload: bytes = b"v1"):
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def _key(index: int) -> bytes:
    return int(index).to_bytes(8, "big")


def _cached(pair: tuple[LmdbCache, bytes]) -> bytes | None:
    cache, key = pair
    return cache.get(key)


def _frame() -> Frame:
    frame = Frame()
    frame["atoms"] = Block(
        {
            "element": np.array(["O", "H"], dtype="U3"),
            "number": np.array([8, 1], dtype=np.int64),
            "x": np.array([0.1, -1.5], dtype=np.float64),
        }
    )
    frame["hessian"] = Block(
        {
            "row": np.array([0, 1], dtype=np.int32),
            "value": np.array([0.1, -2.5], dtype=np.float64),
        }
    )
    frame.meta = {"energy": -1.0, "mapped_isomeric_smiles": "C", "total_charge": 0}
    frame.box = Box(
        np.diag([10.0, 11.0, 12.0]),
        pbc=[True, False, True],
        origin=[1.0, 2.0, 3.0],
    )
    return frame


class TestLmdbCache:
    def test_a_missing_row_is_none(self, tmp_path):
        cache = LmdbCache([_source(tmp_path)], "rows", root=tmp_path / "rows")
        assert cache.get(_key(0)) is None

    def test_put_then_get_returns_the_bytes(self, tmp_path):
        cache = LmdbCache([_source(tmp_path)], "rows", root=tmp_path / "rows")
        cache.put(_key(2), b"row-2")
        assert cache.get(_key(2)) == b"row-2"
        assert cache.get(_key(1)) is None

    def test_a_changed_source_is_a_different_cache(self, tmp_path):
        path = _source(tmp_path)
        cache = LmdbCache([path], "rows", root=tmp_path / "rows")
        cache.put(_key(0), b"old")
        path.write_bytes(b"v2!")
        assert LmdbCache([path], "rows", root=tmp_path / "rows").get(_key(0)) is None

    def test_a_different_field_is_a_different_cache(self, tmp_path):
        path = _source(tmp_path)
        LmdbCache([path], "rows.v1", root=tmp_path / "rows").put(_key(0), b"one")
        assert LmdbCache([path], "rows.v2", root=tmp_path / "rows").get(_key(0)) is None

    def test_a_missing_source_does_not_raise(self, tmp_path):
        cache = LmdbCache([tmp_path / "gone.h5"], "rows", root=tmp_path / "rows")
        cache.put(_key(0), b"x")
        assert cache.get(_key(0)) == b"x"

    def test_threads_read_one_environment(self, tmp_path):
        cache = LmdbCache([_source(tmp_path)], "rows", root=tmp_path / "rows")
        cache.put(_key(0), b"a")
        cache.put(_key(1), b"b")
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(cache.get, [_key(1), _key(0), _key(1)])) == [b"b", b"a", b"b"]

    def test_two_handles_in_one_process_share_the_file(self, tmp_path):
        path = _source(tmp_path)
        first = LmdbCache([path], "rows", root=tmp_path / "rows")
        first.put(_key(0), b"row")
        second = LmdbCache([path], "rows", root=tmp_path / "rows")
        assert second.get(_key(0)) == b"row"
        first.close()
        assert second.get(_key(0)) == b"row"

    def test_a_spawned_worker_reopens_the_file(self, tmp_path):
        cache = LmdbCache([_source(tmp_path)], "rows", root=tmp_path / "rows")
        cache.put(_key(3), b"row")
        context = mp.get_context("spawn")
        with context.Pool(1) as pool:
            assert pool.apply(_cached, ((cache, _key(3)),)) == b"row"


class TestEncodeSample:
    def test_round_trip_keeps_columns_meta_and_box(self):
        other = Frame()
        other["atoms"] = Block({"x": np.array([2.0], dtype=np.float64)})
        other.meta = {"energy": 0.5, "step_index": 1}
        restored = decode_sample(encode_sample((_frame(), other)))
        first, second = restored
        assert first["hessian"]["row"].dtype == np.dtype(np.int32)
        assert first["hessian"]["value"].dtype == np.dtype(np.float64)
        assert np.array_equal(first["atoms"]["element"], np.array(["O", "H"]))
        assert np.array_equal(first["atoms"]["x"], np.array([0.1, -1.5]))
        assert first.meta["mapped_isomeric_smiles"] == "C"
        assert first.meta["total_charge"] == 0
        assert first.meta["energy"] == -1.0
        assert first.box.pbc.tolist() == [True, False, True]
        assert np.allclose(np.asarray(first.box.matrix), np.diag([10.0, 11.0, 12.0]))
        assert np.allclose(np.asarray(first.box.origin), [1.0, 2.0, 3.0])
        assert second.meta["step_index"] == 1
        assert second.meta["energy"] == 0.5
        first["atoms"]["x"][0] = 4.0

    def test_a_foreign_payload_is_refused(self):
        with pytest.raises(ValueError, match="magic"):
            decode_sample(b"nope")
