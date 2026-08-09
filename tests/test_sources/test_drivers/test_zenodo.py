"""Tests for the Zenodo driver — resolve only; transfer is HttpsSource's."""

from __future__ import annotations

import json
import urllib.request

import pytest

from molhub.sources.drivers.zenodo import ZenodoSource
from molhub.sources.errors import SourceError
from molhub.sources.locator import Locator

from ..conftest import FakeResponse

# Shaped after a real /api/records/<id> payload.
_RECORD = {
    "doi": "10.5281/zenodo.14980914",
    "conceptdoi": "10.5281/zenodo.14980913",
    "files": [
        {
            "key": "data.csv",
            "size": 6024335,
            "checksum": "md5:ce2c7b2a879450cbbfff4d7ccea648f9",
            "links": {"self": "https://zenodo.org/api/records/14980914/files/data.csv/content"},
        },
        {
            "key": "readme.txt",
            "size": 120,
            "checksum": "md5:0123456789abcdef0123456789abcdef",
            "links": {"self": "https://zenodo.org/api/records/14980914/files/readme.txt/content"},
        },
    ],
}


@pytest.fixture
def api(monkeypatch):
    def _serve(payload):
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *a, **k: FakeResponse(200, json.dumps(payload).encode()),
        )

    return _serve


class TestZenodoResolve:
    def test_bare_record_returns_every_file(self, api):
        api(_RECORD)
        remotes = ZenodoSource().resolve(Locator.parse("zenodo://14980914"))
        assert [r.filename for r in remotes] == ["data.csv", "readme.txt"]

    def test_named_file_narrows_to_one(self, api):
        api(_RECORD)
        remotes = ZenodoSource().resolve(Locator.parse("zenodo://14980914/data.csv"))
        assert [r.filename for r in remotes] == ["data.csv"]

    def test_direct_content_url_is_used(self, api):
        api(_RECORD)
        remote = ZenodoSource().resolve(Locator.parse("zenodo://14980914/data.csv"))[0]
        assert remote.url.endswith("/files/data.csv/content")

    def test_published_md5_is_carried_for_reconciliation(self, api):
        api(_RECORD)
        remote = ZenodoSource().resolve(Locator.parse("zenodo://14980914/data.csv"))[0]
        assert remote.upstream_digest == "md5:ce2c7b2a879450cbbfff4d7ccea648f9"

    def test_size_is_carried(self, api):
        api(_RECORD)
        assert (
            ZenodoSource().resolve(Locator.parse("zenodo://14980914/data.csv"))[0].size == 6024335
        )

    def test_unknown_filename_raises_and_lists_alternatives(self, api):
        api(_RECORD)
        with pytest.raises(SourceError, match="readme.txt"):
            ZenodoSource().resolve(Locator.parse("zenodo://14980914/nope.csv"))

    def test_record_without_files_raises(self, api):
        api({"files": []})
        with pytest.raises(SourceError, match="no files"):
            ZenodoSource().resolve(Locator.parse("zenodo://1"))

    def test_custom_api_base_is_honoured(self, monkeypatch):
        seen = {}

        def _urlopen(req, *a, **k):
            seen["url"] = req.full_url
            return FakeResponse(200, json.dumps(_RECORD).encode())

        monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
        ZenodoSource(api_base="https://sandbox.zenodo.org/api").resolve(
            Locator.parse("zenodo://14980914")
        )
        assert seen["url"].startswith("https://sandbox.zenodo.org/api/records/14980914")


class TestZenodoTransfer:
    def test_fetch_delegates_to_the_transfer_object(self, tmp_path, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"bytes"))
        from molhub.sources.remote import RemoteFile

        dest = tmp_path / "out.bin"
        ZenodoSource().fetch(RemoteFile(url="https://x/y", filename="y"), dest)
        assert dest.read_bytes() == b"bytes"

    def test_scheme(self):
        assert ZenodoSource().scheme == "zenodo"
