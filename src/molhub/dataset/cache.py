"""Filename-addressed download cache for the built-in dataset sources.

A stopgap. These sources still address their inputs by raw URL, so there is no
digest to key on and :class:`~molhub.registry.blobs.BlobStore` cannot be used.
Once a dataset is addressed by coordinate and fetched with the digest from its
manifest, this class goes away and the content-addressed store takes over.

What it does provide is a single place for the cache-path rule, replacing the
two identical copies that used to live in ``csv_dataset``.
"""

from __future__ import annotations

import os
from pathlib import Path

from molhub.registry import HttpsRegistry, RemoteFile

__all__ = ["DownloadCache"]

_ENV_VAR = "MOLHUB_CACHE_DIR"
_DEFAULT_SUBPATH = (".cache", "molhub")


class DownloadCache:
    """Caches remote files on disk under a name derived from their URL.

    Args:
        root: Cache directory. Defaults to ``$MOLHUB_CACHE_DIR``, then
            ``~/.cache/molhub``.
        transfer: Object performing the byte transfer. Defaults to
            :class:`~molhub.registry.drivers.https.HttpsRegistry`, so these
            sources inherit the same status-checked, atomically-renamed
            transfer as everything else.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        transfer: HttpsRegistry | None = None,
    ) -> None:
        self._root = self._resolve_root(root)
        self._transfer = transfer or HttpsRegistry()

    @staticmethod
    def _resolve_root(root: str | Path | None) -> Path:
        if root is not None:
            return Path(root).expanduser()
        if configured := os.environ.get(_ENV_VAR):
            return Path(configured).expanduser()
        return Path.home().joinpath(*_DEFAULT_SUBPATH)

    @property
    def root(self) -> Path:
        """The cache directory."""
        return self._root

    def path_for(self, url: str) -> Path:
        """Return the path *url* is cached at, without touching the network."""
        return self._root / self.filename_for(url)

    def fetch(self, url: str) -> Path:
        """Return a local path for *url*, downloading it if not already cached.

        Raises:
            BadStatus: If the server responds with a status other than 200.
        """
        destination = self.path_for(url)
        if destination.is_file() and destination.stat().st_size > 0:
            return destination
        self._root.mkdir(parents=True, exist_ok=True)
        self._transfer.fetch(RemoteFile(url=url, filename=destination.name), destination)
        return destination

    def transfer_to(self, url: str, destination: Path) -> Path:
        """Download *url* to an explicit *destination* outside the cache layout.

        For sources such as QM9 that keep a caller-supplied directory with
        fixed filenames rather than the cache's URL-derived naming.

        Raises:
            BadStatus: If the server responds with a status other than 200.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        return self._transfer.fetch(RemoteFile(url=url, filename=destination.name), destination)

    @staticmethod
    def filename_for(url: str) -> str:
        """Best-effort filename from a URL, ignoring any query string."""
        name = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        return name or "download"
