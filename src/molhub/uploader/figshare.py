"""Compatibility shim for the pre-registry Figshare uploader.

The implementation now lives in
:class:`molhub.registry.drivers.figshare.FigshareRegistry`, where uploading is
the write half of the same driver that resolves and fetches. This class stays
so existing callers keep working; prefer the driver directly::

    from molhub.registry import Drivers, Publication

    figshare = Drivers.discover().for_scheme("figshare")
    locator = figshare.publish([Path("data.csv")], "new", Publication(title="…"))

Scheduled for removal two minor releases after 0.1.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from molhub.registry.drivers.figshare import FigshareRegistry

__all__ = ["FigshareUploader"]


class FigshareUploader:
    """Create Figshare articles and upload files to them.

    Args:
        token: Figshare personal access token (or set ``FIGSHARE_TOKEN``).
        base_url: API base URL.

    Raises:
        ValueError: If no token is available. The driver defers this until a
            publish is attempted; this shim keeps the original eager check.
    """

    BASE_URL = "https://api.figshare.com/v2"

    def __init__(self, token: str | None = None, base_url: str | None = None) -> None:
        token = token or os.environ.get("FIGSHARE_TOKEN")
        if not token:
            raise ValueError("Figshare token required. Pass token= or set FIGSHARE_TOKEN env var.")
        self._token = token
        self._base_url = base_url or self.BASE_URL
        self._registry = FigshareRegistry(api_base=self._base_url, token=token)

    @property
    def _session(self) -> Any:
        """The driver's authenticated session, exposed for backwards compatibility."""
        return self._registry._session

    def create_article(
        self,
        title: str,
        *,
        description: str = "",
        category: str | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Create a new Figshare article (item)."""
        return self._registry.create_article(
            title, description=description, category=category, tags=tags, **kwargs
        )

    def upload_file(
        self,
        local_path: str | Path,
        article_id: int,
        *,
        filename: str | None = None,
    ) -> dict:
        """Upload a file to an existing Figshare article."""
        return self._registry.upload_file(local_path, article_id, filename=filename)

    def upload_dataset(
        self,
        local_path: str | Path,
        title: str,
        *,
        description: str = "",
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Create an article and upload a file in one step."""
        article = self.create_article(
            title=title, description=description, category=category, tags=tags
        )
        file_info = self.upload_file(local_path, article["id"])
        return {"article": article, "file": file_info}
