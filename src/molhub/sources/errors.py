"""Exceptions raised by the transport layer.

Every failure a caller can reasonably distinguish gets its own type, because
:class:`~molhub.sources.fetcher.Fetcher` decides whether to try the next
locator based on *which* failure occurred.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = [
    "SourceError",
    "InvalidLocator",
    "InvalidDigest",
    "UnknownScheme",
    "BadStatus",
    "DigestMismatch",
    "AllLocatorsFailed",
]


class SourceError(Exception):
    """Base class for every transport-layer failure."""


class InvalidLocator(SourceError):
    """A locator string does not match ``scheme://path``."""


class InvalidDigest(SourceError):
    """A digest string is malformed or uses an unsupported algorithm."""


class UnknownScheme(SourceError):
    """No registered driver claims the requested scheme."""


class BadStatus(SourceError):
    """A transfer returned an HTTP status other than 200.

    Notably raised for ``202 Accepted``, which some hosts return with an empty
    body while they prepare a file asynchronously.
    """


class DigestMismatch(SourceError):
    """Transferred bytes did not match the expected digest.

    This means the mirror served the wrong content, so the same locator is not
    retried — the fetcher moves on to the next one.
    """


class AllLocatorsFailed(SourceError):
    """Every locator for an artifact failed.

    The message lists each locator with its own reason, so a multi-source
    failure can be diagnosed from a single traceback.

    Args:
        reasons: ``(locator, error)`` pairs in the order they were attempted.
    """

    def __init__(self, reasons: Sequence[tuple[str, BaseException]]) -> None:
        self.reasons = tuple(reasons)
        if not self.reasons:
            super().__init__("No locators were supplied.")
            return
        detail = "\n".join(
            f"  {locator} -> {type(error).__name__}: {error}" for locator, error in self.reasons
        )
        super().__init__(f"All {len(self.reasons)} locator(s) failed:\n{detail}")
