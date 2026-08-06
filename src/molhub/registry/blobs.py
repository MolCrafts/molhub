"""Content-addressed local cache.

The on-disk layout is a **frozen contract** (see CLAUDE.md): the TypeScript
client uses the same directory so that two clients on one machine share
downloads. Changing it requires updating both implementations and bumping the
schema version.

    $MOLHUB_HOME/                       default ~/.cache/molhub
      blobs/<algorithm>/<ab>/<hex>      immutable, addressed by content
      tmp/                              in-flight transfers, same filesystem
"""

from __future__ import annotations

import os
from pathlib import Path

from molhub.registry.digest import Digest

__all__ = ["BlobStore"]

_ENV_VAR = "MOLHUB_HOME"
_DEFAULT_SUBPATH = (".cache", "molhub")


class BlobStore:
    """Immutable blobs on local disk, addressed by digest.

    Args:
        root: Cache root. Defaults to ``$MOLHUB_HOME``, then
            ``~/.cache/molhub``.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = self._resolve_root(root)

    @staticmethod
    def _resolve_root(root: str | Path | None) -> Path:
        if root is not None:
            return Path(root).expanduser()
        if configured := os.environ.get(_ENV_VAR):
            return Path(configured).expanduser()
        return Path.home().joinpath(*_DEFAULT_SUBPATH)

    @property
    def root(self) -> Path:
        """The cache root directory."""
        return self._root

    def path_for(self, digest: Digest) -> Path:
        """Return the canonical path a blob with *digest* occupies.

        The path exists only if the blob has been stored; this is pure
        arithmetic on the digest.
        """
        return self._root / "blobs" / digest.algorithm / digest.hexdigest[:2] / digest.hexdigest

    def temp_path(self, digest: Digest) -> Path:
        """Return a scratch path for an in-flight transfer of *digest*.

        Kept under the same root as :meth:`path_for` so the final move is a
        same-filesystem rename, which is atomic.
        """
        return self._root / "tmp" / f"{digest.hexdigest}.part"

    def has(self, digest: Digest) -> bool:
        """Whether a non-empty blob for *digest* is already stored.

        A zero-byte file counts as absent: that is what an interrupted or
        wrongly-accepted transfer leaves behind, and treating it as a cache hit
        is how such a failure becomes permanent.
        """
        path = self.path_for(digest)
        return path.is_file() and path.stat().st_size > 0

    def put(self, source: Path, digest: Digest) -> Path:
        """Move *source* into the store under *digest* and return its path.

        The caller is responsible for having verified that *source* actually
        hashes to *digest*.
        """
        target = self.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        Path(source).replace(target)
        return target
