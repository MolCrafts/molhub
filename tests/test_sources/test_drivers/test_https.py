"""Tests for the HTTPS transfer driver — the five-step fetch contract."""

from __future__ import annotations

import io
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPResponse
from threading import Barrier
from unittest.mock import Mock

import pytest

from molhub.sources.drivers.https import HttpsSource
from molhub.sources.errors import BadStatus, SourceError
from molhub.sources.locator import Locator
from molhub.sources.remote import RemoteFile

from ..conftest import FakeResponse


class TestHttpsResolve:
    def test_locator_becomes_a_single_remote_file(self):
        remotes = HttpsSource().resolve(Locator.parse("https://example.org/a/data.csv"))
        assert len(remotes) == 1
        assert remotes[0].url == "https://example.org/a/data.csv"

    def test_filename_comes_from_the_url_tail(self):
        remote = HttpsSource().resolve(Locator.parse("https://example.org/a/data.csv"))[0]
        assert remote.filename == "data.csv"

    def test_query_string_is_stripped_from_the_filename(self):
        remote = HttpsSource().resolve(Locator.parse("https://example.org/d.csv?token=x"))[0]
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
        assert HttpsSource().fetch(remote, dest).read_bytes() == b"payload"

    @pytest.mark.parametrize("existing", [False, True])
    def test_truncated_body_is_not_published(self, tmp_path, monkeypatch, remote, existing):
        # Real stdlib HTTP parsing: a sized read can finish without raising
        # even though Content-Length has not been satisfied.
        wire = b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nabc"
        response = HTTPResponse(Mock(makefile=lambda *_: io.BytesIO(wire)))
        response.begin()
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: response)
        dest = tmp_path / "out.bin"
        if existing:
            dest.write_bytes(b"previous")
        with pytest.raises(SourceError, match="10.*3"):
            HttpsSource().fetch(remote, dest)
        if existing:
            assert dest.read_bytes() == b"previous"
        else:
            assert not dest.exists()
        assert list(tmp_path.glob("*.part")) == []

    @pytest.mark.parametrize(
        ("headers", "wire", "expected"),
        [
            (b"Content-Length: 3\r\n", b"abc", b"abc"),
            (b"", b"abc", b"abc"),
            (
                b"Transfer-Encoding: chunked\r\nContent-Length: 99\r\n",
                b"3\r\nabc\r\n0\r\n\r\n",
                b"abc",
            ),
        ],
    )
    def test_supported_response_framing(
        self, tmp_path, monkeypatch, remote, headers, wire, expected
    ):
        framed = b"HTTP/1.1 200 OK\r\n" + headers + b"\r\n" + wire
        response = HTTPResponse(Mock(makefile=lambda *_: io.BytesIO(framed)))
        response.begin()
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: response)
        dest = tmp_path / "out.bin"
        assert HttpsSource().fetch(remote, dest).read_bytes() == expected
        assert list(tmp_path.glob("*.part")) == []

    @pytest.mark.parametrize("length", ["invalid", "-1"])
    def test_invalid_content_length_is_rejected(self, tmp_path, monkeypatch, remote, length):
        response = FakeResponse(200, b"abc")
        response.headers["Content-Length"] = length
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: response)
        dest = tmp_path / "out.bin"
        with pytest.raises(SourceError, match="invalid Content-Length"):
            HttpsSource().fetch(remote, dest)
        assert not dest.exists()
        assert list(tmp_path.glob("*.part")) == []

    def test_incomplete_chunked_response_is_a_source_error(self, tmp_path, monkeypatch, remote):
        wire = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n3\r\na"
        response = HTTPResponse(Mock(makefile=lambda *_: io.BytesIO(wire)))
        response.begin()
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: response)
        dest = tmp_path / "out.bin"
        with pytest.raises(SourceError, match="incomplete response"):
            HttpsSource().fetch(remote, dest)
        assert not dest.exists()
        assert list(tmp_path.glob("*.part")) == []

    def test_concurrent_transfers_use_independent_scratch_files(
        self, tmp_path, monkeypatch, remote
    ):
        rendezvous = Barrier(2)

        class ConcurrentResponse(FakeResponse):
            def read(self, size=-1):
                data = super().read(size)
                if data:
                    rendezvous.wait(timeout=5)
                return data

        monkeypatch.setattr(
            urllib.request, "urlopen", lambda *a, **k: ConcurrentResponse(200, b"complete payload")
        )
        dest = tmp_path / "out.bin"
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(HttpsSource().fetch, remote, dest) for _ in range(2)]
            assert [future.result(timeout=10) for future in futures] == [dest, dest]
        assert dest.read_bytes() == b"complete payload"
        assert list(tmp_path.glob("*.part")) == []

    def test_creates_missing_parent_directories(self, tmp_path, monkeypatch, remote):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"x"))
        dest = tmp_path / "nested" / "deeper" / "out.bin"
        assert HttpsSource().fetch(remote, dest).exists()

    @pytest.mark.parametrize("status", [202, 204, 301, 404, 500])
    def test_non_200_raises_bad_status(self, tmp_path, monkeypatch, remote, status):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(status, b""))
        with pytest.raises(BadStatus, match=str(status)):
            HttpsSource().fetch(remote, tmp_path / "out.bin")

    def test_202_leaves_no_file(self, tmp_path, monkeypatch, remote):
        """Figshare answers 202 with an empty body while preparing a file."""
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(202, b""))
        dest = tmp_path / "out.bin"
        with pytest.raises(BadStatus):
            HttpsSource().fetch(remote, dest)
        assert not dest.exists()

    def test_interrupted_transfer_leaves_no_file(self, tmp_path, monkeypatch, remote):
        class Exploding(FakeResponse):
            def read(self, *a, **k):
                raise OSError("connection reset")

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Exploding(200, b"abc"))
        dest = tmp_path / "out.bin"
        with pytest.raises(OSError):
            HttpsSource().fetch(remote, dest)
        assert not dest.exists()
        assert list(tmp_path.glob("*.part")) == []

    def test_an_existing_file_is_untouched_when_the_transfer_fails(
        self, tmp_path, monkeypatch, remote
    ):
        dest = tmp_path / "out.bin"
        dest.write_bytes(b"previously cached")
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(202, b""))
        with pytest.raises(BadStatus):
            HttpsSource().fetch(remote, dest)
        assert dest.read_bytes() == b"previously cached"

    def test_sends_a_user_agent(self, tmp_path, monkeypatch, remote):
        seen = {}

        def _urlopen(req, *a, **k):
            seen["ua"] = req.get_header("User-agent")
            return FakeResponse(200, b"x")

        monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
        HttpsSource().fetch(remote, tmp_path / "out.bin")
        assert seen["ua"]


class TestHttpsScheme:
    def test_declares_https(self):
        assert HttpsSource().scheme == "https"
