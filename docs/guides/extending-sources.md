# Extending sources

A source owns one locator scheme and moves bytes under the transport contract. This complete example
uses an in-memory source and a temporary cache, so the documentation test runs without network access.

<!-- test: exec -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory

from molhub.sources import BlobStore, Drivers, Fetcher, Locator, RemoteFile


class MemorySource:
    scheme = "memory"

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        return [RemoteFile(url=str(locator), filename="sample.xyz", size=4)]

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        assert remote.url == "memory://sample"
        dest.write_bytes(b"data")
        return dest


with TemporaryDirectory() as directory:
    fetcher = Fetcher(
        drivers=Drivers.of(MemorySource()),
        blobs=BlobStore(directory),
    )
    path = fetcher.fetch(["memory://sample"], "dataset/lab/sample@v1/main")
    assert path.read_bytes() == b"data"
```

An installed extension publishes the class through the `molhub.sources` entry-point group. Then
`Drivers.discover()` loads it without a MolHub source change.
