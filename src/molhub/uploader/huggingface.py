"""Upload files and datasets to HuggingFace Hub.

Uses the ``huggingface_hub`` library.  Install with
``pip install molhub[huggingface]`` or ``pip install huggingface_hub``.

Usage::

    from molhub.uploader import HuggingFaceUploader

    uploader = HuggingFaceUploader(token="hf_...")
    uploader.upload_file(
        local_path="data/qm9.tar.bz2",
        repo_id="my-org/my-dataset",
        path_in_repo="raw/qm9.tar.bz2",
    )
    uploader.upload_folder(
        local_dir="data/processed/",
        repo_id="my-org/my-dataset",
        path_in_repo="processed/",
    )
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class HuggingFaceUploader:
    """Upload files and folders to a HuggingFace Hub repository.

    Args:
        token: HuggingFace API token (or set ``HF_TOKEN`` env var).
        endpoint: Optional custom endpoint URL.
    """

    def __init__(
        self,
        token: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        self._token = token
        self._endpoint = endpoint

    # -- public API ----------------------------------------------------------

    def upload_file(
        self,
        local_path: str | Path,
        repo_id: str,
        path_in_repo: str,
        *,
        repo_type: str = "dataset",
        commit_message: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Upload a single file to a HF Hub repository.

        Args:
            local_path: Path to the local file.
            repo_id: HuggingFace repository id (e.g. ``"username/dataset-name"``).
            path_in_repo: Destination path inside the repository.
            repo_type: One of ``"dataset"``, ``"model"``, ``"space"``.
            commit_message: Optional commit message.
            **kwargs: Forwarded to :func:`huggingface_hub.upload_file`.

        Returns:
            The URL of the uploaded file.
        """
        from huggingface_hub import upload_file as _hf_upload_file

        msg = commit_message or f"Upload {Path(local_path).name}"
        return _hf_upload_file(
            path_or_fileobj=str(local_path),
            path_in_repo=path_in_repo,
            repo_id=repo_id,
            repo_type=repo_type,
            token=self._token,
            commit_message=msg,
            **kwargs,
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
    ) -> str:
        """Upload an entire folder to a HF Hub repository.

        Args:
            local_dir: Path to the local folder.
            repo_id: HuggingFace repository id.
            path_in_repo: Destination path prefix inside the repository.
            repo_type: One of ``"dataset"``, ``"model"``, ``"space"``.
            commit_message: Optional commit message.
            **kwargs: Forwarded to :func:`huggingface_hub.upload_folder`.

        Returns:
            The URL of the uploaded folder.
        """
        from huggingface_hub import upload_folder as _hf_upload_folder

        msg = commit_message or f"Upload folder {Path(local_dir).name}"
        return _hf_upload_folder(
            folder_path=str(local_dir),
            path_in_repo=path_in_repo,
            repo_id=repo_id,
            repo_type=repo_type,
            token=self._token,
            commit_message=msg,
            **kwargs,
        )

    def create_repo(
        self,
        repo_id: str,
        *,
        repo_type: str = "dataset",
        private: bool = False,
        exist_ok: bool = True,
    ) -> str:
        """Create a new repository on HuggingFace Hub.

        Args:
            repo_id: Repository id (e.g. ``"username/dataset-name"``).
            repo_type: One of ``"dataset"``, ``"model"``, ``"space"``.
            private: Whether the repository should be private.
            exist_ok: If True, do not raise when the repo already exists.

        Returns:
            The URL of the created repository.
        """
        from huggingface_hub import create_repo as _hf_create_repo

        return _hf_create_repo(
            repo_id=repo_id,
            repo_type=repo_type,
            private=private,
            token=self._token,
            exist_ok=exist_ok,
        )

    def upload_dataset(
        self,
        local_path: str | Path,
        repo_id: str,
        *,
        path_in_repo: str = "",
        private: bool = False,
        commit_message: str | None = None,
    ) -> str:
        """Upload a dataset (file or folder) to HF Hub, creating the repo if needed.

        This is a convenience combining :meth:`create_repo` and
        :meth:`upload_file` / :meth:`upload_folder`.

        Args:
            local_path: Path to local file or folder.
            repo_id: HuggingFace repository id.
            path_in_repo: Destination path prefix inside the repository.
            private: Whether to create a private repository.
            commit_message: Optional commit message.

        Returns:
            The repository URL.
        """
        local = Path(local_path)
        self.create_repo(repo_id, private=private)

        if local.is_dir():
            return self.upload_folder(
                local,
                repo_id,
                path_in_repo=path_in_repo,
                commit_message=commit_message,
            )
        else:
            dest = f"{path_in_repo}/{local.name}" if path_in_repo else local.name
            dest = dest.lstrip("/")
            return self.upload_file(
                local,
                repo_id,
                path_in_repo=dest,
                commit_message=commit_message,
            )
