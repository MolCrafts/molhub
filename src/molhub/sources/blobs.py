"""Local cache for fetched artifact files.

Files are filed under the key the caller names them by — in practice a
coordinate plus a role, e.g. ``dataset/molcrafts/qm9@v2/main``. That is what a
manifest already identifies, so no digest is needed to address the cache and
none has to be invented when a platform publishes none.

    $MOLHUB_HOME/                default ~/.cache/molhub
      files/<key>/<...>          fetched artifacts, keyed by coordinate + role
      tmp/                       in-flight transfers, same filesystem

The layout is a shared contract: the TypeScript client uses the same directory
so two clients on one machine share downloads.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

__all__ = ["BlobStore"]

_ENV_VAR = "MOLHUB_HOME"
_DEFAULT_SUBPATH = (".cache", "molhub")
_UNSAFE = re.compile(r"[^A-Za-z0-9._@-]+")


class BlobStore:
    """Fetched files on local disk, addressed by caller-supplied key.

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

    @staticmethod
    def _segments(key: str) -> list[str]:
        """Split *key* into path-safe segments.

        ``/`` in the key becomes a directory boundary; everything else that
        could escape the cache or upset a filesystem is replaced.
        """
        parts = [_UNSAFE.sub("_", part) for part in key.split("/") if part not in ("", ".", "..")]
        if not parts:
            raise ValueError(f"Cache key {key!r} has no usable segments.")
        return parts

    def path_for(self, key: str) -> Path:
        """Return the path *key* occupies, whether or not anything is there."""
        return self._root.joinpath("files", *self._segments(key))

    def temp_path(self, key: str) -> Path:
        """Return a scratch path for an in-flight transfer of *key*.

        Kept under the same root as :meth:`path_for`, so the final move is a
        same-filesystem rename and therefore atomic.
        """
        return self._root / "tmp" / f"{'_'.join(self._segments(key))}.part"

    def has(self, key: str) -> bool:
        """Whether a non-empty file is cached under *key*.

        A zero-byte file counts as absent: that is what an interrupted transfer
        leaves behind, and treating it as a hit is how such a failure becomes
        permanent.
        """
        path = self.path_for(key)
        return path.is_file() and path.stat().st_size > 0

    def put(self, source: Path, key: str) -> Path:
        """Move *source* into the cache under *key* and return its path."""
        target = self.path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        Path(source).replace(target)
        return target
