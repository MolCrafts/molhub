"""Name-based open: ``load``. The primitive is the dataset class.

    from molhub.dataset import QM9
    from molhub import load, SubsetDataset, assignment

    ds = QM9().load()
    themol = load("themol/mbis")
    train = SubsetDataset(themol, assignment(themol)["train"])

``@dataset(...) class FooDataset`` is the definition. ``MANIFEST`` on the
same module says where the bytes live. ``prepare`` writes a molnex block
directory from a dataset you already opened.

The loader sits above ``molhub.dataset`` and ``molhub.conveyor`` and reads
both; neither may read it back (``tests/test_loader/test_layering.py``).
"""

from __future__ import annotations

from typing import Literal, overload

from molhub.conveyor import DEFAULT_BUDGET_BYTES
from molhub.conveyor.errors import UnroutableUnitError, UnsupportedRecordError
from molhub.conveyor.splits import SplitProvenanceMismatch
from molhub.dataset.definition import UnknownDataset
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.protocol import Dataset, SubsetDataset, assignment
from molhub.loader.builder import DatasetBuilder
from molhub.loader.errors import SplitTableUnavailable, UnknownSplit
from molhub.loader.mapstyle import UnknownRecordKey
from molhub.loader.materialize import prepare
from molhub.loader.naming import AmbiguousRevision
from molhub.loader.streaming import StreamingSplitDataset
from molhub.registry import Registry
from molhub.sources.errors import AllLocatorsFailed

__all__ = [
    "load",
    "assignment",
    "prepare",
    "SubsetDataset",
    "UnknownDataset",
    "AmbiguousRevision",
    "SplitTableUnavailable",
    "UnknownSplit",
    "UnknownRecordKey",
    "SplitProvenanceMismatch",
    "UnroutableUnitError",
    "UnsupportedRecordError",
    "AllLocatorsFailed",
]


@overload
def load(
    name: str,
    *,
    revision: str | None = ...,
    streaming: Literal[True],
    disk_budget: int = ...,
    registry: Registry | None = ...,
    hub: ArtifactHub | None = ...,
) -> StreamingSplitDataset: ...


@overload
def load(
    name: str,
    *,
    revision: str | None = ...,
    streaming: Literal[False] = ...,
    disk_budget: int = ...,
    registry: Registry | None = ...,
    hub: ArtifactHub | None = ...,
) -> Dataset: ...


def load(
    name: str,
    *,
    revision: str | None = None,
    streaming: bool = False,
    disk_budget: int = DEFAULT_BUDGET_BYTES,
    registry: Registry | None = None,
    hub: ArtifactHub | None = None,
) -> Dataset | StreamingSplitDataset:
    """Open a named artifact as records. The whole thing, not one split.

    Args:
        name: HuggingFace spelling, e.g. ``"themol/mbis"``.
        revision: molhub ``@version``. ``None`` takes the newest declared.
        streaming: Walk published files one at a time instead of indexing.
        disk_budget: Bytes of fetched files a walk may keep on disk at once.
        registry: Where registry YAML comes from.
        hub: Where bytes come from.

    Returns:
        A map-style :class:`~molhub.dataset.protocol.Dataset`, or a walk
        under *streaming*. Records are ``Sequence[Frame]``.

    Raises:
        UnknownDataset: If this molhub has no reader for *name*.
        UnknownArtifact: If the registry has no such dataset or version.
        AmbiguousRevision: If versions do not order and *revision* is omitted.
        ValueError: If *streaming* is asked of a whole-file dataset, or the
            payload needs a conversion this machine has not run.
    """
    builder = DatasetBuilder(name, revision=revision, registry=registry, hub=hub)
    if streaming:
        return builder.streaming_view(disk_budget=disk_budget)
    return builder.dataset()
