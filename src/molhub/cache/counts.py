"""Per-row count vectors, cached beside the dataset they describe.

A packing budget needs one integer per row — how many atoms, how many bonds.
Some containers answer that from a column they already hold; a packed NPZ
stores ``n_atoms`` outright. Others cannot: an ASE-style LMDB has to decode a
record to learn its length, which on a four-million-row source is a quarter of
an hour of work to rediscover a number that never changes.

So this module caches exactly that, and nothing else.

**The key is a fingerprint of the files, not a description of the dataset.**
An earlier design keyed on a ten-field tuple — source revision, shard digests,
adapter schema version, record identity, row-mapping digest, row domain,
length, quantity, dtype, schema version — which meant every way a cache could
go stale had to be *enumerated* and kept in sync with the readers. Keying on
``(name, size, mtime)`` of the files themselves inverts that: a file that
changed produces a different key, and staleness stops being a case analysis.

**A vector is whole or absent.** There is no partially-known mask and no
conflict protocol. A scan is sequential; an interrupted one is repeated, which
is cheaper than the machinery for resuming it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import numpy as np

__all__ = ["CountSidecar"]


class CountSidecar:
    """The cached per-row count vector of one field over one set of files.

    Args:
        sources: Files the vector was measured from, in the order the rows
            are indexed. Their name, size and modification time make the key.
        field: Frame field the vector holds, e.g. ``graph.natoms``.
        root: Directory the ``.npy`` lives in. Defaults to
            ``<molhub home>/counts``.

    Example::

        sidecar = CountSidecar(paths, "graph.natoms")
        counts = sidecar.load(n_rows=len(dataset))
        if counts is None:
            counts = measure()          # the expensive scan
            sidecar.save(counts)
    """

    def __init__(
        self,
        sources: Sequence[Path | str],
        field: str,
        *,
        root: Path | str | None = None,
    ) -> None:
        self.sources = tuple(Path(p) for p in sources)
        self.field = str(field)
        self.root = Path(root) if root is not None else self._default_root()

    @staticmethod
    def _default_root() -> Path:
        from molhub.config import config

        return Path(getattr(config, "home_dir", Path.home() / ".molhub")) / "counts"

    @property
    def key(self) -> str:
        """Fingerprint of the sources and the field.

        Hashes each file's name, byte size and modification time in source
        order, then the field name. A replaced shard, a reordered index, a
        truncated file — each changes a byte that goes into this digest, so
        none of them needs its own staleness rule.
        """
        h = hashlib.blake2b(digest_size=16)
        for path in self.sources:
            try:
                stat = path.stat()
                token = f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}"
            except OSError:
                token = f"{path.name}:missing"
            h.update(token.encode())
            h.update(b"\x00")
        h.update(self.field.encode())
        return h.hexdigest()

    @property
    def path(self) -> Path:
        """Where this vector is stored."""
        return self.root / f"{self.key}.npy"

    def load(self, *, n_rows: int) -> np.ndarray | None:
        """The cached vector, or ``None`` when there is no usable one.

        A file whose length disagrees with *n_rows* is treated as absent
        rather than trusted: the caller asked about a different row set than
        the one that was measured, and a silently short vector would mis-size
        every batch built from it.

        Args:
            n_rows: Number of rows the caller expects.

        Returns:
            The vector, or ``None`` on a miss, a length mismatch, or an
            unreadable file.
        """
        path = self.path
        if not path.is_file():
            return None
        try:
            counts = np.load(path)
        except (OSError, ValueError):
            return None
        if counts.ndim != 1 or int(counts.shape[0]) != int(n_rows):
            return None
        return counts

    def save(self, counts: np.ndarray) -> Path:
        """Store *counts*, creating the directory if needed.

        Writes through a temporary file in the same directory and renames, so
        a reader never sees a half-written vector and a crashed writer leaves
        no file that would later load as a valid short one.

        Args:
            counts: The 1-D vector to store.

        Returns:
            The path written.

        Raises:
            ValueError: *counts* is not 1-D.
        """
        counts = np.asarray(counts)
        if counts.ndim != 1:
            raise ValueError(f"counts must be 1-D, got shape {tuple(counts.shape)}")
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path
        tmp = target.with_name(target.name + ".tmp")
        # Through a file object: given a path that does not end in ``.npy``,
        # ``np.save`` appends the suffix itself and the rename below would
        # then look for a name nothing wrote.
        with open(tmp, "wb") as handle:
            np.save(handle, counts)
        tmp.replace(target)
        return target
