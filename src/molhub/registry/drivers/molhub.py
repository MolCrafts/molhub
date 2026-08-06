"""MolCrafts' own small registry — static object storage behind a CDN.

Used for MolCrafts plugins and anything else the project hosts itself. It gets
**no special treatment**: it implements the same
:class:`~molhub.registry.driver.Registry` protocol as every third-party remote,
and :class:`~molhub.registry.fetcher.Fetcher` has no branch for it. If this
driver ever needed a back door, the protocol would be wrong.

Locator form::

    molhub://plugins/molvis-render/0.3.1.zip
"""

from __future__ import annotations

import os
from pathlib import Path

from molhub.registry.drivers.https import HttpsRegistry
from molhub.registry.locator import Locator
from molhub.registry.remote import RemoteFile

__all__ = ["MolHubRegistry"]

_DEFAULT_BASE = "https://hub.molcrafts.org"
_ENV_VAR = "MOLHUB_REGISTRY_BASE"


class MolHubRegistry:
    """Resolves MolCrafts-hosted paths against a static base URL.

    Args:
        base_url: Storage root. Defaults to ``$MOLHUB_REGISTRY_BASE``, then the
            public CDN. Pointing it at a local directory server is how the
            tests exercise it without network.
        transfer: Object performing the byte transfer.
    """

    scheme = "molhub"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        transfer: HttpsRegistry | None = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get(_ENV_VAR) or _DEFAULT_BASE).rstrip("/")
        self._transfer = transfer or HttpsRegistry()

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        """Join the locator path onto the storage base."""
        url = f"{self._base_url}/{locator.path.lstrip('/')}"
        return [RemoteFile(url=url, filename=locator.path.rsplit("/", 1)[-1])]

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        """Delegate the transfer, which is plain HTTPS."""
        return self._transfer.fetch(remote, dest)
