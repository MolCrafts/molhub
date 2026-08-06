"""Tests for the self-hosted MolCrafts registry.

The point of these is that this driver is ordinary: same protocol, same
transfer, no privileges. See also test_layering.py, which asserts no other
module branches on its scheme.
"""

from __future__ import annotations

import urllib.request

import pytest

from molhub.registry.drivers.molhub import MolHubRegistry
from molhub.registry.errors import BadStatus
from molhub.registry.locator import Locator
from molhub.registry.remote import RemoteFile

from ..conftest import FakeResponse


class TestMolHubResolve:
    def test_path_is_joined_onto_the_base(self):
        registry = MolHubRegistry(base_url="https://hub.example.org")
        remote = registry.resolve(Locator.parse("molhub://plugins/molvis-render/0.3.1.zip"))[0]
        assert remote.url == "https://hub.example.org/plugins/molvis-render/0.3.1.zip"

    def test_filename_is_the_last_segment(self):
        registry = MolHubRegistry(base_url="https://hub.example.org")
        remote = registry.resolve(Locator.parse("molhub://plugins/molvis-render/0.3.1.zip"))[0]
        assert remote.filename == "0.3.1.zip"

    def test_trailing_slash_on_base_is_normalised(self):
        registry = MolHubRegistry(base_url="https://hub.example.org/")
        remote = registry.resolve(Locator.parse("molhub://a/b.zip"))[0]
        assert remote.url == "https://hub.example.org/a/b.zip"

    def test_env_var_sets_the_base(self, monkeypatch):
        monkeypatch.setenv("MOLHUB_REGISTRY_BASE", "https://staging.example.org")
        remote = MolHubRegistry().resolve(Locator.parse("molhub://a.zip"))[0]
        assert remote.url == "https://staging.example.org/a.zip"

    def test_explicit_base_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("MOLHUB_REGISTRY_BASE", "https://staging.example.org")
        registry = MolHubRegistry(base_url="https://explicit.example.org")
        assert registry.resolve(Locator.parse("molhub://a.zip"))[0].url.startswith(
            "https://explicit.example.org"
        )


class TestMolHubTransfer:
    def test_uses_the_same_transfer_contract(self, tmp_path, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(200, b"zip"))
        dest = tmp_path / "out.zip"
        MolHubRegistry().fetch(RemoteFile(url="https://x/y.zip", filename="y.zip"), dest)
        assert dest.read_bytes() == b"zip"

    def test_non_200_is_rejected_exactly_as_elsewhere(self, tmp_path, monkeypatch):
        """No leniency for our own host."""
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse(202, b""))
        dest = tmp_path / "out.zip"
        with pytest.raises(BadStatus):
            MolHubRegistry().fetch(RemoteFile(url="https://x/y.zip", filename="y.zip"), dest)
        assert not dest.exists()

    def test_scheme(self):
        assert MolHubRegistry().scheme == "molhub"
