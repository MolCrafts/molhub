"""Transport layer — resolve a locator, fetch its bytes, file them on disk.

Correctness here rests on the transfer contract: check the response status,
stream to a temporary file, rename it into place only once the transfer
completed. That is what stops a 202, a truncated body, or an error page from
ever appearing at the final path. When the caller supplies a digest — the one
the publishing platform declared, if it declared any — the bytes are checked
against it as a secondary cross-check.

This package knows about bytes and nothing else: it does not parse content, does
not build :class:`molpy.Frame` objects, and does not understand molhub
coordinates. Datasets, models, and plugins are indistinguishable here.

Supporting a new hosting platform means implementing
:class:`~molhub.sources.source.Source` and registering it — no molhub source
file changes::

    from molhub.sources import Digest, Drivers, Fetcher

    fetcher = Fetcher(drivers=Drivers.discover().with_driver(MySource()))
    path = fetcher.fetch(
        ["zenodo://14980914/data.csv", "https://mirror.example.org/data.csv"],
        "dataset/molcrafts/polymer-tg@1/main",
        digest=Digest.parse("md5:ce2c7b2a879450cbbfff4d7ccea648f9"),
    )

The second argument is the cache key: where the bytes are filed once they
arrive. ``digest`` is optional — omit it when the platform publishes nothing.
"""

from molhub.sources.blobs import BlobStore
from molhub.sources.digest import Digest, Sha256Stream
from molhub.sources.drivers import (
    Drivers,
    FigshareSource,
    HttpsSource,
    HuggingFaceSource,
    MolHubSource,
    ZenodoSource,
)
from molhub.sources.errors import (
    AllLocatorsFailed,
    BadStatus,
    DigestMismatch,
    InvalidDigest,
    InvalidLocator,
    SourceError,
    UnknownScheme,
)
from molhub.sources.fetcher import Fetcher
from molhub.sources.locator import Locator
from molhub.sources.publication import Publication
from molhub.sources.remote import RemoteFile
from molhub.sources.source import FileTransfer, PublishingSource, Source

__all__ = [
    "Locator",
    "Digest",
    "Sha256Stream",
    "RemoteFile",
    "FileTransfer",
    "Source",
    "PublishingSource",
    "Publication",
    "Drivers",
    "BlobStore",
    "Fetcher",
    "HttpsSource",
    "ZenodoSource",
    "FigshareSource",
    "HuggingFaceSource",
    "MolHubSource",
    "SourceError",
    "InvalidLocator",
    "InvalidDigest",
    "UnknownScheme",
    "BadStatus",
    "DigestMismatch",
    "AllLocatorsFailed",
]
