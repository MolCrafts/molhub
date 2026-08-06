"""Tests for the content-addressed blob store.

The on-disk layout asserted here is a frozen contract (see CLAUDE.md): the
TypeScript client shares the same directory, so paths are compared for exact
equality, never by prefix.
"""

from __future__ import annotations

import hashlib

import pytest

from molhub.registry.blobs import BlobStore
from molhub.registry.digest import Digest

_HEX = hashlib.sha256(b"molecular bytes").hexdigest()


class TestBlobStoreRoot:
    def test_explicit_root_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "env"))
        assert BlobStore(root=tmp_path / "explicit").root == tmp_path / "explicit"

    def test_molhub_home_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "env"))
        assert BlobStore().root == tmp_path / "env"

    def test_defaults_to_user_cache(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MOLHUB_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        assert BlobStore().root == tmp_path / ".cache" / "molhub"

    def test_root_is_expanded_and_absolute(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_HOME", "~/molhub-cache")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert BlobStore().root == tmp_path / "molhub-cache"


class TestBlobStoreLayout:
    @pytest.fixture
    def store(self, tmp_path):
        return BlobStore(root=tmp_path)

    def test_path_is_sharded_by_first_two_hex_chars(self, store, tmp_path):
        digest = Digest.sha256(_HEX)
        assert store.path_for(digest) == tmp_path / "blobs" / "sha256" / _HEX[:2] / _HEX

    def test_layout_is_exact_not_prefixed(self, store, tmp_path):
        """The TS client mirrors this string; only equality is acceptable."""
        digest = Digest.sha256(_HEX)
        relative = store.path_for(digest).relative_to(tmp_path)
        assert str(relative) == f"blobs/sha256/{_HEX[:2]}/{_HEX}"

    def test_algorithm_appears_in_the_path(self, store, tmp_path):
        digest = Digest.parse(f"md5:{'a' * 32}")
        assert store.path_for(digest).parent.parent == tmp_path / "blobs" / "md5"

    def test_temp_path_is_outside_blobs(self, store, tmp_path):
        tmp = store.temp_path(Digest.sha256(_HEX))
        assert tmp.parent == tmp_path / "tmp"

    def test_temp_path_shares_root_so_rename_is_atomic(self, store):
        digest = Digest.sha256(_HEX)
        assert store.temp_path(digest).is_relative_to(store.root)


class TestBlobStorePresence:
    @pytest.fixture
    def store(self, tmp_path):
        return BlobStore(root=tmp_path)

    def test_absent_when_never_written(self, store):
        assert store.has(Digest.sha256(_HEX)) is False

    def test_present_after_put(self, store, tmp_path):
        digest = Digest.sha256(_HEX)
        source = tmp_path / "incoming.bin"
        source.write_bytes(b"molecular bytes")
        store.put(source, digest)
        assert store.has(digest) is True

    def test_zero_byte_blob_is_not_considered_present(self, store):
        """A 0-byte file is what an interrupted transfer used to leave behind."""
        digest = Digest.sha256(_HEX)
        target = store.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")
        assert store.has(digest) is False


class TestBlobStorePut:
    @pytest.fixture
    def store(self, tmp_path):
        return BlobStore(root=tmp_path)

    def test_returns_the_canonical_path(self, store, tmp_path):
        digest = Digest.sha256(_HEX)
        source = tmp_path / "incoming.bin"
        source.write_bytes(b"molecular bytes")
        assert store.put(source, digest) == store.path_for(digest)

    def test_content_survives(self, store, tmp_path):
        digest = Digest.sha256(_HEX)
        source = tmp_path / "incoming.bin"
        source.write_bytes(b"molecular bytes")
        assert store.put(source, digest).read_bytes() == b"molecular bytes"

    def test_source_is_moved_not_copied(self, store, tmp_path):
        digest = Digest.sha256(_HEX)
        source = tmp_path / "incoming.bin"
        source.write_bytes(b"molecular bytes")
        store.put(source, digest)
        assert not source.exists()

    def test_put_over_an_existing_blob_is_idempotent(self, store, tmp_path):
        digest = Digest.sha256(_HEX)
        for _ in range(2):
            source = tmp_path / "incoming.bin"
            source.write_bytes(b"molecular bytes")
            assert store.put(source, digest).read_bytes() == b"molecular bytes"
