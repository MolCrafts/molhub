"""``CountSidecar`` — a per-row vector cached against a file fingerprint."""

from __future__ import annotations

import numpy as np
import pytest

from molhub.cache import CountSidecar


@pytest.fixture
def shards(tmp_path):
    a, b = tmp_path / "data0000.lmdb", tmp_path / "data0001.lmdb"
    a.write_bytes(b"first shard")
    b.write_bytes(b"second shard")
    return [a, b]


class TestCountSidecar:
    def test_round_trips_a_vector(self, shards, tmp_path):
        sc = CountSidecar(shards, "graph.natoms", root=tmp_path / "counts")
        counts = np.array([3, 5, 8], dtype=np.int64)
        sc.save(counts)
        assert np.array_equal(sc.load(n_rows=3), counts)

    def test_a_miss_is_None_not_an_error(self, shards, tmp_path):
        sc = CountSidecar(shards, "graph.natoms", root=tmp_path / "counts")
        assert sc.load(n_rows=3) is None

    def test_a_length_mismatch_is_a_miss(self, shards, tmp_path):
        # The caller is asking about a different row set than the one measured.
        # A silently short vector would mis-size every batch built from it.
        sc = CountSidecar(shards, "graph.natoms", root=tmp_path / "counts")
        sc.save(np.array([3, 5, 8], dtype=np.int64))
        assert sc.load(n_rows=4) is None

    def test_a_changed_file_changes_the_key(self, shards, tmp_path):
        # Staleness is not a case analysis: the bytes that identify the file
        # go into the digest, so a replaced shard simply keys elsewhere.
        sc = CountSidecar(shards, "graph.natoms", root=tmp_path / "counts")
        before = sc.key
        shards[0].write_bytes(b"first shard, edited")
        assert CountSidecar(shards, "graph.natoms", root=tmp_path / "counts").key != before

    def test_a_replaced_shard_of_equal_length_still_misses(self, shards, tmp_path):
        # Same size, different content — the modification time separates them.
        sc = CountSidecar(shards, "graph.natoms", root=tmp_path / "counts")
        sc.save(np.array([1, 2], dtype=np.int64))
        import time

        time.sleep(0.01)
        shards[0].write_bytes(b"FIRST SHARD")  # identical length
        assert CountSidecar(shards, "graph.natoms", root=tmp_path / "counts").load(n_rows=2) is None

    def test_reordering_the_shards_changes_the_key(self, shards, tmp_path):
        # Row order follows source order, so two orders are two vectors.
        a = CountSidecar(shards, "graph.natoms", root=tmp_path / "counts").key
        b = CountSidecar(list(reversed(shards)), "graph.natoms", root=tmp_path / "counts").key
        assert a != b

    def test_two_fields_do_not_share_a_vector(self, shards, tmp_path):
        a = CountSidecar(shards, "graph.natoms", root=tmp_path / "counts")
        b = CountSidecar(shards, "bonds", root=tmp_path / "counts")
        assert a.key != b.key

    def test_a_missing_source_still_keys_deterministically(self, tmp_path):
        # A source that is not there yet must not raise from the key; it just
        # keys somewhere that nothing has written.
        sc = CountSidecar([tmp_path / "absent.lmdb"], "graph.natoms", root=tmp_path / "counts")
        assert (
            sc.key
            == CountSidecar(
                [tmp_path / "absent.lmdb"], "graph.natoms", root=tmp_path / "counts"
            ).key
        )
        assert sc.load(n_rows=1) is None

    def test_refuses_a_vector_that_is_not_one_dimensional(self, shards, tmp_path):
        sc = CountSidecar(shards, "graph.natoms", root=tmp_path / "counts")
        with pytest.raises(ValueError):
            sc.save(np.zeros((2, 2), dtype=np.int64))

    def test_leaves_no_temporary_behind(self, shards, tmp_path):
        # The write goes through a rename so a reader never sees half a file.
        sc = CountSidecar(shards, "graph.natoms", root=tmp_path / "counts")
        sc.save(np.array([1, 2, 3], dtype=np.int64))
        assert not list((tmp_path / "counts").glob("*.tmp"))

    def test_an_unreadable_file_is_a_miss(self, shards, tmp_path):
        sc = CountSidecar(shards, "graph.natoms", root=tmp_path / "counts")
        sc.save(np.array([1, 2, 3], dtype=np.int64))
        sc.path.write_bytes(b"not an npy")
        assert sc.load(n_rows=3) is None
