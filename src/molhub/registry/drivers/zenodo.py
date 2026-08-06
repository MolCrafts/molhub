"""Zenodo driver.

Zenodo is the closest thing to an archival guarantee in this set: files are
immutable once published, every record carries a versioned DOI plus a concept
DOI, and the REST API publishes a per-file md5. molhub still verifies against
its own sha256 — the md5 is kept for reconciling with upstream.

Locator forms::

    zenodo://14980914                 every file in the record
    zenodo://14980914/data.csv        one named file
"""

from __future__ import annotations

from pathlib import Path

from molhub.registry.drivers._api import fetch_json
from molhub.registry.drivers.https import HttpsRegistry
from molhub.registry.errors import RegistryError
from molhub.registry.locator import Locator
from molhub.registry.remote import RemoteFile

__all__ = ["ZenodoRegistry"]

_DEFAULT_API = "https://zenodo.org/api"


class ZenodoRegistry:
    """Resolves Zenodo records into downloadable files.

    Args:
        api_base: API root; point it at a Zenodo instance such as
            ``https://sandbox.zenodo.org/api`` for testing.
        transfer: Object performing the byte transfer. Defaults to
            :class:`~molhub.registry.drivers.https.HttpsRegistry`.
    """

    scheme = "zenodo"

    def __init__(
        self,
        *,
        api_base: str = _DEFAULT_API,
        transfer: HttpsRegistry | None = None,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._transfer = transfer or HttpsRegistry()

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        """Resolve a record id, optionally narrowed to one filename.

        Raises:
            RegistryError: If the record has no files, or the requested
                filename is absent from it.
        """
        record_id, _, wanted = locator.path.partition("/")
        payload = fetch_json(f"{self._api_base}/records/{record_id}")
        files = payload.get("files") or []
        if not files:
            raise RegistryError(f"Zenodo record {record_id} lists no files.")

        remotes = [self._to_remote(entry) for entry in files]
        if not wanted:
            return remotes
        matched = [remote for remote in remotes if remote.filename == wanted]
        if not matched:
            available = ", ".join(sorted(remote.filename for remote in remotes))
            raise RegistryError(
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
