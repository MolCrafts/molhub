"""Figshare driver.

Figshare DOIs are persistent, but the raw download endpoint is not a stable
contract: it answers ``202 Accepted`` with an empty body while preparing a
file. Resolving through the API instead of hard-coding a download URL is what
lets molhub see the real file list and its published md5.

Locator forms::

    figshare://978904                 every file in the article
    figshare://978904/qm9.tar.bz2     one named file
"""

from __future__ import annotations

from pathlib import Path

from molhub.registry.drivers._api import fetch_json
from molhub.registry.drivers.https import HttpsRegistry
from molhub.registry.errors import RegistryError
from molhub.registry.locator import Locator
from molhub.registry.remote import RemoteFile

__all__ = ["FigshareRegistry"]

_DEFAULT_API = "https://api.figshare.com/v2"


class FigshareRegistry:
    """Resolves Figshare articles into downloadable files.

    Args:
        api_base: API root.
        transfer: Object performing the byte transfer.
    """

    scheme = "figshare"

    def __init__(
        self,
        *,
        api_base: str = _DEFAULT_API,
        transfer: HttpsRegistry | None = None,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._transfer = transfer or HttpsRegistry()

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        """Resolve an article id, optionally narrowed to one filename.

        Raises:
            RegistryError: If the article has no files, or the requested
                filename is absent from it.
        """
        article_id, _, wanted = locator.path.partition("/")
        entries = fetch_json(f"{self._api_base}/articles/{article_id}/files")
        if not entries:
            raise RegistryError(f"Figshare article {article_id} lists no files.")

        remotes = [self._to_remote(entry) for entry in entries]
        if not wanted:
            return remotes
        matched = [remote for remote in remotes if remote.filename == wanted]
        if not matched:
            available = ", ".join(sorted(remote.filename for remote in remotes))
            raise RegistryError(
                f"Figshare article {article_id} has no file {wanted!r}. Available: {available}"
            )
        return matched

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        """Delegate the transfer, which is plain HTTPS."""
        return self._transfer.fetch(remote, dest)

    @staticmethod
    def _to_remote(entry: dict) -> RemoteFile:
        md5 = entry.get("supplied_md5") or entry.get("computed_md5")
        return RemoteFile(
            url=entry.get("download_url", ""),
            filename=entry.get("name", ""),
            size=entry.get("size"),
            upstream_digest=f"md5:{md5}" if md5 else None,
        )
