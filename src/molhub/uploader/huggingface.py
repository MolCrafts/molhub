"""Compatibility shim for the pre-source HuggingFace uploader.

The implementation now lives in
:class:`molhub.sources.drivers.huggingface.HuggingFaceSource`, where
uploading is the write half of the same driver that resolves and fetches. This
class stays so existing callers keep working; prefer the driver directly::

    from molhub.sources import Drivers, Publication

    hub = Drivers.discover().for_scheme("hf")
    locator = hub.publish([Path("data.csv")], "my-org/my-dataset",
                          Publication(title="…"))

Scheduled for removal two minor releases after 0.1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from molhub.sources.drivers.huggingface import HuggingFaceSource

__all__ = ["HuggingFaceUploader"]

# The shim's public API is spelled in huggingface_hub's singular repo types;
# the driver is constructed with molhub's plural form.
_DRIVER_REPO_TYPE = {"dataset": "datasets", "model": "models", "space": "spaces"}


class HuggingFaceUploader:
    """Upload files and folders to a HuggingFace Hub repository.

    Args:
        token: HuggingFace API token (or set ``HF_TOKEN``).
        endpoint: Optional custom endpoint URL.
    """

    def __init__(self, token: str | None = None, endpoint: str | None = None) -> None:
        self._token = token
        self._endpoint = endpoint

    def _source(self, repo_type: str) -> HuggingFaceSource:
        """Build a driver for *repo_type* (``"dataset"``, ``"model"``, ``"space"``)."""
        kwargs: dict[str, Any] = {
            "repo_type": _DRIVER_REPO_TYPE[repo_type],
            "token": self._token,
        }
        if self._endpoint:
            kwargs["endpoint"] = self._endpoint
        return HuggingFaceSource(**kwargs)

    def upload_file(
        self,
        local_path: str | Path,
        repo_id: str,
        path_in_repo: str,
        *,
        repo_type: str = "dataset",
        commit_message: str | None = None,
        **kwargs: Any,
    ) -> object:
        """Upload a single file to a HuggingFace Hub repository.

        Args:
            local_path: Existing local file to upload.
            repo_id: Destination repository id, ``"org/name"``.
            path_in_repo: Destination path inside the repository.
            repo_type: Hub repository type.
            commit_message: Optional commit message.
            **kwargs: Additional arguments forwarded to the Hub client.

        Returns:
            The exact object returned by ``huggingface_hub.upload_file``.
        """
        return self._source(repo_type).upload_file(
            local_path, repo_id, path_in_repo, commit_message=commit_message, **kwargs
        )

    def upload_folder(
        self,
        local_dir: str | Path,
        repo_id: str,
        path_in_repo: str = "",
        *,
        repo_type: str = "dataset",
        commit_message: str | None = None,
        **kwargs: Any,
    ) -> object:
        """Upload an entire folder to a HuggingFace Hub repository.

        Args:
            local_dir: Existing local directory to upload.
            repo_id: Destination repository id, ``"org/name"``.
            path_in_repo: Destination path inside the repository.
            repo_type: Hub repository type.
            commit_message: Optional commit message.
            **kwargs: Additional arguments forwarded to the Hub client.

        Returns:
            The exact object returned by ``huggingface_hub.upload_folder``.
        """
        return self._source(repo_type).upload_folder(
            local_dir, repo_id, path_in_repo, commit_message=commit_message, **kwargs
        )

    def create_repo(
        self,
        repo_id: str,
        *,
        repo_type: str = "dataset",
        private: bool = False,
        exist_ok: bool = True,
    ) -> str:
        """Create a new repository on HuggingFace Hub."""
        return self._source(repo_type).create_repo(repo_id, private=private, exist_ok=exist_ok)

    def upload_dataset(
        self,
        local_path: str | Path,
        repo_id: str,
        *,
        path_in_repo: str = "",
        private: bool = False,
        commit_message: str | None = None,
    ) -> object:
        """Upload a dataset, creating its HuggingFace Hub repository if needed.

        Args:
            local_path: Existing local file or directory to upload.
            repo_id: Destination repository id, ``"org/name"``.
            path_in_repo: Destination path inside the repository.
            private: Whether to create a private repository.
            commit_message: Optional commit message.

        Returns:
            The exact Hub object returned by the selected file or folder
            upload operation.
        """
        local = Path(local_path)
        self.create_repo(repo_id, private=private)

        if local.is_dir():
            return self.upload_folder(
                local, repo_id, path_in_repo=path_in_repo, commit_message=commit_message
            )
        destination = f"{path_in_repo}/{local.name}" if path_in_repo else local.name
        return self.upload_file(
            local, repo_id, path_in_repo=destination.lstrip("/"), commit_message=commit_message
        )
