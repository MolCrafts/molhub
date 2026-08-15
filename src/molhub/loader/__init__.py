"""The HuggingFace-shaped front door: three functions, and the types behind them.

    from molhub import load_dataset, load_dataset_builder, prepare

    load_dataset_builder("themol/mbis").info      # what is in here?
    load_dataset("themol/mbis", split="train")    # give me one split of it
    load_dataset("themol/mbis", split="train", streaming=True)   # …a file at a time
    prepare("themol/torsion-scan", split="train", output_dir="blocks/")  # …as blocks

All three are thin delegations to :class:`~molhub.loader.builder.DatasetBuilder`;
every verb they appear to have is a method on a constructed type. They are the
**only** free functions this package sanctions, and the scope of that sanction is
written down in ``.claude/notes/notes.md`` (2026-08-15 operator override,
``mol:note:topic:hf-style-api``): the façade is the loader surface, and nothing
under ``sources/``, ``dataset/`` or ``conveyor/`` gains one. The two reading
functions are defined here; :func:`~molhub.loader.materialize.prepare` is defined
in :mod:`molhub.loader.materialize`, beside the :class:`BlockExport` it delegates
to, and re-exported here and from ``molhub`` — which is what
``tests/test_loader/test_layering.py`` binds.

**``streaming=True`` selects the walk, not a different dataset.** The same name
and the same split come back as a
:class:`~molhub.loader.streaming.StreamingSplitDataset`: an iterable dataset that
keeps one published file on disk at a time, with ``disk_budget`` bounding what
"one file at a time" is allowed to cost. Map-style access needs the whole split
addressable; a walk does not, which is the entire difference.

**Two refusals are exported beside them.**
:class:`~molhub.loader.errors.SplitTableUnavailable` (the published split
derivation has never been built on this machine — nothing downloads it) and
:class:`~molhub.loader.errors.UnknownSplit` (a name this dataset does not
declare, decided before anything is fetched) are both things a script
legitimately catches, so both are reachable from here and from ``molhub``
itself rather than only from the module that raises them.

**And so is the transport's own.**
:class:`~molhub.sources.errors.AllLocatorsFailed` is what opening a split raises
when every mirror of a published file is down: the one failure on this path that
is nobody's bug and that a script has a real reason to catch — to retry, to fall
back, to report. Reaching it means importing :mod:`molhub.sources.errors`, a
transport-layer module this façade exists to hide, so a caller who has only
``import molhub`` writes ``except Exception`` and swallows their own bugs with
it. It is re-exported unchanged: catching it here catches what the driver raised.

**``split`` is required.** Omitting it would have to return a dict of splits —
a new container type — or make ``ds[0]`` mean different things depending on an
argument nobody passed. Discovery is ``load_dataset_builder(name).info.splits``,
and there is deliberately no ``DatasetDict`` here to come back under. The refusal
is still a :class:`TypeError`, but it is molhub's sentence rather than Python's:
"missing 1 required keyword-only argument" says what is absent and nothing about
what to type next, and the names are one call away.

**Every type these docstrings promise is reachable from ``import molhub``.** A
``Raises:`` line is a promise a reader writes ``except`` against, and a type they
can only name by importing ``molhub.conveyor.prepare`` turns that promise into
``except Exception``. So the refusals and the records those functions hand back
are re-exported here and from the package root beside the functions themselves.

**``load_dataset`` is overloaded on ``streaming``.** One function returns two
genuinely different things — a map-style dataset and a walk — and a single
``Dataset | IterableDataset`` annotation would make ``ds[0]`` an editor error on
the path where indexing is the whole point. The :func:`typing.overload` stubs
below are a type-level statement only; the runtime is the one implementation
under them.

**The signatures read user-first.** ``registry=`` and ``hub=`` are seams a test
or an embedder injects and essentially no user call passes, so they sit last.
Everything is keyword-only, which makes that order documentation rather than an
ABI: moving them breaks nobody's call.

The loader sits **above** ``molhub.dataset`` and ``molhub.conveyor`` and reads
both; neither may read it back (``tests/test_loader/test_layering.py``).

Reference:
    ``.claude/specs/hf-facade-03-builder-info.md`` — Summary, D5 and ac-003.
"""

from __future__ import annotations

from typing import Literal, overload

from molhub.conveyor import DEFAULT_BUDGET_BYTES
from molhub.conveyor.errors import UnroutableUnitError, UnsupportedRecordError
from molhub.conveyor.prepare import PreparedBlocks
from molhub.conveyor.splits import SplitProvenanceMismatch
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.protocol import Dataset
from molhub.loader.builder import DatasetBuilder
from molhub.loader.errors import SplitTableUnavailable, UnknownSplit
from molhub.loader.info import ByteSize, DatasetInfo, Feature, SplitInfo
from molhub.loader.mapstyle import ShardIndex, SplitDataset, UnknownRecordKey
from molhub.loader.materialize import BlockExport, SplitRouting, prepare
from molhub.loader.naming import AmbiguousRevision, DatasetName
from molhub.loader.streaming import BoundedStream, PublishedParts, StreamingSplitDataset
from molhub.registry import Registry
from molhub.sources.errors import AllLocatorsFailed

__all__ = [
    "load_dataset",
    "load_dataset_builder",
    "prepare",
    "DatasetBuilder",
    "DatasetInfo",
    "SplitInfo",
    "Feature",
    "ByteSize",
    "DatasetName",
    "AmbiguousRevision",
    "SplitTableUnavailable",
    "UnknownSplit",
    "ShardIndex",
    "SplitDataset",
    "UnknownRecordKey",
    "StreamingSplitDataset",
    "BoundedStream",
    "PublishedParts",
    "BlockExport",
    "SplitRouting",
    "PreparedBlocks",
    "SplitProvenanceMismatch",
    "UnroutableUnitError",
    "UnsupportedRecordError",
    "AllLocatorsFailed",
]


class _MissingSplit:
    """The default of ``split=``, so its absence is molhub's to refuse.

    A sentinel rather than a required keyword-only argument: Python's own
    "missing 1 required keyword-only argument: 'split'" names what is absent and
    nothing about what to type next, and the call that lists the split names is
    the next thing the reader wants. The refusal stays a :class:`TypeError`.
    """


_MISSING_SPLIT = _MissingSplit()


@overload
def load_dataset(
    name: str,
    *,
    split: str,
    revision: str | None = ...,
    streaming: Literal[True],
    disk_budget: int = ...,
    registry: Registry | None = ...,
    hub: ArtifactHub | None = ...,
) -> StreamingSplitDataset: ...


@overload
def load_dataset(
    name: str,
    *,
    split: str,
    revision: str | None = ...,
    streaming: Literal[False] = ...,
    disk_budget: int = ...,
    registry: Registry | None = ...,
    hub: ArtifactHub | None = ...,
) -> Dataset: ...


def load_dataset(
    name: str,
    *,
    split: str | _MissingSplit = _MISSING_SPLIT,
    revision: str | None = None,
    streaming: bool = False,
    disk_budget: int = DEFAULT_BUDGET_BYTES,
    registry: Registry | None = None,
    hub: ArtifactHub | None = None,
) -> Dataset | StreamingSplitDataset:
    """Open one split of one dataset.

    Args:
        name: The dataset in HuggingFace spelling, e.g. ``"themol/mbis"``.
        split: Which split to open. Required, and keyword-only: this returns
            one dataset, never a container of them.
        revision: Which version to pin — molhub's ``@version``, not a git sha.
            ``None`` takes the newest the registry declares.
        streaming: Walk the split one published file at a time instead of
            addressing it map-style.
        disk_budget: How many bytes of fetched files a streaming walk may keep
            on local disk at once. Ignored when *streaming* is false, where
            residency is the cache's own business.
        registry: Where manifests come from; ``None`` uses the configured or
            bundled registry.
        hub: Where bytes come from; ``None`` constructs a
            :class:`~molhub.molhub.Molhub`.

    Returns:
        A map-style dataset satisfying
        :class:`~molhub.dataset.protocol.Dataset`, or — under *streaming* — a
        :class:`~molhub.loader.streaming.StreamingSplitDataset` satisfying
        :class:`~molhub.dataset.protocol.IterableDataset`. Either way the
        records are the :class:`molpy.Frame` / :class:`molpy.Trajectory` the
        dataset's own reader builds.

    Raises:
        TypeError: If *split* is omitted. There is no container of splits to
            return in its place; the message names the call that lists them.
        UnknownSplit: If *split* is not one of the dataset's declared splits.
            It is a ``KeyError``; the name is checked against the declaration
            before any byte is fetched.
        SplitTableUnavailable: If the dataset's splits come from a published
            derivation and this molhub has not built it. The message names the
            command that does.
        UnknownArtifact: If the registry has no such dataset or version.
        AmbiguousRevision: If no revision was given and the declared versions
            do not order.
        ValueError: If *streaming* is asked of a dataset published as whole
            files, which there is no way to walk a piece at a time, if the
            dataset's manifest publishes no checksum to verify a walked file
            against, or if the dataset's payload needs an offline conversion
            this machine has not run.
    """
    if isinstance(split, _MissingSplit):
        raise TypeError(
            "load_dataset() opens one split and needs to be told which: pass split=. "
            "Omitting it has no answer — there is no container of splits to hand back. "
            "The names are one call away: load_dataset_builder(name).info.splits."
        )
    builder = DatasetBuilder(name, revision=revision, registry=registry, hub=hub)
    if streaming:
        return builder.streaming_view(split, disk_budget=disk_budget)
    return builder.split_view(split)


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
