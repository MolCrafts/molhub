"""Tests for dataset uploaders (HuggingFace Hub and Figshare)."""

from __future__ import annotations

import sys
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Helper — mock ``huggingface_hub`` so lazy imports succeed
# ---------------------------------------------------------------------------


def _inject_fake_huggingface_hub():
    """Replace ``huggingface_hub`` in sys.modules with a fresh mock."""
    fake = mock.MagicMock()
    fake.upload_file = mock.MagicMock(
        return_value="https://huggingface.co/datasets/test/ds/resolve/main/f.txt"
    )
    fake.upload_folder = mock.MagicMock(return_value="https://huggingface.co/datasets/test/ds")
    fake.create_repo = mock.MagicMock(return_value="https://huggingface.co/datasets/test/ds")
    sys.modules["huggingface_hub"] = fake
    return fake


# ---------------------------------------------------------------------------
# HuggingFaceUploader
# ---------------------------------------------------------------------------


class TestHuggingFaceUploader:
    def test_init_defaults(self):
        from molhub.uploader import HuggingFaceUploader

        u = HuggingFaceUploader(token="hf_test")
        assert u._token == "hf_test"

    def test_upload_file_calls_hf(self):
        fake_hf = _inject_fake_huggingface_hub()
        from molhub.uploader import HuggingFaceUploader

        u = HuggingFaceUploader(token="hf_test")
        url = u.upload_file(
            local_path="/tmp/test.txt",
            repo_id="test/ds",
            path_in_repo="f.txt",
        )

        fake_hf.upload_file.assert_called_once()
        assert url.startswith("https://")

    def test_upload_folder_calls_hf(self):
        fake_hf = _inject_fake_huggingface_hub()
        from molhub.uploader import HuggingFaceUploader

        u = HuggingFaceUploader(token="hf_test")
        url = u.upload_folder(
            local_dir="/tmp/dir",
            repo_id="test/ds",
            path_in_repo="data/",
        )

        fake_hf.upload_folder.assert_called_once()
        assert url.startswith("https://")

    def test_create_repo(self):
        fake_hf = _inject_fake_huggingface_hub()
        from molhub.uploader import HuggingFaceUploader

        u = HuggingFaceUploader(token="hf_test")
        u.create_repo("test/ds")

        fake_hf.create_repo.assert_called_once_with(
            repo_id="test/ds",
            repo_type="dataset",
            private=False,
            token="hf_test",
            exist_ok=True,
        )

    def test_upload_dataset_creates_repo_first(self):
        fake_hf = _inject_fake_huggingface_hub()
        from molhub.uploader import HuggingFaceUploader

        u = HuggingFaceUploader(token="hf_test")
        u.upload_dataset(
            local_path="/tmp/file.txt",
            repo_id="test/ds",
        )

        fake_hf.create_repo.assert_called_once()
        fake_hf.upload_file.assert_called_once()


# ---------------------------------------------------------------------------
# FigshareUploader
# ---------------------------------------------------------------------------


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
        test_file.write_text("hello figshare")

        u = FigshareUploader(token="test")

        init_resp = mock.MagicMock()
        init_resp.json.return_value = {
            "location": "https://api.figshare.com/v2/account/articles/1/files/1",
            "upload_url": "https://uploads.figshare.com/upload/abc",
        }
        init_resp.raise_for_status = mock.MagicMock()

        get_resp = mock.MagicMock()
        get_resp.json.return_value = {"parts": []}
        get_resp.raise_for_status = mock.MagicMock()

        put_resp = mock.MagicMock()
        put_resp.raise_for_status = mock.MagicMock()

        u._session.post = mock.MagicMock(return_value=init_resp)
        u._session.get = mock.MagicMock(return_value=get_resp)
        u._session.put = mock.MagicMock(return_value=put_resp)

        u.upload_file(test_file, article_id=1)
        u._session.put.assert_called_once()

    def test_upload_dataset_combined(self, tmp_path):
        from molhub.uploader import FigshareUploader

        test_file = tmp_path / "dataset.txt"
        test_file.write_text("molecular data")

        u = FigshareUploader(token="test")

        create_resp = mock.MagicMock()
        create_resp.json.return_value = {"id": 99, "title": "My Dataset"}
        create_resp.raise_for_status = mock.MagicMock()

        init_resp = mock.MagicMock()
        init_resp.json.return_value = {
            "location": "https://api.figshare.com/v2/upload/xyz",
            "upload_url": "https://uploads.figshare.com/upload/abc",
        }
        init_resp.raise_for_status = mock.MagicMock()

        get_resp = mock.MagicMock()
        get_resp.json.return_value = {"parts": []}
        get_resp.raise_for_status = mock.MagicMock()

        put_resp = mock.MagicMock()
        put_resp.raise_for_status = mock.MagicMock()

        u._session.post = mock.MagicMock(side_effect=[create_resp, init_resp])
        u._session.get = mock.MagicMock(return_value=get_resp)
        u._session.put = mock.MagicMock(return_value=put_resp)

        result = u.upload_dataset(
            test_file,
            title="My Dataset",
            description="A test dataset",
            tags=["chemistry"],
        )

        assert result["article"]["id"] == 99
        assert "file" in result
