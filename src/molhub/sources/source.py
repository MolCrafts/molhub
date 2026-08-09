"""The Source driver protocol.

Supporting a new hosting platform means implementing this protocol and
registering it — either explicitly via
:meth:`~molhub.sources.drivers.Drivers.with_driver` or, for installed
packages, through the ``molhub.sources`` entry-point group. No molhub source
file changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from molhub.sources.locator import Locator
from molhub.sources.publication import Publication
from molhub.sources.remote import RemoteFile

__all__ = ["FileTransfer", "Source", "PublishingSource"]


@runtime_checkable
class FileTransfer(Protocol):
    """Puts one already-located remote file onto local disk.

    Split out of :class:`Source` because callers that already know a URL do
    not need the rest of it. Such a caller has nothing to resolve and no scheme
    to claim, so requiring it to satisfy the whole driver interface would make
    it implement two members nobody calls — and would make its test fake do the
    same.
    """

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        """Transfer *remote* to *dest*.

        Implementations must verify the response status before writing, stream
        the body rather than buffering it whole, and leave **no file at
        *dest*** if anything fails.

        Args:
            remote: The file to transfer.
            dest: Destination path; the caller owns it and will move the result
                into the cache under the coordinate and role naming it, after
                checking any digest the manifest recorded.

        Returns:
            *dest*.

        Raises:
            BadStatus: If the response status is not 200.
        """
        ...


@runtime_checkable
class Source(FileTransfer, Protocol):
    """A remote that molhub can read bytes from.

    A :class:`FileTransfer` that can also work out *what* to transfer:
    implementors declare the locator scheme they claim and translate a locator
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


@runtime_checkable
class PublishingSource(Source, Protocol):
    """A :class:`Source` that can also accept uploads.

    Optional: drivers for read-only mirrors do not implement it.
    """

    def publish(
        self,
        files: Sequence[Path],
        target: str,
        publication: Publication,
    ) -> Locator:
        """Upload *files* and return a locator addressing the result.

        The returned locator is the point of the whole operation: it is what
        goes into an artifact manifest, so publishing and fetching close a
        loop rather than being two unrelated features.

        Args:
            files: Local files to upload. Must all exist.
            target: Where to put them, in this platform's own terms — a
                HuggingFace ``org/repo``, a Figshare article id, or the
                literal ``"new"`` where the platform can mint a container.
            publication: Descriptive metadata. Drivers document which fields
                they cannot express.

        Returns:
            A :class:`Locator` addressing the uploaded result.

        Raises:
            FileNotFoundError: If any path in *files* does not exist.
            SourceError: If the platform rejects the upload.
        """
        ...
