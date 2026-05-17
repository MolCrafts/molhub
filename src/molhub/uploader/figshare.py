"""Upload files and datasets to Figshare.

Uses the Figshare REST API (https://docs.figshare.com).  Requires a
Figshare personal access token.  Install with
``pip install molhub[figshare]`` or ``pip install requests``.

Usage::

    from molhub.uploader import FigshareUploader

    uploader = FigshareUploader(token="...")
    uploader.upload_file(
        local_path="data/qm9.tar.bz2",
        title="QM9 dataset tarball",
        description="Raw QM9 molecular property dataset",
    )
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class FigshareUploader:
    """Upload files and create items on Figshare.

    Args:
        token: Figshare personal access token (or set ``FIGSHARE_TOKEN`` env var).
        base_url: API base URL (defaults to the public Figshare API).
    """

    BASE_URL = "https://api.figshare.com/v2"

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
    ) -> None:
        import requests

        self._requests = requests
        token = token or os.environ.get("FIGSHARE_TOKEN")
        if not token:
            raise ValueError(
                "Figshare token required. Pass token= or set FIGSHARE_TOKEN env var."
            )
        self._token = token
        self._base_url = base_url or self.BASE_URL
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"token {self._token}",
                "Accept": "application/json",
            }
        )

    # -- public API ----------------------------------------------------------

    def create_article(
        self,
        title: str,
        *,
        description: str = "",
        category: str | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Create a new Figshare article (item).

        Args:
            title: Article title.
            description: Optional description.
            category: Optional category id or name.
            tags: Optional list of tags.
            **kwargs: Additional article metadata.

        Returns:
            The created article dict (includes ``id`` field for the article).
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

        resp = self._session.post(
            f"{self._base_url}/account/articles",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    def upload_file(
        self,
        local_path: str | Path,
        article_id: int,
        *,
        filename: str | None = None,
    ) -> dict:
        """Upload a file to an existing Figshare article.

        Args:
            local_path: Path to the local file.
            article_id: Figshare article id (from :meth:`create_article`).
            filename: Optional override for the filename in Figshare.

        Returns:
            The uploaded file metadata dict.
        """
        local_path = Path(local_path)
        if not local_path.exists():
            raise FileNotFoundError(f"File not found: {local_path}")

        actual_name = filename or local_path.name
        file_size = local_path.stat().st_size

        # Step 1: Initiate upload
        init_payload = {
            "name": actual_name,
            "size": int(file_size),
        }
        resp = self._session.post(
            f"{self._base_url}/account/articles/{article_id}/files",
            json=init_payload,
        )
        resp.raise_for_status()
        file_info = resp.json()

        # Step 2: Get upload URL and parts info
        upload_url = file_info.get("upload_url") or file_info["location"]
        upload_result = self._session.get(upload_url)
        upload_result.raise_for_status()
        parts_info = upload_result.json()

        parts = parts_info.get("parts", [])
        if not parts:
            # Single-part upload
            with open(local_path, "rb") as f:
                self._session.put(upload_url, data=f.read()).raise_for_status()
        else:
            # Multi-part upload
            parts_data = []
            with open(local_path, "rb") as f:
                for part in parts:
                    part_data = f.read(part["endOffset"] - part["startOffset"] + 1)
                    part_url = f"{upload_url}/{part['partNo']}"
                    self._session.put(part_url, data=part_data).raise_for_status()
                    parts_data.append({"partNo": part["partNo"], "etag": "uploaded"})

            # Complete the multi-part upload
            self._session.post(
                f"{upload_url}",
                json={"parts": parts_data},
            ).raise_for_status()

        return file_info

    def upload_dataset(
        self,
        local_path: str | Path,
        title: str,
        *,
        description: str = "",
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Create an article and upload a file in one step.

        Args:
            local_path: Path to the local file.
            title: Article title.
            description: Optional description.
            category: Optional category id.
            tags: Optional list of tags.

        Returns:
            Dict with ``article`` and ``file`` entries.
        """
        article = self.create_article(
            title=title,
            description=description,
            category=category,
            tags=tags,
        )
        article_id = article["id"]
        file_info = self.upload_file(local_path, article_id)
        return {"article": article, "file": file_info}
