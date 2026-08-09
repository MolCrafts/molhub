"""Zenodo driver.

Zenodo is the closest thing to an archival guarantee in this set: files are
immutable once published, every record carries a versioned DOI plus a concept
DOI, and the REST API publishes a per-file md5. A manifest copies that md5
verbatim; it is what a fetch is checked against.

Locator forms::

    zenodo://14980914                 every file in the record
    zenodo://14980914/data.csv        one named file
"""

from __future__ import annotations

from pathlib import Path

from molhub.sources.drivers._api import fetch_json
from molhub.sources.drivers.https import HttpsSource
from molhub.sources.errors import SourceError
from molhub.sources.locator import Locator
from molhub.sources.remote import RemoteFile

__all__ = ["ZenodoSource"]

_DEFAULT_API = "https://zenodo.org/api"


class ZenodoSource:
    """Resolves Zenodo records into downloadable files.

    Args:
        api_base: API root; point it at a Zenodo instance such as
            ``https://sandbox.zenodo.org/api`` for testing.
        transfer: Object performing the byte transfer. Defaults to
            :class:`~molhub.sources.drivers.https.HttpsSource`.
    """

    scheme = "zenodo"

    def __init__(
        self,
        *,
        api_base: str = _DEFAULT_API,
        transfer: HttpsSource | None = None,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._transfer = transfer or HttpsSource()

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        """Resolve a record id, optionally narrowed to one filename.

        Raises:
            SourceError: If the record has no files, or the requested
                filename is absent from it.
        """
        record_id, _, wanted = locator.path.partition("/")
        payload = fetch_json(f"{self._api_base}/records/{record_id}")
        files = payload.get("files") or []
        if not files:
            raise SourceError(f"Zenodo record {record_id} lists no files.")

        remotes = [self._to_remote(entry) for entry in files]
        if not wanted:
            return remotes
        matched = [remote for remote in remotes if remote.filename == wanted]
        if not matched:
            available = ", ".join(sorted(remote.filename for remote in remotes))
            raise SourceError(
                f"Zenodo record {record_id} has no file {wanted!r}. Available: {available}"
            )
        return matched

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        """Delegate the transfer, which is plain HTTPS."""
        return self._transfer.fetch(remote, dest)

    @staticmethod
    def _to_remote(entry: dict) -> RemoteFile:
        return RemoteFile(
            url=entry.get("links", {}).get("self", ""),
            filename=entry.get("key", ""),
            size=entry.get("size"),
            upstream_digest=entry.get("checksum"),
        )
