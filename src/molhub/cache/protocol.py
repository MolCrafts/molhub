"""A byte cache. The key and the value are opaque; the caller names both."""

from __future__ import annotations

from typing import Protocol

__all__ = ["Cache"]


class Cache(Protocol):
    """``get`` returns the stored bytes, or None when *key* was never written."""

    def get(self, key: bytes) -> bytes | None:
        """The value stored at *key*, or None."""

    def put(self, key: bytes, value: bytes) -> None:
        """Store *value* at *key*. A second put replaces it."""
