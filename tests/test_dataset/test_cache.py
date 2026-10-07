"""Tests for the URL-addressed download cache."""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from molhub.dataset.cache import DownloadCache
from molhub.sources import BlobStore, FileTransfer, RemoteFile
from molhub.sources.errors import BadStatus


class _FakeTransfer:
    """Stand-in for :class:`HttpsSource` — canned bytes, counted calls.

    Mirrors the transfer contract the real driver honours: on a non-200 status
    it raises before anything is written, so nothing lands at *dest*.
    """

    def __init__(self, body: bytes = b"", status: int = 200) -> None:
        self._body = body
        self._status = status
        self.urls: list[str] = []

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        self.urls.append(remote.url)
        if self._status != 200:
            raise BadStatus(f"{remote.url} returned HTTP {self._status}, expected 200")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self._body)
        return dest


@pytest.fixture
def no_cache_env(monkeypatch):
    """Neither the current nor the deprecated root variable is set."""
    monkeypatch.delenv("MOLHUB_HOME", raising=False)
    monkeypatch.delenv("MOLHUB_CACHE_DIR", raising=False)


class TestDownloadCache:
    def test_the_fake_satisfies_the_seam_it_stands_in_for(self):
        """A fake that drifts from the declared seam proves nothing about it."""
        assert isinstance(_FakeTransfer(), FileTransfer)

    # -- root resolution -----------------------------------------------------

    def test_explicit_root_wins_over_every_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "home"))
        monkeypatch.setenv("MOLHUB_CACHE_DIR", str(tmp_path / "legacy"))
        assert DownloadCache(tmp_path / "explicit").root == tmp_path / "explicit"

    def test_molhub_home_wins_over_the_deprecated_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "home"))
        monkeypatch.setenv("MOLHUB_CACHE_DIR", str(tmp_path / "legacy"))
        assert DownloadCache().root == tmp_path / "home"

    def test_deprecated_var_is_used_only_when_molhub_home_is_unset(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MOLHUB_HOME", raising=False)
        monkeypatch.setenv("MOLHUB_CACHE_DIR", str(tmp_path / "legacy"))
        with pytest.warns(DeprecationWarning):
            assert DownloadCache().root == tmp_path / "legacy"

    def test_deprecated_var_warns_and_names_its_replacement(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MOLHUB_HOME", raising=False)
        monkeypatch.setenv("MOLHUB_CACHE_DIR", str(tmp_path / "legacy"))
        with pytest.warns(DeprecationWarning, match="MOLHUB_HOME"):
            DownloadCache()

    def test_molhub_home_does_not_warn(self, tmp_path, monkeypatch, recwarn):
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "home"))
        monkeypatch.setenv("MOLHUB_CACHE_DIR", str(tmp_path / "legacy"))
        DownloadCache()
        assert [w for w in recwarn if issubclass(w.category, DeprecationWarning)] == []

    def test_defaults_to_the_user_cache_directory(self, tmp_path, monkeypatch, no_cache_env):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        assert DownloadCache().root == tmp_path / ".cache" / "molhub"

    def test_root_is_the_blob_store_root(self, tmp_path, monkeypatch):
        """One root rule, owned by BlobStore — not a second copy of it."""
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "home"))
        assert DownloadCache().root == BlobStore().root

    def test_tilde_is_expanded_in_the_deprecated_var(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MOLHUB_HOME", raising=False)
        monkeypatch.setenv("MOLHUB_CACHE_DIR", "~/molhub")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        with pytest.warns(DeprecationWarning):
            assert DownloadCache().root == tmp_path / "molhub"

    # -- filename_for --------------------------------------------------------

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://example.com/a/b/data.csv", "data.csv"),
            ("https://example.com/data.csv?token=xyz", "data.csv"),
            ("https://example.com/dir/", "dir"),
        ],
    )
    def test_filename_extraction(self, url, expected):
        assert DownloadCache.filename_for(url) == expected

    @pytest.mark.parametrize("url", ["https://example.com/a/..", "https://example.com/a/."])
    def test_filename_never_escapes_the_cache(self, url):
        assert DownloadCache.filename_for(url) == "download"

    def test_filename_is_a_single_safe_segment(self, tmp_path):
        name = DownloadCache.filename_for("https://example.com/a/../b c:d.csv")
        assert name == "b_c_d.csv"
        assert (tmp_path / name).parent == tmp_path

    # -- path_for ------------------------------------------------------------

    def test_path_for_lands_in_the_url_subdirectory(self, tmp_path):
        cache = DownloadCache(tmp_path)
        assert cache.path_for("https://example.com/x.csv") == tmp_path / "urls" / "x.csv"

    def test_path_for_stays_out_of_the_shared_files_tree(self, tmp_path):
        path = DownloadCache(tmp_path).path_for("https://example.com/x.csv")
        assert "files" not in path.relative_to(tmp_path).parts

    def test_path_for_does_not_transfer(self, tmp_path, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("path_for must not download")

        monkeypatch.setattr(urllib.request, "urlopen", _boom)
        transfer = _FakeTransfer(b"x")
        DownloadCache(tmp_path, transfer=transfer).path_for("https://example.com/x.csv")
        assert transfer.urls == []

    # -- fetch ---------------------------------------------------------------

    def test_fetch_downloads_when_absent(self, tmp_path):
        cache = DownloadCache(tmp_path, transfer=_FakeTransfer(b"a,b\n"))
        assert cache.fetch("https://example.invalid/x.csv").read_bytes() == b"a,b\n"

    def test_fetch_writes_into_the_url_subdirectory(self, tmp_path):
        cache = DownloadCache(tmp_path, transfer=_FakeTransfer(b"a,b\n"))
        assert cache.fetch("https://example.invalid/x.csv").parent == tmp_path / "urls"

    def test_fetch_leaves_the_shared_files_tree_alone(self, tmp_path):
        cache = DownloadCache(tmp_path, transfer=_FakeTransfer(b"a,b\n"))
        cache.fetch("https://example.invalid/x.csv")
        assert not (tmp_path / "files").exists()

    def test_second_fetch_makes_no_request(self, tmp_path):
        transfer = _FakeTransfer(b"x")
        cache = DownloadCache(tmp_path, transfer=transfer)
        cache.fetch("https://example.invalid/x.csv")
        assert cache.fetch("https://example.invalid/x.csv").read_bytes() == b"x"
        assert len(transfer.urls) == 1

    def test_zero_byte_cache_entry_is_re_downloaded(self, tmp_path):
        """A 0-byte leftover must never be mistaken for a valid cache entry."""
        stale = tmp_path / "urls" / "x.csv"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(b"")
        cache = DownloadCache(tmp_path, transfer=_FakeTransfer(b"real"))
        assert cache.fetch("https://example.invalid/x.csv").read_bytes() == b"real"

    def test_bad_status_propagates_and_leaves_nothing(self, tmp_path):
        cache = DownloadCache(tmp_path, transfer=_FakeTransfer(status=202))
        with pytest.raises(BadStatus, match="202"):
            cache.fetch("https://example.invalid/x.csv")
        assert not (tmp_path / "urls" / "x.csv").exists()
