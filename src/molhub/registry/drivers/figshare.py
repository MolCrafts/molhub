"""Figshare driver.

Figshare DOIs are persistent, but the raw download endpoint is not a stable
contract: it answers ``202 Accepted`` with an empty body while preparing a
file. Resolving through the API instead of hard-coding a download URL is what
lets molhub see the real file list and its published md5.

Locator forms::

    figshare://978904                 every file in the article
    figshare://978904/qm9.tar.bz2     one named file
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from molhub.registry.drivers._api import fetch_json
from molhub.registry.drivers.https import HttpsRegistry
from molhub.registry.errors import RegistryError
from molhub.registry.locator import Locator
from molhub.registry.publication import Publication
from molhub.registry.remote import RemoteFile

__all__ = ["FigshareRegistry"]

_DEFAULT_API = "https://api.figshare.com/v2"


class FigshareRegistry:
    """Resolves Figshare articles into downloadable files.

    Reading is anonymous; only :meth:`publish` needs a token.

    Args:
        api_base: API root.
        token: Figshare personal access token, or ``$FIGSHARE_TOKEN``. Only
            required to publish.
        transfer: Object performing the byte transfer.
    """

    scheme = "figshare"

    def __init__(
        self,
        *,
        api_base: str = _DEFAULT_API,
        token: str | None = None,
        transfer: HttpsRegistry | None = None,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._token = token or os.environ.get("FIGSHARE_TOKEN")
        self._transfer = transfer or HttpsRegistry()
        self._session_cache: Any = None

    # -- publishing ----------------------------------------------------------

    @property
    def _session(self) -> Any:
        """An authenticated ``requests`` session, created on first use.

        ``requests`` is imported lazily so that the read path never pays for
        it, and so a token is only demanded when something is actually
        published.
        """
        if self._session_cache is None:
            if not self._token:
                raise RegistryError(
                    "Figshare token required to publish. Pass token= or set "
                    "the FIGSHARE_TOKEN environment variable."
                )
            import requests

            session = requests.Session()
            session.headers.update(
                {"Authorization": f"token {self._token}", "Accept": "application/json"}
            )
            self._session_cache = session
        return self._session_cache

    def publish(
        self,
        files: Sequence[Path],
        target: str,
        publication: Publication,
    ) -> Locator:
        """Upload *files* to a Figshare article and return its locator.

        Args:
            files: Local files to upload.
            target: ``"new"`` to create an article, or an existing article id.
            publication: Descriptive metadata. ``private`` is not expressible —
                Figshare articles start unpublished and are made public by a
                separate action, so a private publication is the normal state
                and the flag is ignored.

        Returns:
            ``figshare://<article_id>``.

        Raises:
            FileNotFoundError: If any path in *files* does not exist.
            RegistryError: If no token is configured.
        """
        paths = [Path(f) for f in files]
        for path in paths:
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")

        if target == "new":
            article_id = int(
                self.create_article(
                    title=publication.title,
                    description=publication.description,
                    tags=list(publication.keywords) or None,
                )["id"]
            )
        else:
            article_id = int(target)

        for path in paths:
            self.upload_file(path, article_id)
        return Locator(scheme=self.scheme, path=str(article_id))

    def create_article(
        self,
        title: str,
        *,
        description: str = "",
        category: str | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Create a Figshare article (item) and return its metadata.

        Args:
            title: Article title.
            description: Optional description.
            category: Optional category id or name.
            tags: Optional list of tags.
            **kwargs: Additional article fields passed through verbatim.

        Returns:
            The created article, including its ``id``.
        """
        payload: dict[str, Any] = {
            "title": title,
            "description": description,
            "defined_type": "dataset",
        }
        if category:
            payload["categories"] = [category]
        if tags:
            payload["tags"] = tags
        payload.update(kwargs)

        response = self._session.post(f"{self._api_base}/account/articles", json=payload)
        response.raise_for_status()
        return response.json()

    def upload_file(
        self,
        local_path: str | Path,
        article_id: int,
        *,
        filename: str | None = None,
    ) -> dict:
        """Upload one file to an existing article.

        Figshare's upload is a four-step dance: announce the file, read back
        the part layout, PUT each part, then confirm.

        Args:
            local_path: File to upload.
            article_id: Target article.
            filename: Name to use upstream; defaults to the local name.

        Returns:
            The file metadata Figshare returned when the upload was announced.

        Raises:
            FileNotFoundError: If *local_path* does not exist.
        """
        local_path = Path(local_path)
        if not local_path.exists():
            raise FileNotFoundError(f"File not found: {local_path}")

        announcement = self._session.post(
            f"{self._api_base}/account/articles/{article_id}/files",
            json={"name": filename or local_path.name, "size": int(local_path.stat().st_size)},
        )
        announcement.raise_for_status()
        file_info = announcement.json()

        upload_url = file_info.get("upload_url") or file_info["location"]
        layout = self._session.get(upload_url)
        layout.raise_for_status()
        parts = layout.json().get("parts", [])

        if not parts:
            with open(local_path, "rb") as handle:
                self._session.put(upload_url, data=handle.read()).raise_for_status()
        else:
            uploaded = []
            with open(local_path, "rb") as handle:
                for part in parts:
                    chunk = handle.read(part["endOffset"] - part["startOffset"] + 1)
                    self._session.put(
                        f"{upload_url}/{part['partNo']}", data=chunk
                    ).raise_for_status()
                    uploaded.append({"partNo": part["partNo"], "etag": "uploaded"})
            self._session.post(upload_url, json={"parts": uploaded}).raise_for_status()

        return file_info

    # -- reading -------------------------------------------------------------

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        """Resolve an article id, optionally narrowed to one filename.

        Raises:
            RegistryError: If the article has no files, or the requested
                filename is absent from it.
        """
        article_id, _, wanted = locator.path.partition("/")
        entries = fetch_json(f"{self._api_base}/articles/{article_id}/files")
        if not entries:
            raise RegistryError(f"Figshare article {article_id} lists no files.")

        remotes = [self._to_remote(entry) for entry in entries]
        if not wanted:
            return remotes
        matched = [remote for remote in remotes if remote.filename == wanted]
        if not matched:
            available = ", ".join(sorted(remote.filename for remote in remotes))
            raise RegistryError(
                f"Figshare article {article_id} has no file {wanted!r}. Available: {available}"
            )
        return matched

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        """Delegate the transfer, which is plain HTTPS."""
        return self._transfer.fetch(remote, dest)

    @staticmethod
    def _to_remote(entry: dict) -> RemoteFile:
        md5 = entry.get("supplied_md5") or entry.get("computed_md5")
        return RemoteFile(
            url=entry.get("download_url", ""),
            filename=entry.get("name", ""),
            size=entry.get("size"),
            upstream_digest=f"md5:{md5}" if md5 else None,
        )
