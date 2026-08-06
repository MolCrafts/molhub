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

from pathlib import Path

from molhub.registry.drivers.https import HttpsRegistry
from molhub.registry.errors import InvalidLocator
from molhub.registry.locator import Locator
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
        transfer: Object performing the byte transfer.
    """

    scheme = "hf"

    def __init__(
        self,
        *,
        endpoint: str = _DEFAULT_ENDPOINT,
        repo_type: str = "datasets",
        transfer: HttpsRegistry | None = None,
    ) -> None:
        if repo_type not in _REPO_PREFIX:
            raise ValueError(
                f"Unknown HuggingFace repo_type {repo_type!r}; "
                f"expected one of {sorted(_REPO_PREFIX)}."
            )
        self._endpoint = endpoint.rstrip("/")
        self._repo_type = repo_type
        self._transfer = transfer or HttpsRegistry()

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
