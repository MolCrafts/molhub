"""Batched fetch: stage off-thread, realize on the caller."""

from __future__ import annotations

import threading
from collections.abc import Sequence

from molhub.dataset.prefetch import Prefetch, getitems


class _Records(Prefetch):
    """Four indices. ``stage`` waits until every worker has entered."""

    def __init__(self, *, workers: int, barrier: bool = False) -> None:
        self.prefetch_workers = workers
        self.stage_threads: list[int] = []
        self.realize_threads: list[int] = []
        self._guard = threading.Lock()
        self._barrier = threading.Barrier(4) if barrier else None

    def __len__(self) -> int:
        return 4

    def __getitem__(self, index: int, /) -> tuple[str, int]:
        return self.realize(self.stage(index))

    def stage(self, index: int) -> tuple[str, int]:
        with self._guard:
            self.stage_threads.append(threading.get_ident())
        if self._barrier is not None:
            self._barrier.wait(timeout=5)
        return ("staged", int(index))

    def realize(self, staged: tuple[str, int]) -> tuple[str, int]:
        with self._guard:
            self.realize_threads.append(threading.get_ident())
        return staged


class TestGetitems:
    def test_order_is_kept_and_frames_are_built_on_the_caller(self) -> None:
        ds = _Records(workers=4, barrier=True)
        caller = threading.get_ident()
        order = [3, 1, 0, 2]
        assert ds.__getitems__(order) == [("staged", i) for i in order]
        assert len(set(ds.stage_threads)) > 1
        assert ds.realize_threads == [caller] * 4

    def test_one_worker_reads_serially_on_the_caller(self) -> None:
        ds = _Records(workers=1)
        caller = threading.get_ident()
        assert getitems(ds, [2, 0], workers=1) == [("staged", 2), ("staged", 0)]
        assert ds.stage_threads == [caller, caller]
        assert ds.realize_threads == [caller, caller]

    def test_a_single_index_does_not_open_a_pool(self) -> None:
        ds = _Records(workers=4)
        caller = threading.get_ident()
        assert getitems(ds, [1], workers=4) == [("staged", 1)]
        assert ds.stage_threads == [caller]
        assert ds.realize_threads == [caller]


def test_a_cached_batch_reads_the_source_only_for_misses(tmp_path) -> None:
    """A hit rebuilds on the caller. The source is read only for a miss."""
    import numpy as np
    from molpy import Block, Frame

    from molhub.cache.lmdb import LmdbCache
    from molhub.io.collection import decode_sample, encode_sample

    class _Frames(Prefetch):
        def __init__(self) -> None:
            source = tmp_path / "shard.h5"
            source.write_bytes(b"shard")
            self.cache = LmdbCache([source], "rows", root=tmp_path / "rows")
            self.prefetch_workers = 4
            self.reads: list[int] = []
            self.realize_threads: list[int] = []

        def __len__(self) -> int:
            return 2

        def stage(self, index: int) -> tuple[str, object]:
            key = int(index).to_bytes(8, "big")
            blob = self.cache.get(key)
            if blob is not None:
                return ("cached", blob)
            self.reads.append(int(index))
            return ("source", int(index))

        def realize(self, staged: tuple[str, object]) -> tuple[Frame, ...]:
            self.realize_threads.append(threading.get_ident())
            if staged[0] == "cached":
                return decode_sample(staged[1])  # type: ignore[arg-type]
            index = int(staged[1])  # type: ignore[arg-type]
            frame = Frame()
            frame["atoms"] = Block({"x": np.array([float(index)], dtype=np.float64)})
            frame.meta = {"i": index}
            self.cache.put(index.to_bytes(8, "big"), encode_sample((frame,)))
            return (frame,)

    def _ids(rows: list[tuple[Frame, ...]]) -> list[int]:
        return [int(row[0].meta["i"]) for row in rows]

    dataset = _Frames()
    caller = threading.get_ident()
    assert _ids(dataset.__getitems__([1, 0])) == [1, 0]
    assert dataset.realize_threads == [caller, caller]
    dataset.reads.clear()
    dataset.realize_threads.clear()
    assert _ids(dataset.__getitems__([0, 1])) == [0, 1]
    assert dataset.reads == []
    assert dataset.realize_threads == [caller, caller]


def test_getitems_accepts_a_sequence_of_indices() -> None:
    class _Plain:
        def __getitem__(self, index: int, /) -> int:
            return int(index) + 1

    got: Sequence[int] = getitems(_Plain(), [4, 5], workers=4)
    assert got == [5, 6]
