"""Plain HTTP(S) transfer.

Also the transfer half of every platform driver: Zenodo, Figshare and
HuggingFace differ only in how they resolve a locator into direct URLs, so they
compose this class rather than reimplementing the transfer contract.
"""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

from molhub.sources.errors import BadStatus
from molhub.sources.locator import Locator
from molhub.sources.remote import RemoteFile

__all__ = ["HttpsSource"]

_USER_AGENT = "molhub/0.1 (+https://github.com/MolCrafts/molhub)"
_TEMP_SUFFIX = ".part"


class HttpsSource:
    """Fetches bytes over HTTP(S).

    Args:
        user_agent: Value sent as ``User-Agent``. Some scientific hosts reject
            the stdlib default.
    """

    scheme = "https"

    def __init__(self, *, user_agent: str = _USER_AGENT) -> None:
        self._user_agent = user_agent

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        """Treat the locator as a direct URL to a single file."""
        url = f"{locator.scheme}://{locator.path}"
        return [RemoteFile(url=url, filename=self._filename_from_url(url))]

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        """Transfer *remote* to *dest*, leaving nothing behind on failure.

        Streams into a sibling ``.part`` file and renames only after the body
        has been read in full, so neither a non-200 response nor a mid-transfer
        error can leave a file at *dest* that a later run would trust.

        Args:
            remote: File to transfer.
            dest: Destination path; parent directories are created.

        Returns:
            *dest*.

        Raises:
            BadStatus: If the response status is not 200. Notably, Figshare
                answers 202 with an empty body while preparing a file.
        """
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(dest.name + _TEMP_SUFFIX)
        request = urllib.request.Request(remote.url, headers={"User-Agent": self._user_agent})
        try:
            with urllib.request.urlopen(request) as response:
                if response.status != 200:
                    raise BadStatus(
                        f"{remote.url} returned HTTP {response.status}, expected 200. "
                        "Some hosts answer 202 while preparing a file asynchronously — "
                        "retry shortly."
                    )
                with open(partial, "wb") as handle:
                    shutil.copyfileobj(response, handle)
            partial.replace(dest)
        finally:
            partial.unlink(missing_ok=True)
        return dest

    @staticmethod
    def _filename_from_url(url: str) -> str:
        """Best-effort filename from a URL, ignoring any query string."""
        name = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        return name or "download"
