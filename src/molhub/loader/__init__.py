"""The HuggingFace-shaped front door: two functions, and the types behind them.

    from molhub import load_dataset, load_dataset_builder

    load_dataset_builder("themol/mbis").info      # what is in here?
    load_dataset("themol/mbis", split="train")    # give me one split of it

Both are thin delegations to :class:`~molhub.loader.builder.DatasetBuilder`;
every verb they appear to have is a method on a constructed type. They are the
**only** free functions this distribution sanctions, they live only here, and
the scope of that sanction is written down in ``.claude/notes/notes.md``
(2026-08-15 operator override, ``mol:note:topic:hf-style-api``): the façade is
the loader surface, and nothing under ``sources/``, ``dataset/`` or
``conveyor/`` gains one.

**``split`` is required.** Omitting it would have to return a dict of splits —
a new container type — or make ``ds[0]`` mean different things depending on an
argument nobody passed. Discovery is ``load_dataset_builder(name).info.splits``,
and there is deliberately no ``DatasetDict`` here to come back under.

The loader sits **above** ``molhub.dataset`` and ``molhub.conveyor`` and reads
both; neither may read it back (``tests/test_loader/test_layering.py``).

Reference:
    ``.claude/specs/hf-facade-03-builder-info.md`` — Summary, D5 and ac-003.
"""

from __future__ import annotations

from molhub.dataset.hub import ArtifactHub
from molhub.dataset.protocol import Dataset
from molhub.loader.builder import DatasetBuilder
from molhub.loader.info import DatasetInfo, Feature, SplitInfo
from molhub.loader.mapstyle import ShardIndex, SplitDataset, UnknownRecordKey
from molhub.loader.naming import AmbiguousRevision, DatasetName
from molhub.registry import Registry

__all__ = [
    "load_dataset",
    "load_dataset_builder",
    "DatasetBuilder",
    "DatasetInfo",
    "SplitInfo",
    "Feature",
    "DatasetName",
    "AmbiguousRevision",
    "ShardIndex",
    "SplitDataset",
    "UnknownRecordKey",
]


def load_dataset(
    name: str,
    *,
    split: str,
    revision: str | None = None,
    registry: Registry | None = None,
    hub: ArtifactHub | None = None,
) -> Dataset:
    """Open one split of one dataset.

    Args:
        name: The dataset in HuggingFace spelling, e.g. ``"themol/mbis"``.
        split: Which split to open. Required, and keyword-only: this returns
            one dataset, never a container of them.
        revision: Which version to pin — molhub's ``@version``, not a git sha.
            ``None`` takes the newest the registry declares.
        registry: Where manifests come from; ``None`` uses the configured or
            bundled registry.
        hub: Where bytes come from; ``None`` constructs a
            :class:`~molhub.molhub.Molhub`.

    Returns:
        A map-style dataset satisfying
        :class:`~molhub.dataset.protocol.Dataset`, whose records are the
        :class:`molpy.Frame` / :class:`molpy.Trajectory` the dataset's own
        reader builds.

    Raises:
        KeyError: If *split* is not one of the dataset's declared splits.
        UnknownArtifact: If the registry has no such dataset or version.
        AmbiguousRevision: If no revision was given and the declared versions
            do not order.
    """
    return DatasetBuilder(name, revision=revision, registry=registry, hub=hub).split_view(split)


def load_dataset_builder(
    name: str,
    *,
    revision: str | None = None,
    registry: Registry | None = None,
    hub: ArtifactHub | None = None,
) -> DatasetBuilder:
    """Describe a dataset without opening a split of it.

    Args:
        name: The dataset in HuggingFace spelling.
        revision: Which version to pin; ``None`` takes the newest declared.
        registry: Where manifests come from.
        hub: Where bytes come from, when a split is eventually opened.

    Returns:
        The :class:`~molhub.loader.builder.DatasetBuilder`, whose ``.info``
        reports content — features, splits, counts, citation — and never a
        shard role.
    """
    return DatasetBuilder(name, revision=revision, registry=registry, hub=hub)
