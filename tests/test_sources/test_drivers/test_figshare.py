"""Tests for the Figshare driver."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from unittest import mock

import pytest

import molhub.sources.drivers.figshare as figshare_module
from molhub.sources.drivers.figshare import FigshareSource
from molhub.sources.errors import SourceError
from molhub.sources.locator import Locator
from molhub.sources.publication import Publication
from molhub.sources.remote import RemoteFile

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

_API_BASE = "https://api.figshare.invalid/v2"
_UPLOAD_URL = "https://uploads.figshare.invalid/token"
_PAYLOAD = b"a,b\n1,2\n"


def _response(payload: object) -> mock.Mock:
    response = mock.Mock()
    response.json.return_value = payload
    return response


class FakeTransfer:
    """Deterministic byte-transfer seam used by the driver unit."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.remotes: list[RemoteFile] = []

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        self.remotes.append(remote)
        dest.write_bytes(self.payload)
        return dest


@pytest.fixture
def api(monkeypatch):
    def _serve(payload):
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *a, **k: FakeResponse(200, json.dumps(payload).encode()),
        )

    return _serve


@pytest.fixture
def payload(tmp_path: Path) -> Path:
    path = tmp_path / "data.csv"
    path.write_bytes(_PAYLOAD)
    return path


@pytest.fixture
def publish_source() -> FigshareSource:
    transfer = FakeTransfer(_PAYLOAD)
    source = FigshareSource(api_base=_API_BASE, token="t", transfer=transfer)
    session = mock.MagicMock()
    session.post.return_value = _response({})
    session.get.return_value = _response({"version": 3})
    source._session_cache = session
    source.create_article = mock.Mock(return_value={"id": 99})
    source.upload_file = mock.Mock(return_value={"id": 501, "name": "data.csv"})
    return source


class TestFigshareSource:
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

    def test_publish_rejects_no_files_before_any_request(self, publish_source):
        with pytest.raises(SourceError, match="exactly one"):
            publish_source.publish([], "new", Publication(title="Dataset"))

        publish_source.create_article.assert_not_called()
        publish_source.upload_file.assert_not_called()
        publish_source._session_cache.post.assert_not_called()

    def test_publish_rejects_multiple_files_before_any_request(self, publish_source, payload):
        second = payload.with_name("second.csv")
        second.write_bytes(b"x\n")

        with pytest.raises(SourceError, match="exactly one"):
            publish_source.publish([payload, second], "new", Publication(title="Dataset"))

        publish_source.create_article.assert_not_called()
        publish_source.upload_file.assert_not_called()
        publish_source._session_cache.post.assert_not_called()

    def test_publish_rejects_a_directory_before_any_request(self, publish_source, tmp_path):
        directory = tmp_path / "bundle"
        directory.mkdir()

        with pytest.raises(SourceError, match="regular file"):
            publish_source.publish([directory], "new", Publication(title="Dataset"))

        publish_source.create_article.assert_not_called()
        publish_source.upload_file.assert_not_called()
        publish_source._session_cache.post.assert_not_called()

    def test_publish_rejects_a_missing_file_before_any_request(self, publish_source, tmp_path):
        with pytest.raises(FileNotFoundError):
            publish_source.publish([tmp_path / "missing.csv"], "new", Publication(title="Dataset"))

        publish_source.create_article.assert_not_called()
        publish_source.upload_file.assert_not_called()
        publish_source._session_cache.post.assert_not_called()

    def test_publish_rejects_private_publication_before_any_request(self, publish_source, payload):
        with pytest.raises(SourceError, match="public"):
            publish_source.publish([payload], "new", Publication(title="Dataset", private=True))

        publish_source.create_article.assert_not_called()
        publish_source.upload_file.assert_not_called()
        publish_source._session_cache.post.assert_not_called()

    def test_publish_without_a_token_raises(self, payload, monkeypatch):
        monkeypatch.delenv("FIGSHARE_TOKEN", raising=False)

        with pytest.raises(SourceError, match="token"):
            FigshareSource().publish([payload], "new", Publication(title="Dataset"))

    def test_resolve_needs_no_token(self, monkeypatch):
        monkeypatch.delenv("FIGSHARE_TOKEN", raising=False)

        assert FigshareSource().scheme == "figshare"

    def test_publish_existing_article_skips_creation(self, publish_source, payload):
        publish_source.publish([payload], "99", Publication(title="Dataset"))

        publish_source.create_article.assert_not_called()
        publish_source.upload_file.assert_called_once_with(payload, 99)

    def test_publish_passes_keywords_as_article_tags(self, publish_source, payload):
        publish_source.publish(
            [payload],
            "new",
            Publication(title="Dataset", keywords=("chem", "ml")),
        )

        assert publish_source.create_article.call_args.kwargs["tags"] == ["chem", "ml"]

    def test_create_article_reads_metadata_from_the_created_resource_location(self):
        source = FigshareSource(api_base=_API_BASE, token="t")
        session = mock.MagicMock()
        created = _response({})
        created.headers = {"Location": f"{_API_BASE}/account/articles/99"}
        article = _response({"id": 99, "title": "Dataset"})
        session.post.return_value = created
        session.get.return_value = article
        source._session_cache = session

        result = source.create_article("Dataset")

        assert result == {"id": 99, "title": "Dataset"}
        session.get.assert_called_once_with(f"{_API_BASE}/account/articles/99")
        article.raise_for_status.assert_called_once_with()

    @pytest.mark.parametrize(
        ("created_payload", "created_headers"),
        [
            ({}, {"Location": "/v2/account/articles/99"}),
            ({"location": "/v2/account/articles/99"}, {}),
        ],
        ids=["relative-header", "relative-json-body"],
    )
    def test_create_article_joins_relative_resource_locations_to_the_api_origin(
        self,
        created_payload,
        created_headers,
    ):
        source = FigshareSource(api_base=_API_BASE, token="t")
        session = mock.MagicMock()
        created = _response(created_payload)
        created.headers = created_headers
        article = _response({"id": 99, "title": "Dataset"})
        session.post.return_value = created
        session.get.return_value = article
        source._session_cache = session

        result = source.create_article("Dataset")

        assert result == {"id": 99, "title": "Dataset"}
        session.get.assert_called_once_with(f"{_API_BASE}/account/articles/99")

    def test_upload_file_completes_through_the_account_file_endpoint(self, payload):
        source = FigshareSource(api_base=_API_BASE, token="t")
        session = mock.MagicMock()
        file_endpoint = f"{_API_BASE}/account/articles/99/files/501"
        announcement = _response({})
        announcement.headers = {"Location": file_endpoint}
        announced_file = _response({"id": 501, "name": "data.csv", "upload_url": _UPLOAD_URL})
        completion = _response({})
        session.post.side_effect = [announcement, completion]
        session.get.side_effect = [announced_file, _response({"parts": []})]
        session.put.return_value = _response({})
        source._session_cache = session

        file_info = source.upload_file(payload, 99)

        assert file_info["id"] == 501
        assert session.post.call_args_list[-1] == mock.call(file_endpoint)
        completion.raise_for_status.assert_called_once_with()

    @pytest.mark.parametrize(
        ("announcement_payload", "announcement_headers"),
        [
            ({}, {"Location": "/v2/account/articles/99/files/501"}),
            ({"location": "/v2/account/articles/99/files/501"}, {}),
        ],
        ids=["relative-header", "relative-json-body"],
    )
    def test_upload_file_joins_relative_resource_locations_to_the_api_origin(
        self,
        payload,
        announcement_payload,
        announcement_headers,
    ):
        source = FigshareSource(api_base=_API_BASE, token="t")
        session = mock.MagicMock()
        announcement = _response(announcement_payload)
        announcement.headers = announcement_headers
        announced_file = _response({"id": 501, "name": "data.csv", "upload_url": _UPLOAD_URL})
        session.post.side_effect = [announcement, _response({})]
        session.get.side_effect = [announced_file, _response({"parts": []})]
        session.put.return_value = _response({})
        source._session_cache = session

        result = source.upload_file(payload, 99)

        assert result["id"] == 501
        assert session.get.call_args_list[0] == mock.call(
            f"{_API_BASE}/account/articles/99/files/501"
        )

    def test_upload_file_announces_the_exact_size_and_md5(self, payload):
        source = FigshareSource(api_base=_API_BASE, token="t")
        session = mock.MagicMock()
        announcement = _response({"id": 501, "name": "data.csv", "upload_url": _UPLOAD_URL})
        announcement.headers = {}
        session.post.side_effect = [announcement, _response({})]
        session.get.return_value = _response({"parts": []})
        session.put.return_value = _response({})
        source._session_cache = session

        source.upload_file(payload, 99)

        assert session.post.call_args_list[0] == mock.call(
            f"{_API_BASE}/account/articles/99/files",
            json={
                "name": "data.csv",
                "size": 8,
                "md5": "e5ebd4c02cefbe7955977c67ada242b7",
            },
        )

    def test_upload_file_seeks_to_each_part_start_offset(self, tmp_path):
        path = tmp_path / "parts.bin"
        path.write_bytes(b"0123456789abcdef")
        source = FigshareSource(api_base=_API_BASE, token="t")
        session = mock.MagicMock()
        announcement = _response({"id": 501, "name": "parts.bin", "upload_url": _UPLOAD_URL})
        announcement.headers = {}
        session.post.side_effect = [announcement, _response({})]
        session.get.return_value = _response(
            {
                "parts": [
                    {"partNo": 7, "startOffset": 8, "endOffset": 10},
                    {"partNo": 2, "startOffset": 1, "endOffset": 3},
                ]
            }
        )
        session.put.return_value = _response({})
        source._session_cache = session

        source.upload_file(path, 99)

        assert session.put.call_args_list == [
            mock.call(f"{_UPLOAD_URL}/7", data=b"89a"),
            mock.call(f"{_UPLOAD_URL}/2", data=b"123"),
        ]

    def test_upload_file_translates_completion_http_failure(self, payload):
        source = FigshareSource(api_base=_API_BASE, token="t")
        session = mock.MagicMock()
        announcement = _response({"id": 501, "name": "data.csv", "upload_url": _UPLOAD_URL})
        announcement.headers = {}
        completion = _response({})
        completion.raise_for_status.side_effect = RuntimeError("raw HTTP failure")
        session.post.side_effect = [announcement, completion]
        session.get.return_value = _response({"parts": []})
        session.put.return_value = _response({})
        source._session_cache = session

        with pytest.raises(SourceError, match="complet"):
            source.upload_file(payload, 99)

    def test_upload_file_rejects_missing_upstream_file_id(self, payload):
        source = FigshareSource(api_base=_API_BASE, token="t")
        session = mock.MagicMock()
        announcement = _response({})
        announcement.headers = {"Location": f"{_API_BASE}/account/articles/99/files/pending"}
        session.post.return_value = announcement
        session.get.return_value = _response({"name": "data.csv", "upload_url": _UPLOAD_URL})
        session.put.return_value = _response({})
        source._session_cache = session

        with pytest.raises(SourceError, match="file id"):
            source.upload_file(payload, 99)

    def test_publish_finalizes_the_article_publicly(self, publish_source, payload):
        response = publish_source._session_cache.post.return_value

        publish_source.publish([payload], "new", Publication(title="Dataset"))

        publish_source._session_cache.post.assert_called_once_with(
            f"{_API_BASE}/account/articles/99/publish"
        )
        response.raise_for_status.assert_called_once_with()

    def test_publish_translates_article_finalize_http_failure(self, publish_source, payload):
        response = publish_source._session_cache.post.return_value
        response.raise_for_status.side_effect = RuntimeError("raw HTTP failure")

        with pytest.raises(SourceError, match="publish|finaliz"):
            publish_source.publish([payload], "new", Publication(title="Dataset"))

    def test_publish_reads_the_authoritative_article_version(self, publish_source, payload):
        publish_source.publish([payload], "new", Publication(title="Dataset"))

        publish_source._session_cache.get.assert_called_once_with(
            f"{_API_BASE}/account/articles/99"
        )

    @pytest.mark.parametrize("version", [None, 0, -1, 1.5, "3"])
    def test_publish_rejects_a_non_positive_integer_version(self, publish_source, payload, version):
        publish_source._session_cache.get.return_value = _response({"version": version})

        with pytest.raises(SourceError, match="version"):
            publish_source.publish([payload], "new", Publication(title="Dataset"))

    def test_publish_returns_an_exact_pinned_file_locator(self, publish_source, payload):
        locator = publish_source.publish([payload], "new", Publication(title="Dataset"))

        assert locator == Locator.parse("figshare://99/v3/data.csv")

    def test_publish_result_resolves_and_fetches_with_the_same_source(
        self, publish_source, payload, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            figshare_module,
            "fetch_json",
            lambda _endpoint: {
                "files": [
                    {
                        "name": "data.csv",
                        "size": len(_PAYLOAD),
                        "download_url": "https://downloads.figshare.invalid/data.csv",
                    }
                ]
            },
        )

        locator = publish_source.publish([payload], "new", Publication(title="Dataset"))
        remote = publish_source.resolve(locator)[0]
        destination = tmp_path / "fetched.csv"

        assert locator == Locator.parse("figshare://99/v3/data.csv")
        assert publish_source.fetch(remote, destination) == destination
        assert destination.read_bytes() == _PAYLOAD
