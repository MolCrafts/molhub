"""Tests for the filename-addressed download cache."""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from molhub.dataset.cache import DownloadCache
from molhub.registry.errors import BadStatus

from ..test_registry.conftest import FakeResponse


class TestRoot:
    def test_explicit_root_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_CACHE_DIR", str(tmp_path / "env"))
        assert DownloadCache(tmp_path / "explicit").root == tmp_path / "explicit"

    def test_env_var_is_honoured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_CACHE_DIR", str(tmp_path / "env"))
        assert DownloadCache().root == tmp_path / "env"

    def test_defaults_to_user_cache(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MOLHUB_CACHE_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        assert DownloadCache().root == tmp_path / ".cache" / "molhub"

    def test_tilde_is_expanded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MOLHUB_CACHE_DIR", "~/molhub")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert DownloadCache().root == tmp_path / "molhub"


class TestFilenameFor:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://example.com/a/b/data.csv", "data.csv"),
            ("https://example.com/data.csv?token=xyz", "data.csv"),
            ("https://example.com/dir/", "dir"),
        ],
    )
    def test_extraction(self, url, expected):
        assert DownloadCache.filename_for(url) == expected


class TestPathFor:
    def test_joins_filename_onto_root(self, tmp_path):
        cache = DownloadCache(tmp_path)
        assert cache.path_for("https://example.com/x.csv") == tmp_path / "x.csv"

    def test_does_not_touch_the_network(self, tmp_path, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("path_for must not download")

        monkeypatch.setattr(urllib.request, "urlopen", _boom)
        DownloadCache(tmp_path).path_for("https://example.com/x.csv")


class TestFetch:
    def test_downloads_when_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"a,b\n"))
        path = DownloadCache(tmp_path).fetch("https://example.invalid/x.csv")
        assert path.read_bytes() == b"a,b\n"

    def test_second_call_makes_no_request(self, tmp_path, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"x"))
        cache = DownloadCache(tmp_path)
        cache.fetch("https://example.invalid/x.csv")

        def _boom(*a, **k):
            raise AssertionError("cached file must not be re-downloaded")

        monkeypatch.setattr(urllib.request, "urlopen", _boom)
        assert cache.fetch("https://example.invalid/x.csv").read_bytes() == b"x"

    def test_zero_byte_cache_entry_is_re_downloaded(self, tmp_path, monkeypatch):
        """A 0-byte leftover must never be mistaken for a valid cache entry."""
        stale = tmp_path / "x.csv"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(b"")
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"real"))
        assert (
            DownloadCache(tmp_path).fetch("https://example.invalid/x.csv").read_bytes() == b"real"
        )

    def test_bad_status_propagates_and_leaves_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(202, b""))
        with pytest.raises(BadStatus, match="202"):
            DownloadCache(tmp_path).fetch("https://example.invalid/x.csv")
        assert not (tmp_path / "x.csv").exists()


class TestTransferTo:
    def test_writes_to_an_explicit_destination(self, tmp_path, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"raw"))
        dest = tmp_path / "elsewhere" / "qm9.tar.bz2"
        DownloadCache(tmp_path).transfer_to("https://example.invalid/f", dest)
        assert dest.read_bytes() == b"raw"

    def test_ignores_the_url_derived_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"raw"))
        dest = tmp_path / "fixed-name.bin"
        assert (
            DownloadCache(tmp_path).transfer_to("https://example.invalid/other.bin", dest) == dest
        )

    def test_bad_status_leaves_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(202, b""))
        dest = tmp_path / "out.bin"
        with pytest.raises(BadStatus):
            DownloadCache(tmp_path).transfer_to("https://example.invalid/f", dest)
        assert not dest.exists()
        assert isinstance(dest, Path)
