"""HuggingFace Hub driver.

Content inside a repository is addressable by commit SHA and LFS sha256, but
the ``org/name`` namespace is mutable: repositories get renamed, deleted, or
gated. That is why a HuggingFace locator is one entry in an artifact's ordered
list rather than its only source.

Locator forms::

    hf://MolCrafts/qm9/qm9.tar.bz2            datasets repo, revision "main"
    hf://MolCrafts/qm9@abc1234/qm9.tar.bz2    pinned revision
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from molhub.sources.drivers.https import HttpsSource
from molhub.sources.errors import InvalidLocator, SourceError
from molhub.sources.locator import Locator
from molhub.sources.publication import Publication
from molhub.sources.remote import RemoteFile

__all__ = ["HuggingFaceSource"]

_DEFAULT_ENDPOINT = "https://huggingface.co"
_REPO_PREFIX = {"datasets": "datasets/", "models": "", "spaces": "spaces/"}
_FULL_COMMIT_OID = re.compile(r"(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64})\Z")


class HuggingFaceSource:
    """Resolve and publish files in a HuggingFace Hub repository.

    Args:
        endpoint: Hub base URL. Point at ``https://hf-mirror.com`` to use a
            mirror without touching any manifest.
        repo_type: One of ``datasets``, ``models``, ``spaces``.
        token: Hub token, or ``$HF_TOKEN``. Only required to publish.
        transfer: Object performing the byte transfer.
    """

    scheme = "hf"

    def __init__(
        self,
        *,
        endpoint: str = _DEFAULT_ENDPOINT,
        repo_type: str = "datasets",
        token: str | None = None,
        transfer: HttpsSource | None = None,
    ) -> None:
        if repo_type not in _REPO_PREFIX:
            raise ValueError(
                f"Unknown HuggingFace repo_type {repo_type!r}; "
                f"expected one of {sorted(_REPO_PREFIX)}."
            )
        self._endpoint = endpoint.rstrip("/")
        self._repo_type = repo_type
        self._token = token
        self._transfer = transfer or HttpsSource()

    # -- publishing ----------------------------------------------------------

    def publish(
        self,
        files: Sequence[Path],
        target: str,
        publication: Publication,
    ) -> Locator:
        """Publish one public file at an immutable Hub commit.

        Args:
            files: A sequence containing exactly one existing regular file.
            target: Repository id, ``"org/name"``.
            publication: Descriptive metadata for a public publication. This
                driver does not write the title, description, license, or
                keywords to a repository card.

        Returns:
            ``hf://<org>/<repo>@<full commit OID>/<filename>``.

        Raises:
            FileNotFoundError: If the selected file does not exist.
            SourceError: If the input is not one public regular file, or the
                Hub does not return a full immutable commit OID.

        All input-validation failures occur before the driver accesses the
        Hub.
        """
        paths = [Path(f) for f in files]
        if len(paths) != 1:
            raise SourceError("HuggingFace publication requires exactly one regular file.")
        path = paths[0]
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise SourceError("HuggingFace publication requires exactly one regular file.")
        if publication.private:
            raise SourceError("HuggingFace publication must be public, not private.")

        self.create_repo(target, private=False)
        result = self.upload_file(path, target, path_in_repo=path.name)
        oid = getattr(result, "oid", None)
        if not isinstance(oid, str) or _FULL_COMMIT_OID.fullmatch(oid) is None:
            raise SourceError("HuggingFace upload did not return a full immutable commit OID.")
        return Locator(scheme=self.scheme, path=f"{target}@{oid.lower()}/{path.name}")

    def create_repo(
        self,
        repo_id: str,
        *,
        private: bool = False,
        exist_ok: bool = True,
    ) -> str:
        """Create a Hub repository, returning its URL."""
        from huggingface_hub import create_repo as _create_repo

        return _create_repo(
            repo_id=repo_id,
            repo_type=self._hub_repo_type,
            private=private,
            token=self._token,
            exist_ok=exist_ok,
        )

    def upload_file(
        self,
        local_path: str | Path,
        repo_id: str,
        path_in_repo: str,
        *,
        commit_message: str | None = None,
        **kwargs: Any,
    ) -> object:
        """Upload a single file and preserve the Hub response.

        Args:
            local_path: Existing local file to upload.
            repo_id: Destination repository id, ``"org/name"``.
            path_in_repo: Destination path inside the repository.
            commit_message: Optional commit message. By default, the message
                names the uploaded file.
            **kwargs: Additional arguments forwarded to the Hub client.

        Returns:
            The exact object returned by ``huggingface_hub.upload_file``.
        """
        from huggingface_hub import upload_file as _upload_file

        return _upload_file(
            path_or_fileobj=str(local_path),
            path_in_repo=path_in_repo,
            repo_id=repo_id,
            repo_type=self._hub_repo_type,
            token=self._token,
            commit_message=commit_message or f"Upload {Path(local_path).name}",
            **kwargs,
        )

    def upload_folder(
        self,
        local_dir: str | Path,
        repo_id: str,
        path_in_repo: str = "",
        *,
        commit_message: str | None = None,
        **kwargs: Any,
    ) -> object:
        """Upload a directory and preserve the Hub response.

        Args:
            local_dir: Existing local directory to upload.
            repo_id: Destination repository id, ``"org/name"``.
            path_in_repo: Destination path inside the repository.
            commit_message: Optional commit message. By default, the message
                names the uploaded directory.
            **kwargs: Additional arguments forwarded to the Hub client.

        Returns:
            The exact object returned by ``huggingface_hub.upload_folder``.
        """
        from huggingface_hub import upload_folder as _upload_folder

        return _upload_folder(
            folder_path=str(local_dir),
            path_in_repo=path_in_repo,
            repo_id=repo_id,
            repo_type=self._hub_repo_type,
            token=self._token,
            commit_message=commit_message or f"Upload folder {Path(local_dir).name}",
            **kwargs,
        )

    @property
    def _hub_repo_type(self) -> str:
        """``huggingface_hub`` spells the repo type in the singular."""
        return {"datasets": "dataset", "models": "model", "spaces": "space"}[self._repo_type]

    # -- reading -------------------------------------------------------------

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        """Build the direct resolve URL for one file in a repository.

        Raises:
            InvalidLocator: If the path is not ``org/repo[@revision]/file...``.
        """
        parts = locator.path.split("/")
        if len(parts) < 3:
            raise InvalidLocator(
                f"HuggingFace locator {locator} must be 'org/repo[@revision]/path/to/file'."
            )
        org, repo_and_revision, *file_parts = parts
        repo, _, revision = repo_and_revision.partition("@")
        revision = revision or "main"
        file_path = "/".join(file_parts)
        prefix = _REPO_PREFIX[self._repo_type]
        url = f"{self._endpoint}/{prefix}{org}/{repo}/resolve/{revision}/{file_path}"
        return [RemoteFile(url=url, filename=file_parts[-1])]

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        """Delegate the transfer, which is plain HTTPS."""
        return self._transfer.fetch(remote, dest)
