"""MolHub — name an artifact, fetch its bytes, or construct its type.

Primitive (a dataset is a class)::

    from molhub.dataset import QM9

    ds = QM9().load()
    frames = ds[0]                # Sequence[Frame]

Package verbs, distinguished only by the name you pass::

    import molhub as mh

    mh.search(query="themol")
    mh.fetch("qm9")
    mh.load("themol/mbis")
    mh.artifacts("qm9")
    mh.snapshot()

``load`` / ``fetch`` / ``search`` do not care whether the name is a
dataset, a model, or a plugin — the coordinate does. There is no
``load_dataset`` factory.

Splitting is :class:`~molhub.dataset.protocol.SubsetDataset`, like PyTorch.
"""

from pathlib import Path

from molhub._version import __version__
from molhub.coordinate import InvalidCoordinate
from molhub.dataset.definition import UnknownDataset
from molhub.dataset.protocol import SubsetDataset, assignment
from molhub.loader import (
    AllLocatorsFailed,
    AmbiguousRevision,
    SplitProvenanceMismatch,
    SplitTableUnavailable,
    UnknownRecordKey,
    UnknownSplit,
    UnroutableUnitError,
    UnsupportedRecordError,
    load,
    prepare,
)
from molhub.manifest import Artifact, Manifest
from molhub.molhub import Molhub
from molhub.registry import Registry, UnknownArtifact

__all__ = [
    "__version__",
    "load",
    "fetch",
    "search",
    "artifacts",
    "snapshot",
    "assignment",
    "SubsetDataset",
    "prepare",
    "Molhub",
    "UnknownDataset",
    "AllLocatorsFailed",
    "AmbiguousRevision",
    "SplitProvenanceMismatch",
    "SplitTableUnavailable",
    "UnknownRecordKey",
    "UnknownSplit",
    "UnroutableUnitError",
    "UnsupportedRecordError",
    "InvalidCoordinate",
    "UnknownArtifact",
    "Artifact",
    "Manifest",
    "Registry",
]


def fetch(
    name: str, *, roles: list[str] | None = None, registry: Registry | None = None
) -> dict[str, Path]:
    """Retrieve an artifact's files by name. Same verb for dataset, model, plugin."""
    return Molhub(registry).fetch(name, roles=roles)


def search(
    *,
    kind: str | None = None,
    query: str | None = None,
    registry: Registry | None = None,
) -> list[Manifest]:
    """Search the registry by substring. Kind is optional, not a second verb."""
    return Molhub(registry).search(kind=kind, query=query)


def artifacts(name: str | None = None) -> dict[str, Artifact] | dict[str, dict[str, Artifact]]:
    """Declared downloadable files from the Python catalog.

    The frontend and any other client that needs the file list calls this
    (or :func:`snapshot`) — there is no project YAML to read.

    Args:
        name: Coordinate or shorthand. ``None`` returns every catalog
            coordinate mapped to its artifacts.
    """
    registry = Registry.builtin()
    if name is None:
        return {
            manifest.coordinate.canonical: dict(manifest.artifacts)
            for manifest in registry.search()
        }
    return dict(registry.get(name).artifacts)


def snapshot() -> dict[str, object]:
    """Aggregate registry document for the Web build and other non-Python clients."""
    return Registry.builtin().snapshot()
