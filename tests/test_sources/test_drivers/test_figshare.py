"""Tests for the Figshare driver — resolve only."""

from __future__ import annotations

import json
import urllib.request

import pytest

from molhub.sources.drivers.figshare import FigshareSource
from molhub.sources.errors import SourceError
from molhub.sources.locator import Locator

from ..conftest import FakeResponse

# Shaped after a real /v2/articles/<id>/files payload.
_FILES = [
    {
        "name": "qm9.tar.bz2",
        "size": 82000000,
        "supplied_md5": "ad4b6b1e4c3a5f6d7e8f9a0b1c2d3e4f",
        "download_url": "https://ndownloader.figshare.com/files/3195389",
    },
    {
        "name": "uncharacterized.txt",
        "size": 51200,
        "supplied_md5": None,
        "computed_md5": "00112233445566778899aabbccddeeff",
        "download_url": "https://ndownloader.figshare.com/files/3195404",
    },
]


@pytest.fixture
def api(monkeypatch):
    def _serve(payload):
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *a, **k: FakeResponse(200, json.dumps(payload).encode()),
        )

    return _serve


class TestFigshareResolve:
    def test_bare_article_returns_every_file(self, api):
        api(_FILES)
        remotes = FigshareSource().resolve(Locator.parse("figshare://978904"))
        assert [r.filename for r in remotes] == ["qm9.tar.bz2", "uncharacterized.txt"]

    def test_named_file_narrows_to_one(self, api):
        api(_FILES)
        remotes = FigshareSource().resolve(Locator.parse("figshare://978904/qm9.tar.bz2"))
        assert len(remotes) == 1
        assert remotes[0].url.endswith("/3195389")

    def test_supplied_md5_is_preferred(self, api):
        api(_FILES)
        remote = FigshareSource().resolve(Locator.parse("figshare://978904/qm9.tar.bz2"))[0]
        assert remote.upstream_digest == "md5:ad4b6b1e4c3a5f6d7e8f9a0b1c2d3e4f"

    def test_computed_md5_is_the_fallback(self, api):
        api(_FILES)
        remote = FigshareSource().resolve(Locator.parse("figshare://978904/uncharacterized.txt"))[0]
        assert remote.upstream_digest == "md5:00112233445566778899aabbccddeeff"

    def test_unknown_filename_raises_and_lists_alternatives(self, api):
        api(_FILES)
        with pytest.raises(SourceError, match="qm9.tar.bz2"):
            FigshareSource().resolve(Locator.parse("figshare://978904/nope"))

    def test_article_without_files_raises(self, api):
        api([])
        with pytest.raises(SourceError, match="no files"):
            FigshareSource().resolve(Locator.parse("figshare://1"))

    def test_scheme(self):
        assert FigshareSource().scheme == "figshare"
