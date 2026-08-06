"""Transport layer — resolve a locator, fetch its bytes, verify their digest.

This package knows about bytes and nothing else: it does not parse content, does
not build :class:`molpy.Frame` objects, and does not understand molhub
coordinates. Datasets, models, and plugins are indistinguishable here.

Supporting a new hosting platform means implementing
:class:`~molhub.registry.driver.Registry` and registering it — no molhub source
file changes::

    from molhub.registry import Drivers, Fetcher, Digest

    fetcher = Fetcher(drivers=Drivers.discover().with_driver(MyRegistry()))
    path = fetcher.fetch(
        ["zenodo://14980914/data.csv", "https://mirror.example.org/data.csv"],
        Digest.sha256("…"),
    )
"""

from molhub.registry.blobs import BlobStore
from molhub.registry.digest import Digest, Sha256Stream
from molhub.registry.driver import PublishingRegistry, Registry
from molhub.registry.drivers import (
    Drivers,
    FigshareRegistry,
    HttpsRegistry,
    HuggingFaceRegistry,
    MolHubRegistry,
    ZenodoRegistry,
)
from molhub.registry.errors import (
    AllLocatorsFailed,
    BadStatus,
    DigestMismatch,
    InvalidDigest,
    InvalidLocator,
    RegistryError,
    UnknownScheme,
)
from molhub.registry.fetcher import Fetcher
from molhub.registry.locator import Locator
from molhub.registry.publication import Publication
from molhub.registry.remote import RemoteFile

__all__ = [
    "Locator",
    "Digest",
    "Sha256Stream",
    "RemoteFile",
    "Registry",
    "PublishingRegistry",
    "Publication",
    "Drivers",
    "BlobStore",
    "Fetcher",
    "HttpsRegistry",
    "ZenodoRegistry",
    "FigshareRegistry",
    "HuggingFaceRegistry",
    "MolHubRegistry",
    "RegistryError",
    "InvalidLocator",
    "InvalidDigest",
    "UnknownScheme",
    "BadStatus",
    "DigestMismatch",
    "AllLocatorsFailed",
]
