"""Tests for FigshareUploader."""

from __future__ import annotations

from unittest import mock

import pytest


class TestFigshareUploader:
    def test_init_with_token(self):
        from molhub.uploader import FigshareUploader

        u = FigshareUploader(token="figshare_token_123")
        assert u._token == "figshare_token_123"

    def test_init_without_token_raises(self, monkeypatch):
        from molhub.uploader import FigshareUploader

        monkeypatch.delenv("FIGSHARE_TOKEN", raising=False)
        with pytest.raises(ValueError, match="Figshare token required"):
            FigshareUploader(token=None)

    def test_init_with_env_var(self, monkeypatch):
        from molhub.uploader import FigshareUploader

        monkeypatch.setenv("FIGSHARE_TOKEN", "env_token")
        u = FigshareUploader()
        assert u._token == "env_token"

    def test_create_article(self):
        from molhub.uploader import FigshareUploader

        u = FigshareUploader(token="test")
        mock_resp = mock.MagicMock()
        mock_resp.json.return_value = {"id": 12345, "title": "Test Dataset"}
        mock_resp.raise_for_status = mock.MagicMock()
        u._session.post = mock.MagicMock(return_value=mock_resp)

        result = u.create_article(
            title="Test Dataset",
            description="A test",
            tags=["chemistry", "ml"],
        )

        assert result["id"] == 12345
        assert result["title"] == "Test Dataset"
        u._session.post.assert_called_once()

    def test_upload_file_single_part(self, tmp_path):
        from molhub.uploader import FigshareUploader

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello figshare", encoding="utf-8")

        u = FigshareUploader(token="test")

        init_resp = mock.MagicMock()
        init_resp.json.return_value = {
            "id": 1,
            "name": "test.txt",
            "upload_url": "https://uploads.figshare.com/upload/abc",
        }
        init_resp.raise_for_status = mock.MagicMock()

        completion_resp = mock.MagicMock()
        completion_resp.raise_for_status = mock.MagicMock()

        get_resp = mock.MagicMock()
        get_resp.json.return_value = {"parts": []}
        get_resp.raise_for_status = mock.MagicMock()

        put_resp = mock.MagicMock()
        put_resp.raise_for_status = mock.MagicMock()

        u._session.post = mock.MagicMock(side_effect=[init_resp, completion_resp])
        u._session.get = mock.MagicMock(return_value=get_resp)
        u._session.put = mock.MagicMock(return_value=put_resp)

        result = u.upload_file(test_file, article_id=1)

        assert result == {
            "id": 1,
            "name": "test.txt",
            "upload_url": "https://uploads.figshare.com/upload/abc",
        }
        assert [call.args[0] for call in u._session.post.call_args_list] == [
            "https://api.figshare.com/v2/account/articles/1/files",
            "https://api.figshare.com/v2/account/articles/1/files/1",
        ]
        completion_resp.raise_for_status.assert_called_once_with()
        u._session.put.assert_called_once()

    def test_upload_dataset_combined(self, tmp_path):
        from molhub.uploader import FigshareUploader

        test_file = tmp_path / "dataset.txt"
        test_file.write_text("molecular data", encoding="utf-8")

        u = FigshareUploader(token="test")

        create_resp = mock.MagicMock()
        create_resp.json.return_value = {"id": 99, "title": "My Dataset"}
        create_resp.raise_for_status = mock.MagicMock()

        init_resp = mock.MagicMock()
        init_resp.json.return_value = {
            "id": 501,
            "name": "dataset.txt",
            "upload_url": "https://uploads.figshare.com/upload/abc",
        }
        init_resp.raise_for_status = mock.MagicMock()

        completion_resp = mock.MagicMock()
        completion_resp.raise_for_status = mock.MagicMock()

        get_resp = mock.MagicMock()
        get_resp.json.return_value = {"parts": []}
        get_resp.raise_for_status = mock.MagicMock()

        put_resp = mock.MagicMock()
        put_resp.raise_for_status = mock.MagicMock()

        u._session.post = mock.MagicMock(side_effect=[create_resp, init_resp, completion_resp])
        u._session.get = mock.MagicMock(return_value=get_resp)
        u._session.put = mock.MagicMock(return_value=put_resp)

        result = u.upload_dataset(
            test_file,
            title="My Dataset",
            description="A test dataset",
            tags=["chemistry"],
        )

        assert result["article"]["id"] == 99
        assert result["file"] == {
            "id": 501,
            "name": "dataset.txt",
            "upload_url": "https://uploads.figshare.com/upload/abc",
        }
        assert [call.args[0] for call in u._session.post.call_args_list] == [
            "https://api.figshare.com/v2/account/articles",
            "https://api.figshare.com/v2/account/articles/99/files",
            "https://api.figshare.com/v2/account/articles/99/files/501",
        ]
        completion_resp.raise_for_status.assert_called_once_with()
