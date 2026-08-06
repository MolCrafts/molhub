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

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from molhub.registry.drivers.https import HttpsRegistry
from molhub.registry.errors import InvalidLocator
from molhub.registry.locator import Locator
from molhub.registry.publication import Publication
from molhub.registry.remote import RemoteFile

__all__ = ["HuggingFaceRegistry"]

_DEFAULT_ENDPOINT = "https://huggingface.co"
_REPO_PREFIX = {"datasets": "datasets/", "models": "", "spaces": "spaces/"}


class HuggingFaceRegistry:
    """Turns a HuggingFace repo path into a resolve URL.

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
        transfer: HttpsRegistry | None = None,
    ) -> None:
        if repo_type not in _REPO_PREFIX:
            raise ValueError(
                f"Unknown HuggingFace repo_type {repo_type!r}; "
                f"expected one of {sorted(_REPO_PREFIX)}."
            )
        self._endpoint = endpoint.rstrip("/")
        self._repo_type = repo_type
        self._token = token
        self._transfer = transfer or HttpsRegistry()

    # -- publishing ----------------------------------------------------------

    def publish(
        self,
        files: Sequence[Path],
        target: str,
        publication: Publication,
    ) -> Locator:
        """Upload *files* to a Hub repository and return its locator.

        Args:
            files: Local files or directories to upload.
            target: Repository id, ``"org/name"``.
            publication: Descriptive metadata. Only ``private`` reaches the
                Hub API here; title, description and license belong in the
                repository card, which molhub does not write.

        Returns:
            ``hf://<org>/<repo>/<name of the last uploaded item>``.

        Raises:
            FileNotFoundError: If any path in *files* does not exist.
        """
        paths = [Path(f) for f in files]
        for path in paths:
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")

        self.create_repo(target, private=publication.private)
        for path in paths:
            if path.is_dir():
                self.upload_folder(path, target, path_in_repo=path.name)
            else:
                self.upload_file(path, target, path_in_repo=path.name)
        return Locator(scheme=self.scheme, path=f"{target}/{paths[-1].name}")

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
    ) -> str:
        """Upload a single file, returning its URL."""
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
    ) -> str:
        """Upload a whole directory, returning its URL."""
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
