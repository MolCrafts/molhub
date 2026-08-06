"""Tests for the HTTPS transfer driver — the five-step fetch contract."""

from __future__ import annotations

import urllib.request

import pytest

from molhub.registry.drivers.https import HttpsRegistry
from molhub.registry.errors import BadStatus
from molhub.registry.locator import Locator
from molhub.registry.remote import RemoteFile

from ..conftest import FakeResponse


class TestHttpsResolve:
    def test_locator_becomes_a_single_remote_file(self):
        remotes = HttpsRegistry().resolve(Locator.parse("https://example.org/a/data.csv"))
        assert len(remotes) == 1
        assert remotes[0].url == "https://example.org/a/data.csv"

    def test_filename_comes_from_the_url_tail(self):
        remote = HttpsRegistry().resolve(Locator.parse("https://example.org/a/data.csv"))[0]
        assert remote.filename == "data.csv"

    def test_query_string_is_stripped_from_the_filename(self):
        remote = HttpsRegistry().resolve(Locator.parse("https://example.org/d.csv?token=x"))[0]
        assert remote.filename == "d.csv"


class TestHttpsFetch:
    @pytest.fixture
    def remote(self):
        return RemoteFile(url="https://example.invalid/f.bin", filename="f.bin")

    def test_writes_the_body(self, tmp_path, monkeypatch, remote):
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"payload")
        )
        dest = tmp_path / "out.bin"
        assert HttpsRegistry().fetch(remote, dest).read_bytes() == b"payload"

    def test_creates_missing_parent_directories(self, tmp_path, monkeypatch, remote):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"x"))
        dest = tmp_path / "nested" / "deeper" / "out.bin"
        assert HttpsRegistry().fetch(remote, dest).exists()

    @pytest.mark.parametrize("status", [202, 204, 301, 404, 500])
    def test_non_200_raises_bad_status(self, tmp_path, monkeypatch, remote, status):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(status, b""))
        with pytest.raises(BadStatus, match=str(status)):
            HttpsRegistry().fetch(remote, tmp_path / "out.bin")

    def test_202_leaves_no_file(self, tmp_path, monkeypatch, remote):
        """Figshare answers 202 with an empty body while preparing a file."""
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(202, b""))
        dest = tmp_path / "out.bin"
        with pytest.raises(BadStatus):
            HttpsRegistry().fetch(remote, dest)
        assert not dest.exists()

    def test_interrupted_transfer_leaves_no_file(self, tmp_path, monkeypatch, remote):
        class Exploding(FakeResponse):
            def read(self, *a, **k):
                raise OSError("connection reset")

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Exploding(200, b"abc"))
        dest = tmp_path / "out.bin"
        with pytest.raises(OSError):
            HttpsRegistry().fetch(remote, dest)
        assert not dest.exists()
        assert list(tmp_path.glob("*.part")) == []

    def test_an_existing_file_is_untouched_when_the_transfer_fails(
        self, tmp_path, monkeypatch, remote
    ):
        dest = tmp_path / "out.bin"
        dest.write_bytes(b"previously cached")
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(202, b""))
        with pytest.raises(BadStatus):
            HttpsRegistry().fetch(remote, dest)
        assert dest.read_bytes() == b"previously cached"

    def test_sends_a_user_agent(self, tmp_path, monkeypatch, remote):
        seen = {}

        def _urlopen(req, *a, **k):
            seen["ua"] = req.get_header("User-agent")
            return FakeResponse(200, b"x")

        monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
        HttpsRegistry().fetch(remote, tmp_path / "out.bin")
        assert seen["ua"]


class TestHttpsScheme:
    def test_declares_https(self):
        assert HttpsRegistry().scheme == "https"
