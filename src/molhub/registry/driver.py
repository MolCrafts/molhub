"""The Registry driver protocol.

Supporting a new hosting platform means implementing this protocol and
registering it — either explicitly via
:meth:`~molhub.registry.drivers.Drivers.with_driver` or, for installed
packages, through the ``molhub.registries`` entry-point group. No molhub source
file changes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from molhub.registry.locator import Locator
from molhub.registry.remote import RemoteFile

__all__ = ["Registry"]


@runtime_checkable
class Registry(Protocol):
    """A remote that molhub can read bytes from.

    Implementors declare the locator scheme they claim and translate a locator
    into concrete downloadable files. Drivers deal in bytes only — they never
    parse content and never see a molhub coordinate.
    """

    scheme: str
    """The locator scheme this driver claims, e.g. ``"zenodo"``."""

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        """Turn *locator* into the files it refers to.

        Args:
            locator: A locator whose scheme equals :attr:`scheme`.

        Returns:
            One :class:`RemoteFile` per downloadable file.
        """
        ...

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        """Transfer *remote* to *dest*.

        Implementations must verify the response status before writing, stream
        the body rather than buffering it whole, and leave **no file at
        *dest*** if anything fails.

        Args:
            remote: The file to transfer.
            dest: Destination path; the caller owns it and will move the result
                into the content-addressed store after verifying its digest.

        Returns:
            *dest*.

        Raises:
            BadStatus: If the response status is not 200.
        """
        ...


class PublishingRegistry(Registry, Protocol):
    """A :class:`Registry` that can also accept uploads.

    Optional: drivers for read-only mirrors do not implement it.
    """

    def publish(
        self,
        files: Sequence[Path],
        target: str,
        meta: Mapping[str, object],
    ) -> Locator:
        """Upload *files* and return a locator addressing the result."""
        ...
