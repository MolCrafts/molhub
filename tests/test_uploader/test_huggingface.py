"""Tests for HuggingFaceUploader."""

from __future__ import annotations

import sys
from unittest import mock


def _inject_fake_huggingface_hub():
    """Replace ``huggingface_hub`` in sys.modules with a fresh mock.

    ``HuggingFaceUploader`` imports the library lazily inside each method, so
    swapping the module entry is enough to intercept every call.
    """
    fake = mock.MagicMock()
    fake.upload_file = mock.MagicMock(
        return_value="https://huggingface.co/datasets/test/ds/resolve/main/f.txt"
    )
    fake.upload_folder = mock.MagicMock(return_value="https://huggingface.co/datasets/test/ds")
    fake.create_repo = mock.MagicMock(return_value="https://huggingface.co/datasets/test/ds")
    sys.modules["huggingface_hub"] = fake
    return fake


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
