"""Tests for the local file cache.

Files are keyed by what the manifest already identifies — a coordinate plus a
role — so nothing has to be hashed just to decide where a file goes. The layout
is asserted by exact string equality because the TypeScript client shares it.
"""

from __future__ import annotations

import pytest

from molhub.registry.blobs import BlobStore

KEY = "dataset:molcrafts/qm9@v2/main"


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

    def test_root_is_expanded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_HOME", "~/molhub-cache")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert BlobStore().root == tmp_path / "molhub-cache"


class TestBlobStoreLayout:
    @pytest.fixture
    def store(self, tmp_path):
        return BlobStore(root=tmp_path)

    def test_key_becomes_a_directory_path(self, store, tmp_path):
        relative = store.path_for(KEY).relative_to(tmp_path)
        assert str(relative) == "files/dataset_molcrafts/qm9@v2/main"

    def test_layout_is_exact_not_prefixed(self, store, tmp_path):
        """The TS client mirrors this string; only equality is acceptable."""
        assert store.path_for(KEY) == tmp_path / "files" / "dataset_molcrafts" / "qm9@v2" / "main"

    def test_different_roles_are_different_files(self, store):
        main = store.path_for("dataset:molcrafts/qm9@v2/main")
        exclude = store.path_for("dataset:molcrafts/qm9@v2/exclude")
        assert main != exclude

    def test_different_versions_are_different_files(self, store):
        assert store.path_for("dataset:x/y@1/main") != store.path_for("dataset:x/y@2/main")

    @pytest.mark.parametrize("evil", ["../../etc/passwd", "a/../../../b", "./x"])
    def test_traversal_cannot_escape_the_cache(self, store, evil):
        assert store.path_for(evil).is_relative_to(store.root)

    def test_empty_key_is_refused(self, store):
        with pytest.raises(ValueError, match="no usable segments"):
            store.path_for("../..")

    def test_temp_path_is_outside_the_files_tree(self, store, tmp_path):
        assert store.temp_path(KEY).parent == tmp_path / "tmp"

    def test_temp_path_shares_the_root_so_rename_is_atomic(self, store):
        assert store.temp_path(KEY).is_relative_to(store.root)


class TestBlobStorePresence:
    @pytest.fixture
    def store(self, tmp_path):
        return BlobStore(root=tmp_path)

    def test_absent_when_never_written(self, store):
        assert store.has(KEY) is False

    def test_present_after_put(self, store, tmp_path):
        source = tmp_path / "incoming.bin"
        source.write_bytes(b"payload")
        store.put(source, KEY)
        assert store.has(KEY) is True

    def test_zero_byte_file_is_not_a_hit(self, store):
        """A 0-byte file is what an interrupted transfer leaves behind."""
        target = store.path_for(KEY)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")
        assert store.has(KEY) is False


class TestBlobStorePut:
    @pytest.fixture
    def store(self, tmp_path):
        return BlobStore(root=tmp_path)

    def test_returns_the_canonical_path(self, store, tmp_path):
        source = tmp_path / "incoming.bin"
        source.write_bytes(b"payload")
        assert store.put(source, KEY) == store.path_for(KEY)

    def test_content_survives(self, store, tmp_path):
        source = tmp_path / "incoming.bin"
        source.write_bytes(b"payload")
        assert store.put(source, KEY).read_bytes() == b"payload"

    def test_source_is_moved_not_copied(self, store, tmp_path):
        source = tmp_path / "incoming.bin"
        source.write_bytes(b"payload")
        store.put(source, KEY)
        assert not source.exists()

    def test_putting_twice_replaces(self, store, tmp_path):
        for body in (b"first", b"second"):
            source = tmp_path / "incoming.bin"
            source.write_bytes(body)
            store.put(source, KEY)
        assert store.path_for(KEY).read_bytes() == b"second"
