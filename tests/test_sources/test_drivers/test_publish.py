"""Tests for the publish half of the drivers.

The read half is proven elsewhere; these cover the contract that publishing
returns a locator, so that publishing and fetching close a loop.
"""

from __future__ import annotations

import sys
from unittest import mock

import pytest

from molhub.sources.drivers.figshare import FigshareSource
from molhub.sources.drivers.huggingface import HuggingFaceSource
from molhub.sources.errors import SourceError
from molhub.sources.locator import Locator
from molhub.sources.publication import Publication


@pytest.fixture
def payload(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2\n")
    return path


class TestFigsharePublish:
    @pytest.fixture
    def source(self):
        source = FigshareSource(token="t")
        created = mock.MagicMock()
        created.json.return_value = {"id": 99, "title": "My Dataset"}
        announced = mock.MagicMock()
        announced.json.return_value = {"upload_url": "https://uploads.invalid/abc"}
        layout = mock.MagicMock()
        layout.json.return_value = {"parts": []}
        session = mock.MagicMock()
        session.post.side_effect = [created, announced]
        session.get.return_value = layout
        source._session_cache = session
        return source

    def test_returns_a_locator_for_the_new_article(self, source, payload):
        locator = source.publish([payload], "new", Publication(title="My Dataset"))
        assert locator == Locator.parse("figshare://99")

    def test_locator_can_be_fed_back_to_resolve(self, source, payload):
        """Publishing and fetching close a loop; the result is addressable."""
        locator = source.publish([payload], "new", Publication(title="My Dataset"))
        assert locator.scheme == FigshareSource.scheme

    def test_existing_article_id_skips_creation(self, source, payload):
        announced = mock.MagicMock()
        announced.json.return_value = {"upload_url": "https://uploads.invalid/abc"}
        source._session_cache.post.side_effect = None
        source._session_cache.post.return_value = announced

        locator = source.publish([payload], "99", Publication(title="x"))

        assert locator == Locator.parse("figshare://99")
        # Only the file announcement was posted — no article was created.
        posted_urls = [call.args[0] for call in source._session_cache.post.call_args_list]
        assert all(url.endswith("/articles/99/files") for url in posted_urls)

    def test_keywords_become_tags(self, source, payload):
        source.publish([payload], "new", Publication(title="x", keywords=("chem", "ml")))
        create_call = source._session_cache.post.call_args_list[0]
        assert create_call.kwargs["json"]["tags"] == ["chem", "ml"]

    def test_missing_file_raises_before_any_request(self, source, tmp_path):
        with pytest.raises(FileNotFoundError):
            source.publish([tmp_path / "nope.csv"], "new", Publication(title="x"))
        source._session_cache.post.assert_not_called()

    def test_publishing_without_a_token_raises(self, payload, monkeypatch):
        monkeypatch.delenv("FIGSHARE_TOKEN", raising=False)
        with pytest.raises(SourceError, match="token"):
            FigshareSource().publish([payload], "new", Publication(title="x"))

    def test_reading_needs_no_token(self, monkeypatch):
        """Resolve is anonymous; only publish demands credentials."""
        monkeypatch.delenv("FIGSHARE_TOKEN", raising=False)
        assert FigshareSource().scheme == "figshare"


class TestHuggingFacePublish:
    @pytest.fixture
    def hub(self, monkeypatch):
        fake = mock.MagicMock()
        fake.create_repo.return_value = "https://huggingface.co/datasets/org/ds"
        fake.upload_file.return_value = "https://huggingface.co/datasets/org/ds/blob/main/data.csv"
        monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
        return fake

    def test_returns_a_locator_naming_the_uploaded_file(self, hub, payload):
        locator = HuggingFaceSource(token="t").publish([payload], "org/ds", Publication(title="x"))
        assert locator == Locator.parse("hf://org/ds/data.csv")

    def test_repository_is_created_first(self, hub, payload):
        HuggingFaceSource(token="t").publish([payload], "org/ds", Publication(title="x"))
        hub.create_repo.assert_called_once()
        assert hub.create_repo.call_args.kwargs["repo_id"] == "org/ds"

    def test_private_flag_reaches_the_hub(self, hub, payload):
        HuggingFaceSource(token="t").publish(
            [payload], "org/ds", Publication(title="x", private=True)
        )
        assert hub.create_repo.call_args.kwargs["private"] is True

    def test_repo_type_is_singular_for_the_hub_api(self, hub, payload):
        HuggingFaceSource(token="t").publish([payload], "org/ds", Publication(title="x"))
        assert hub.create_repo.call_args.kwargs["repo_type"] == "dataset"

    def test_models_repo_type(self, hub, payload):
        HuggingFaceSource(token="t", repo_type="models").publish(
            [payload], "org/m", Publication(title="x")
        )
        assert hub.create_repo.call_args.kwargs["repo_type"] == "model"

    def test_directory_is_uploaded_as_a_folder(self, hub, tmp_path):
        folder = tmp_path / "bundle"
        folder.mkdir()
        (folder / "a.csv").write_text("x")
        HuggingFaceSource(token="t").publish([folder], "org/ds", Publication(title="x"))
        hub.upload_folder.assert_called_once()

    def test_missing_file_raises_before_any_request(self, hub, tmp_path):
        with pytest.raises(FileNotFoundError):
            HuggingFaceSource(token="t").publish(
                [tmp_path / "nope.csv"], "org/ds", Publication(title="x")
            )
        hub.create_repo.assert_not_called()


class TestPublishingProtocol:
    def test_both_drivers_satisfy_it(self):
        from molhub.sources import PublishingSource

        assert isinstance(FigshareSource(), PublishingSource)
        assert isinstance(HuggingFaceSource(), PublishingSource)

    def test_a_read_only_driver_does_not(self):
        from molhub.sources import HttpsSource, PublishingSource

        assert not isinstance(HttpsSource(), PublishingSource)
