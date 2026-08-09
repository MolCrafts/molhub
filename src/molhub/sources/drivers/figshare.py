"""Figshare driver.

Figshare DOIs are persistent, but the raw download endpoint is not a stable
contract: it answers ``202 Accepted`` with an empty body while preparing a
file. Resolving through the API instead of hard-coding a download URL is what
lets molhub see the real file list and its published md5.

A Figshare article id is **not** version-specific — article 1057646 has both a
v1 and a v2 — so a locator that omits the version silently follows whatever
upstream publishes next. Pin it.

Locator forms::

    figshare://1057646/v2                     every file in version 2
    figshare://1057646/v2/qm9.tar.bz2         one named file in version 2
    figshare://1057646                        latest version (discouraged)
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from molhub.sources.drivers._api import fetch_json
from molhub.sources.drivers.https import HttpsSource
from molhub.sources.errors import SourceError
from molhub.sources.locator import Locator
from molhub.sources.publication import Publication
from molhub.sources.remote import RemoteFile

__all__ = ["FigshareSource"]

_DEFAULT_API = "https://api.figshare.com/v2"


class FigshareSource:
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
        transfer: HttpsSource | None = None,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._token = token or os.environ.get("FIGSHARE_TOKEN")
        self._transfer = transfer or HttpsSource()
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
                raise SourceError(
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
        """Publish one public file and return its immutable Figshare locator.

        The file is validated before an authenticated session is created. The
        upload is completed, the article is published, and its authoritative
        version is read before a locator is returned.

        Args:
            files: A sequence containing exactly one local regular file.
            target: ``"new"`` to create an article, or an existing article id.
            publication: Descriptive metadata for a public article. Private
                publication is rejected because the returned locator must be
                anonymously resolvable.

        Returns:
            ``figshare://<article_id>/v<version>/<filename>`` pinned to the
            exact published version and file.

        Raises:
            FileNotFoundError: If the file does not exist.
            SourceError: If the input is not one public regular file, no token
                is configured, or Figshare omits usable file, name, or version
                metadata.
        """
        paths = [Path(f) for f in files]
        if len(paths) != 1:
            raise SourceError("Figshare publish requires exactly one file.")
        path = paths[0]
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise SourceError(f"Figshare publish requires a regular file: {path}")
        if publication.private:
            raise SourceError("Figshare publish only supports public publications.")

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

        file_info = self.upload_file(path, article_id)
        filename = file_info.get("name")
        if not isinstance(filename, str) or not filename or filename != path.name:
            raise SourceError(
                "Figshare did not return a matching usable filename for the uploaded file."
            )

        try:
            published = self._session.post(
                f"{self._api_base}/account/articles/{article_id}/publish"
            )
            published.raise_for_status()
        except Exception as exc:
            raise SourceError("Figshare article publish/finalize failed.") from exc

        version = self._version_from_response(published)
        if version is None:
            location = self._response_location(published)
            if location:
                detail = self._session.get(location)
                detail.raise_for_status()
                version = self._version_from_response(detail)
        if version is None:
            detail = self._session.get(f"{self._api_base}/account/articles/{article_id}")
            detail.raise_for_status()
            version = self._version_from_response(detail)
        if version is None:
            raise SourceError("Figshare did not return an authoritative article version.")

        return Locator(
            scheme=self.scheme,
            path=f"{article_id}/v{version}/{filename}",
        )

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
        article = self._response_json(response)
        if "id" not in article:
            location = self._response_location(response)
            if location:
                detail = self._session.get(location)
                detail.raise_for_status()
                article = self._response_json(detail)
        if "id" not in article:
            raise SourceError("Figshare did not return a usable article id.")
        return article

    def upload_file(
        self,
        local_path: str | Path,
        article_id: int,
        *,
        filename: str | None = None,
    ) -> dict:
        """Upload and complete one regular file on an existing article.

        Figshare first announces the file, exposes the upload-part layout,
        accepts the bytes, and finally requires completion through the
        authenticated account file endpoint.

        Args:
            local_path: File to upload.
            article_id: Target article.
            filename: Name to use upstream; defaults to the local name.

        Returns:
            The upstream metadata for the announced file.

        Raises:
            FileNotFoundError: If *local_path* does not exist.
            SourceError: If *local_path* is not a regular file or Figshare does
                not return a usable integer file id, filename, or upload URL,
                or the required file-completion request fails.
        """
        local_path = Path(local_path)
        if not local_path.exists():
            raise FileNotFoundError(f"File not found: {local_path}")
        if not local_path.is_file():
            raise SourceError(f"Figshare upload requires a regular file: {local_path}")

        size = int(local_path.stat().st_size)
        digest = hashlib.md5()
        with local_path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)

        announcement = self._session.post(
            f"{self._api_base}/account/articles/{article_id}/files",
            json={
                "name": filename or local_path.name,
                "size": size,
                "md5": digest.hexdigest(),
            },
        )
        announcement.raise_for_status()
        file_info = self._response_json(announcement)
        if "id" not in file_info:
            location = self._response_location(announcement)
            if location:
                detail = self._session.get(location)
                detail.raise_for_status()
                file_info = self._response_json(detail)

        file_id = file_info.get("id")
        if isinstance(file_id, bool) or not isinstance(file_id, int) or file_id <= 0:
            raise SourceError("Figshare did not return a usable integer file id.")
        upstream_name = file_info.get("name")
        if not isinstance(upstream_name, str) or not upstream_name:
            raise SourceError("Figshare did not return a usable uploaded filename.")

        upload_url = file_info.get("upload_url") or file_info.get("location")
        if not isinstance(upload_url, str) or not upload_url:
            raise SourceError("Figshare did not return a usable file upload URL.")
        layout = self._session.get(upload_url)
        layout.raise_for_status()
        parts = self._response_json(layout).get("parts", [])

        if not parts:
            with open(local_path, "rb") as handle:
                self._session.put(upload_url, data=handle.read()).raise_for_status()
        else:
            with open(local_path, "rb") as handle:
                for part in parts:
                    handle.seek(part["startOffset"])
                    chunk = handle.read(part["endOffset"] - part["startOffset"] + 1)
                    self._session.put(
                        f"{upload_url}/{part['partNo']}", data=chunk
                    ).raise_for_status()

        try:
            completion = self._session.post(
                f"{self._api_base}/account/articles/{article_id}/files/{file_id}"
            )
            completion.raise_for_status()
        except Exception as exc:
            raise SourceError("Figshare file completion failed.") from exc

        return file_info

    @staticmethod
    def _response_json(response: Any) -> dict[str, Any]:
        """Return an object-shaped response body, tolerating empty responses."""
        try:
            payload = response.json()
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _response_location(self, response: Any) -> str | None:
        """Return an absolute resource location from a header or JSON body."""
        headers = getattr(response, "headers", None)
        location = headers.get("Location") if headers is not None else None
        if not isinstance(location, str) or not location:
            location = self._response_json(response).get("location")
        if not isinstance(location, str) or not location:
            return None
        return urljoin(f"{self._api_base}/", location)

    @classmethod
    def _version_from_response(cls, response: Any) -> int | None:
        """Read and strictly validate an article version from a response."""
        payload = cls._response_json(response)
        if "version" not in payload:
            return None
        version = payload["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
            raise SourceError("Figshare returned an invalid article version.")
        return version

    # -- reading -------------------------------------------------------------

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        """Resolve a pinned article version, optionally narrowed to one filename.

        Raises:
            SourceError: If the article or version has no files, or the
                requested filename is absent from it.
        """
        article_id, version, wanted = self._split(locator.path)
        endpoint = (
            f"{self._api_base}/articles/{article_id}/versions/{version}"
            if version
            else f"{self._api_base}/articles/{article_id}/files"
        )
        payload = fetch_json(endpoint)
        entries = payload.get("files", []) if isinstance(payload, dict) else payload
        if not entries:
            where = f"article {article_id}" + (f" version {version}" if version else "")
            raise SourceError(f"Figshare {where} lists no files.")

        remotes = [self._to_remote(entry) for entry in entries]
        if not wanted:
            return remotes
        matched = [remote for remote in remotes if remote.filename == wanted]
        if not matched:
            available = ", ".join(sorted(remote.filename for remote in remotes))
            raise SourceError(
                f"Figshare article {article_id} has no file {wanted!r}. Available: {available}"
            )
        return matched

    @staticmethod
    def _split(path: str) -> tuple[str, str | None, str]:
        """Split ``<article>[/v<n>][/<filename>]`` into its three parts."""
        article_id, _, rest = path.partition("/")
        if rest.startswith("v") and rest[1:].split("/", 1)[0].isdigit():
            version, _, wanted = rest[1:].partition("/")
            return article_id, version, wanted
        return article_id, None, rest

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
