"""Tests for the shared JSON-over-HTTP helper."""

from __future__ import annotations

import json
import urllib.request

import pytest

from molhub.sources.drivers._api import fetch_json
from molhub.sources.errors import BadStatus

from ..conftest import FakeResponse


class TestFetchJson:
    def test_decodes_the_payload(self, monkeypatch):
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *a, **k: FakeResponse(200, json.dumps({"a": 1}).encode()),
        )
        assert fetch_json("https://example.invalid/api") == {"a": 1}

    def test_decodes_a_top_level_list(self, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"[1, 2]"))
        assert fetch_json("https://example.invalid/api") == [1, 2]

    @pytest.mark.parametrize("status", [202, 404, 500])
    def test_non_200_raises(self, monkeypatch, status):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(status, b"{}"))
        with pytest.raises(BadStatus, match=str(status)):
            fetch_json("https://example.invalid/api")

    def test_non_json_body_raises(self, monkeypatch):
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"<html>nope</html>")
        )
        with pytest.raises(BadStatus, match="did not return JSON"):
            fetch_json("https://example.invalid/api")

    def test_sends_a_user_agent(self, monkeypatch):
        seen = {}

        def _urlopen(req, *a, **k):
            seen["ua"] = req.get_header("User-agent")
            return FakeResponse(200, b"{}")

        monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
        fetch_json("https://example.invalid/api")
        assert seen["ua"]
