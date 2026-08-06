"""Tests for the HuggingFace driver — URL construction, including mirrors."""

from __future__ import annotations

import pytest

from molhub.registry.drivers.huggingface import HuggingFaceRegistry
from molhub.registry.errors import InvalidLocator
from molhub.registry.locator import Locator


class TestHuggingFaceResolve:
    def test_default_revision_is_main(self):
        remote = HuggingFaceRegistry().resolve(Locator.parse("hf://MolCrafts/qm9/qm9.tar.bz2"))[0]
        assert remote.url == (
            "https://huggingface.co/datasets/MolCrafts/qm9/resolve/main/qm9.tar.bz2"
        )

    def test_pinned_revision(self):
        remote = HuggingFaceRegistry().resolve(
            Locator.parse("hf://MolCrafts/qm9@abc1234/qm9.tar.bz2")
        )[0]
        assert "/resolve/abc1234/" in remote.url

    def test_nested_file_path_is_preserved(self):
        remote = HuggingFaceRegistry().resolve(Locator.parse("hf://org/repo/raw/inner/f.bin"))[0]
        assert remote.url.endswith("/resolve/main/raw/inner/f.bin")

    def test_filename_is_the_last_segment(self):
        remote = HuggingFaceRegistry().resolve(Locator.parse("hf://org/repo/raw/inner/f.bin"))[0]
        assert remote.filename == "f.bin"

    def test_mirror_endpoint_needs_no_manifest_change(self):
        """Pointing at hf-mirror.com is a client-side setting, not a new locator."""
        registry = HuggingFaceRegistry(endpoint="https://hf-mirror.com")
        remote = registry.resolve(Locator.parse("hf://MolCrafts/qm9/qm9.tar.bz2"))[0]
        assert remote.url.startswith("https://hf-mirror.com/datasets/")

    def test_models_repo_type_drops_the_prefix(self):
        registry = HuggingFaceRegistry(repo_type="models")
        remote = registry.resolve(Locator.parse("hf://org/mace-mp-0/weights.pt"))[0]
        assert remote.url == "https://huggingface.co/org/mace-mp-0/resolve/main/weights.pt"

    @pytest.mark.parametrize("path", ["org", "org/repo"])
    def test_too_short_path_raises(self, path):
        with pytest.raises(InvalidLocator):
            HuggingFaceRegistry().resolve(Locator.parse(f"hf://{path}"))

    def test_unknown_repo_type_raises(self):
        with pytest.raises(ValueError, match="repo_type"):
            HuggingFaceRegistry(repo_type="notebooks")

    def test_scheme(self):
        assert HuggingFaceRegistry().scheme == "hf"
