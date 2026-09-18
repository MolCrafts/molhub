"""URL-addressed download cache for inputs that have no coordinate.

:class:`~molhub.sources.blobs.BlobStore` files an artifact under the key a
manifest already identifies it by — a coordinate plus a role. Nothing is
content-addressed and molhub never computes a digest of its own, so a cache
entry needs a coordinate, not a hash.

:class:`~molhub.dataset.csv_dataset.CSVDataset` accepts an arbitrary URL. A URL
a user typed has no coordinate, therefore no manifest entry, therefore no key
:class:`BlobStore` could file it under. That is why this class exists, and it
is not a stage on the way to something else: as long as the public API accepts
raw URLs, URL-addressed caching is the honest answer for them.

Both caches share the process home (``config.home_dir``)::

    ~/.cache/molhub/             default process home
      files/<key>/…              BlobStore — the cross-client layout contract
      tmp/                       BlobStore — in-flight transfers
      urls/<filename>            this cache

``urls/`` is **Python-local and not part of the shared layout contract**: the
TypeScript client neither reads nor writes it, and nothing here may be written
into ``files/``, which both clients read.

The root itself is ``config.home_dir`` when *root* is omitted. An explicit
*root* still wins. This class does not call :class:`BlobStore` to resolve home.
"""

from __future__ import annotations

import re
from pathlib import Path

from molhub.config import config
from molhub.sources import FileTransfer, HttpsSource, RemoteFile

__all__ = ["DownloadCache"]

_URL_SUBDIR = "urls"
_UNSAFE = re.compile(r"[^A-Za-z0-9._@-]+")


class DownloadCache:
    """Caches remote files on disk under a name derived from their URL.

    Every path this class hands out is inside ``urls/`` and named after the URL
    it came from — that is the whole of what it does. Its one caller is
    :class:`~molhub.dataset.csv_dataset.CSVDataset`, whose raw URLs have no
    coordinate and so no :class:`BlobStore` key.

    Args:
        root: Cache root, shared with :class:`BlobStore`; downloads land in its
            ``urls/`` subdirectory. Defaults to ``config.home_dir``.
        transfer: Anything satisfying
            :class:`~molhub.sources.source.FileTransfer`. A URL is already
            located, so nothing here resolves or claims a scheme. Defaults to
            :class:`~molhub.sources.drivers.https.HttpsSource`, so cached
            downloads inherit the same status-checked, atomically-renamed
            transfer as everything else.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        transfer: FileTransfer | None = None,
    ) -> None:
        self._root = self._resolve_root(root)
        self._transfer = transfer or HttpsSource()

    @staticmethod
    def _resolve_root(root: str | Path | None) -> Path:
        """Resolve the cache root from *root* or ``config.home_dir``.

        An explicit *root* wins. This method does not call :class:`BlobStore`.
        """
        if root is not None:
            return Path(root).expanduser()
        return Path(config.home_dir).expanduser()

    @property
    def root(self) -> Path:
        """The cache root — the same directory :class:`BlobStore` uses."""
        return self._root

    def path_for(self, url: str) -> Path:
        """Return the path *url* is cached at, without touching the network."""
        return self._root / _URL_SUBDIR / self.filename_for(url)

    def fetch(self, url: str) -> Path:
        """Return a local path for *url*, downloading it if not already cached.

        Raises:
            BadStatus: If the server responds with a status other than 200.
        """
        destination = self.path_for(url)
        if destination.is_file() and destination.stat().st_size > 0:
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._transfer.fetch(RemoteFile(url=url, filename=destination.name), destination)
        return destination

    @staticmethod
    def filename_for(url: str) -> str:
        """Best-effort filename from a URL, ignoring any query string.

        The result is always a single path segment: anything that could escape
        ``urls/`` or upset a filesystem is replaced, and a URL that yields no
        usable name falls back to ``"download"``.
        """
        name = _UNSAFE.sub("_", url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1])
        return name if name.strip(".") else "download"
