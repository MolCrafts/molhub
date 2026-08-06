"""Content digests — molhub's authority on whether bytes are the right bytes.

Upstream platforms publish digests in different algorithms (Zenodo md5,
HuggingFace sha256 LFS OIDs, Figshare md5), so :class:`Digest` can carry any of
them for reconciliation. molhub's own cache key is always sha256: it is the
strongest of the three and a content-addressed store needs one uniform key.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from hmac import compare_digest
from pathlib import Path

from molhub.registry.errors import InvalidDigest

__all__ = ["Digest", "Sha256Stream"]

# Algorithm -> expected hex length. Only algorithms molhub can encounter.
_HEX_LENGTHS: dict[str, int] = {"sha256": 64, "sha512": 128, "md5": 32, "sha1": 40}

_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Digest:
    """An algorithm plus a hex digest.

    Attributes:
        algorithm: One of ``sha256``, ``sha512``, ``md5``, ``sha1``.
        hexdigest: Lower-case hex string of the length that algorithm requires.
    """

    algorithm: str
    hexdigest: str

    def __post_init__(self) -> None:
        algorithm = self.algorithm.lower()
        expected = _HEX_LENGTHS.get(algorithm)
        if expected is None:
            raise InvalidDigest(
                f"Unsupported digest algorithm {self.algorithm!r}; "
                f"expected one of {sorted(_HEX_LENGTHS)}."
            )
        hexdigest = self.hexdigest.strip().lower()
        if len(hexdigest) != expected or not all(c in "0123456789abcdef" for c in hexdigest):
            raise InvalidDigest(
                f"{algorithm} digest must be {expected} hex characters; got {self.hexdigest!r}."
            )
        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(self, "hexdigest", hexdigest)

    @classmethod
    def sha256(cls, hexdigest: str) -> "Digest":
        """Build a sha256 digest from a hex string."""
        return cls(algorithm="sha256", hexdigest=hexdigest)

    @classmethod
    def parse(cls, text: str) -> "Digest":
        """Parse an ``algorithm:hex`` string, as published by upstream APIs.

        Args:
            text: For example ``"md5:ce2c7b2a879450cbbfff4d7ccea648f9"``.

        Returns:
            The parsed :class:`Digest`.

        Raises:
            InvalidDigest: If the string lacks a colon, or either half is invalid.
        """
        algorithm, separator, hexdigest = text.strip().partition(":")
        if not separator:
            raise InvalidDigest(
                f"Malformed digest {text!r}; expected 'algorithm:hex', e.g. 'sha256:abc…'."
            )
        return cls(algorithm=algorithm, hexdigest=hexdigest)

    @classmethod
    def of_file(cls, path: Path, *, algorithm: str = "sha256") -> "Digest":
        """Compute the digest of a file, streaming it in chunks.

        Args:
            path: File to read.
            algorithm: Hash algorithm; defaults to molhub's canonical sha256.

        Returns:
            The computed :class:`Digest`.
        """
        hasher = hashlib.new(algorithm)
        with open(path, "rb") as handle:
            while chunk := handle.read(_CHUNK_BYTES):
                hasher.update(chunk)
        return cls(algorithm=algorithm, hexdigest=hasher.hexdigest())

    def matches(self, other: "Digest") -> bool:
        """Whether *other* is the same algorithm and the same digest.

        Comparison is constant-time, so a digest check cannot be probed by
        timing when molhub is used behind a service.
        """
        return self.algorithm == other.algorithm and compare_digest(self.hexdigest, other.hexdigest)

    def __str__(self) -> str:
        return f"{self.algorithm}:{self.hexdigest}"


class Sha256Stream:
    """Incremental sha256 over bytes as they are transferred.

    Lets a driver hash a body while streaming it, instead of reading the file
    back afterwards.
    """

    def __init__(self) -> None:
        self._hasher = hashlib.sha256()

    def update(self, chunk: bytes) -> None:
        """Fold *chunk* into the running digest."""
        self._hasher.update(chunk)

    def digest(self) -> Digest:
        """Return the digest of everything folded in so far.

        Safe to call repeatedly; the running state is not consumed.
        """
        return Digest.sha256(self._hasher.hexdigest())
