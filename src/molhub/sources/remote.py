"""RemoteFile — one downloadable file, as a driver reports it."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RemoteFile"]


@dataclass(frozen=True)
class RemoteFile:
    """A single file a driver resolved from a locator.

    Attributes:
        url: Direct URL the transfer will read.
        filename: Name the file has upstream, for progress output and logs.
        size: Byte count when upstream publishes one, else ``None``.
        upstream_digest: The digest upstream publishes, in ``algorithm:hex``
            form, when it publishes one. molhub verifies against the digest in
            the manifest, not this — this is kept for reconciling with upstream
            and is often a weaker algorithm (Zenodo and Figshare publish md5).
    """

    url: str
    filename: str
    size: int | None = None
    upstream_digest: str | None = None
