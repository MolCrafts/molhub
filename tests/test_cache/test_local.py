"""A mutable cache is refused on a shared filesystem."""

from __future__ import annotations

import errno
import os
import pickle
from pathlib import Path

import pytest

from molhub.cache.lmdb import LmdbCache
from molhub.cache.local import cache_write_failed, require_node_local, runtime_cache_root


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "shard.h5"
    path.write_bytes(b"v1")
    return path


def _kind(local: Path):
    def fstype(path: Path) -> str:
        if str(path).startswith(str(local)) or str(path).startswith("/tmp"):
            return "xfs"
        return "lustre"

    return fstype


class TestCacheWriteFailed:
    def test_a_full_or_unwritable_scratch_stops_the_cache(self):
        assert cache_write_failed(OSError(errno.ENOSPC, "No space left on device"))
        assert cache_write_failed(OSError(errno.EIO, "Input/output error"))
        assert cache_write_failed(OSError(errno.EDQUOT, "Disk quota exceeded"))
        assert cache_write_failed(RuntimeError("mdb_txn_commit: Input/output error"))
        assert cache_write_failed(RuntimeError("MDB_MAP_FULL: Environment mapsize limit reached"))

    def test_any_other_error_still_fails_the_read(self):
        assert not cache_write_failed(OSError(errno.EACCES, "Permission denied"))
        assert not cache_write_failed(RuntimeError("boom"))


class TestRuntimeCache:
    def test_a_lustre_path_is_refused(self, monkeypatch):
        monkeypatch.setattr("molhub.cache.local.fstype", lambda path: "lustre")
        with pytest.raises(RuntimeError, match="lustre"):
            require_node_local(Path("/nobackup/proj/disk/rows"))

    def test_a_local_directory_stays(self, tmp_path, monkeypatch):
        monkeypatch.setattr("molhub.cache.local.fstype", lambda path: "xfs")
        asked = tmp_path / "rows"
        assert require_node_local(asked) == asked

    def test_a_shared_override_is_refused(self, monkeypatch):
        monkeypatch.setenv("MOLHUB_RUNTIME_CACHE", "/nobackup/cache")
        monkeypatch.setattr("molhub.cache.local.fstype", lambda path: "lustre")
        with pytest.raises(RuntimeError, match="MOLHUB_RUNTIME_CACHE"):
            runtime_cache_root()

    def test_node_scratch_is_per_job(self, tmp_path, monkeypatch):
        scratch = tmp_path / "scratch-local"
        scratch.mkdir()
        monkeypatch.setattr("molhub.cache.local._NODE_SCRATCH", scratch)
        monkeypatch.delenv("MOLHUB_RUNTIME_CACHE", raising=False)
        monkeypatch.setenv("SLURM_JOB_ID", "99")
        monkeypatch.setattr("molhub.cache.local.fstype", _kind(tmp_path))
        assert runtime_cache_root() == scratch / "molcache" / "99"

    def test_without_node_scratch_the_root_is_under_tmp(self, monkeypatch):
        monkeypatch.setattr("molhub.cache.local._NODE_SCRATCH", Path("/no/such/scratch"))
        monkeypatch.delenv("MOLHUB_RUNTIME_CACHE", raising=False)
        monkeypatch.delenv("SLURM_TMPDIR", raising=False)
        monkeypatch.delenv("SLURM_JOB_ID", raising=False)
        monkeypatch.setattr("molhub.cache.local.fstype", _kind(Path("/nowhere")))
        assert runtime_cache_root() == Path("/tmp/molcache") / f"user-{os.getuid()}"

    def test_lmdb_on_lustre_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr("molhub.cache.local.fstype", lambda path: "lustre")
        with pytest.raises(RuntimeError, match="lustre"):
            LmdbCache([_source(tmp_path)], "rows", root=Path("/nobackup/rows"))

    def test_default_root_is_the_runtime_cache(self, tmp_path, monkeypatch):
        runtime = tmp_path / "runtime"
        monkeypatch.setenv("MOLHUB_RUNTIME_CACHE", str(runtime))
        monkeypatch.setattr("molhub.cache.local.fstype", _kind(tmp_path))
        cache = LmdbCache([_source(tmp_path)], "rows")
        cache.put(b"\x00" * 8, b"ok")
        assert cache.root == runtime
        assert cache.get(b"\x00" * 8) == b"ok"
        assert cache._store is not None
        assert cache._store.lock is True

    def test_pickle_drops_the_open_environment(self, tmp_path, monkeypatch):
        monkeypatch.setattr("molhub.cache.local.fstype", lambda path: "xfs")
        cache = LmdbCache([_source(tmp_path)], "rows", root=tmp_path / "rows")
        cache.put(b"\x00" * 8, b"ok")
        restored = pickle.loads(pickle.dumps(cache))
        assert restored._store is None
        assert restored.get(b"\x00" * 8) == b"ok"
        assert restored._store is not cache._store
