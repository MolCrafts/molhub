"""Describe a dataset first, fetch it second — the ``load_dataset_builder`` half.

:class:`DatasetBuilder` resolves a name to one pinned coordinate, reads the
registry manifest and the dataset class's own declarations, and answers two
questions: :attr:`~DatasetBuilder.info` (what is in here?) and
:meth:`~DatasetBuilder.split_view` (give me one split of it). Nothing else. The
composition — *describe, then decide, then read* — stays the caller's.

**Two split flavours, one ``DatasetInfo.splits``.** D6 of the spec:

* *table-backed* (THEMol): the split assignment is a published derivation,
  ``class1-universal-splits@1``. Counts come from one gzipped CSV under
  ``$MOLHUB_HOME/derived/``, memoized per process, and cost **zero shard
  bytes** — which is what makes ``.info`` usable on an artifact of tens of GiB
  to several TiB.
* *declared* (zinc-typing, phalkethoh-mm, 3BPA): the dataset class already owns
  its splits, so the builder delegates to its constructor. The constructors do
  not agree on a spelling — two take ``split=``, 3BPA takes ``tag=`` with a
  required positional path — so each gets its own small adapter below rather
  than a uniform ``Ctor(split=split)`` dispatch that would be wrong for one of
  them.

**What the declared flavour costs, said out loud.** Its counts are exact
because they come from the dataset itself — which means constructing it, which
means its bytes. ``load_dataset_builder(...).info`` is therefore free only for
the table-backed datasets; for a declared-split one it costs what
``load_dataset`` costs. That is the price of a dataset whose splits nobody
published a table for, and it is charged here rather than hidden — and stated
in advance by :attr:`DatasetBuilder.describe_download_size`, which is what
``molhub info`` warns with before it spends the bytes.

**A name is checked before anything is read** (reachability wave, ruling 4).
Which names exist is a *declaration*: a class attribute for the declared
flavour, the derivation's own counts for the table-backed one. So
:meth:`SplitDeclaration.require_split` answers it without constructing a split,
and only the requested split is ever built — asking for a typo cannot download
four benchmark files first, and opening one split cannot download the other
three.

**Three ways to open the same split** (``hf-facade-04-streaming-prepare``):
:meth:`~DatasetBuilder.split_view` reads it map-style,
:meth:`~DatasetBuilder.streaming_view` walks it under a byte budget, and
:meth:`~DatasetBuilder.block_export` materialises it as molnex blocks. Each is
one named step and the composition stays the caller's. The last two need the
dataset to be *published in parts*, which only the table-backed flavour is — a
dataset delivered as whole files refuses them by name rather than pretending to
stream a single download.

Reference:
    ``.claude/specs/hf-facade-03-builder-info.md`` § Design (D5, D6) and
    ac-001/ac-002/ac-003; ``.claude/specs/hf-facade-04-streaming-prepare.md``
    § Design (D7, D8) — both under the 2026-08-15 operator override recorded in
    ``.claude/notes/notes.md`` (``mol:note:topic:hf-style-api``).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, get_args

from molhub.conveyor import DEFAULT_BUDGET_BYTES, default_ledger_path
from molhub.conveyor.ledger import Ledger
from molhub.conveyor.prepare import BlockWriterFactory
from molhub.conveyor.splits import _SplitTable
from molhub.conveyor.tier import DerivedLayout
from molhub.conveyor.transfer import ShardTransfer
from molhub.coordinate import Coordinate
from molhub.dataset.definition import DatasetManifest
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.phalkethoh_mm import PhalkethohMMDataset
from molhub.dataset.protocol import Dataset, TargetSchema
from molhub.dataset.themol import (
    THEMolHessian,
    THEMolMBIS,
    THEMolTorsionScan,
)
from molhub.dataset.threebpa import ThreeBPADataset
from molhub.dataset.zinc_typing import ZincTypingDataset
from molhub.loader.errors import SplitTableUnavailable, UnknownSplit
from molhub.loader.info import DatasetInfo, Feature, SplitInfo
from molhub.loader.mapstyle import ShardIndex, SplitDataset
from molhub.loader.materialize import BlockExport, SplitRouting
from molhub.loader.naming import DatasetName
from molhub.loader.streaming import PublishedParts, StreamingSplitDataset
from molhub.manifest import Manifest
from molhub.molhub import Molhub
from molhub.registry import Registry
from molhub.sources.blobs import BlobStore

__all__ = [
    "SplitDeclaration",
    "TableBackedSplits",
    "DeclaredSplits",
    "UnconvertedPayload",
    "ZincTypingSplits",
    "PhalkethohSplits",
    "ThreeBPASplits",
    "DatasetBuilder",
]

# A published shard, as the manifests spell it and the roster matches it.
_SHARD_ROLE = re.compile(r"shard-\d+")

# Where derived artifacts live under a molhub home, and the one derivation that
# states THEMol's split assignment.
_DERIVED_SUBDIR = "derived"
_SPLIT_DERIVATION = Coordinate.parse("dataset:molcrafts/class1-universal-splits@1")

# What a derivation's own record is called, mirrored from
# `molhub.conveyor.tier.DerivedLayout` exactly as `molhub.conveyor.splits`
# mirrors the producer's filename table: its absence is how "never built here"
# is told apart from "built, and its bytes moved".
_DERIVATION_RECORD = "metadata.json"

# The generator that writes that derivation, and the command a reader types.
# Mirrored from `molhub.scripts.build_class1_splits` rather than imported: this
# layer refuses without it, so importing it would drag a script's argument
# parsing into every reader of a split.
_SPLIT_GENERATOR = "molhub.scripts.build_class1_splits"
_SPLIT_TABLE_COMMAND = f"python -m {_SPLIT_GENERATOR}"

# What that command reads: one index file per THEMol subset. The table cannot be
# rebuilt without all three, which is what makes the rebuild expensive and what
# a "run the generator" message has to say out loud.
_SPLIT_TABLE_INPUTS: tuple[str, ...] = ("hessian", "mbis", "torsion-scan")

# What a record is when the dataset class does not parameterize it: molhub's
# ``Sample``, spelled as `molhub.dataset.protocol` spells it.
_SAMPLE_RECORD_TYPE = "Frame | Trajectory"

# The THEMol definitions whose splits the derivation states. `hessian-relax` and
# `torsion-relax` are deliberately absent: the derivation publishes no table for
# them, and mapping them onto a sibling's table would be inventing an answer.
_THEMolShardDefinition = type[THEMolHessian] | type[THEMolMBIS] | type[THEMolTorsionScan]


class SplitDeclaration(ABC):
    """Where one dataset's splits come from, and how one of them is opened.

    Two implementations, one per D6 flavour. Each entry of
    :data:`DatasetBuilder.DECLARATIONS` is one of them, so the builder never
    branches on which dataset it is holding.
    """

    #: The declared split names, for the flavour whose class states them
    #: statically. The table-backed flavour reads its names off the derivation
    #: instead and overrides :meth:`splits`.
    NAMES: ClassVar[tuple[str, ...]] = ()

    #: The sentence :attr:`SplitInfo.provenance` carries for this dataset.
    PROVENANCE: ClassVar[str] = ""

    @property
    @abstractmethod
    def definition(self) -> type:
        """The dataset class this entry delegates to.

        Read for its ``TARGET_SCHEMA`` and its
        :class:`~molhub.dataset.definition.DatasetManifest`; never called
        through this reference, because each flavour knows its own constructor
        and calls it by name.
        """

    @abstractmethod
    def view(self, split: str, *, manifest: Manifest, hub: ArtifactHub, home: Path) -> Dataset:
        """Open one split of this dataset.

        Args:
            split: One of the declared split names.
            manifest: The registry manifest of the resolved coordinate.
            hub: Where bytes come from.
            home: The molhub home, for anything filed under it.

        Returns:
            A map-style dataset over that split's records.
        """

    def require_split(self, split: str, *, manifest: Manifest, home: Path) -> None:
        """Refuse a name this dataset does not declare, before anything is read.

        The declared flavour states its names as a class attribute, so deciding
        this costs nothing at all — which is the point: a typo must not download
        four published files to discover it was a typo.

        Args:
            split: The name the caller asked for.
            manifest: The registry manifest of the resolved coordinate, for the
                message.
            home: The molhub home; unused here, and where the table-backed
                override reads its names from.

        Raises:
            UnknownSplit: If *split* is not one of :attr:`NAMES`.
        """
        if split not in self.NAMES:
            raise UnknownSplit(
                f"{manifest.coordinate.canonical} declares splits {list(self.NAMES)}, "
                f"not {split!r}."
            )

    def describe_download_size(self, manifest: Manifest) -> int:
        """How many bytes describing this dataset downloads before it can answer.

        Args:
            manifest: The registry manifest of the resolved coordinate.

        Returns:
            ``0`` — describing is free unless counting the splits means reading
            them, which is the declared flavour's own answer.
        """
        return 0

    def splits(self, *, manifest: Manifest, hub: ArtifactHub, home: Path) -> tuple[SplitInfo, ...]:
        """Every declared split, with its exact count and its provenance.

        The declared flavour's rule: the count is the dataset's own ``len``,
        which is exact and which materializes the split. See this module's
        docstring for why that cost is accepted rather than approximated.
        """
        return tuple(
            SplitInfo(
                name=name,
                num_examples=len(self.view(name, manifest=manifest, hub=hub, home=home)),
                provenance=self.PROVENANCE,
            )
            for name in self.NAMES
        )

    def streaming_view(
        self,
        split: str,
        *,
        manifest: Manifest,
        hub: ArtifactHub,
        home: Path,
        disk_budget: int,
    ) -> StreamingSplitDataset:
        """Walk one split of this dataset under a byte budget.

        Args:
            split: One of the declared split names.
            manifest: The registry manifest of the resolved coordinate.
            hub: Where bytes come from.
            home: The molhub home, for the split derivation and the bookkeeping.
            disk_budget: How many bytes of fetched files may sit on disk at once.

        Returns:
            The walk.

        Raises:
            ValueError: For a dataset published as whole files rather than in
                parts, which is the default here — only the table-backed
                flavour overrides it.
        """
        raise ValueError(self._whole_file_refusal(manifest))

    def block_export(
        self,
        split: str,
        *,
        manifest: Manifest,
        hub: ArtifactHub,
        home: Path,
        output_dir: str | Path,
        disk_budget: int,
        writer_factory: BlockWriterFactory | None = None,
        provenance: Mapping[str, object] | None = None,
    ) -> BlockExport:
        """Materialize one split of this dataset as molnex blocks.

        Args:
            split: One of the declared split names.
            manifest: The registry manifest of the resolved coordinate.
            hub: Where bytes come from.
            home: The molhub home, for the split derivation and the bookkeeping.
            output_dir: Directory the sealed block roots are created under.
            disk_budget: How many bytes of fetched files may sit on disk at once.
            writer_factory: How one block is opened; ``None`` resolves molnex's.
            provenance: Opaque provenance; ``None`` states the export's own.

        Returns:
            The export, ready to run.

        Raises:
            ValueError: For a dataset published as whole files rather than in
                parts.
        """
        raise ValueError(self._whole_file_refusal(manifest))

    @staticmethod
    def _whole_file_refusal(manifest: Manifest) -> str:
        """Why a dataset delivered whole is neither walked nor exported in parts."""
        return (
            f"{manifest.coordinate.canonical} is published as whole files rather than in "
            "parts, so there is nothing to read a piece at a time and nothing to "
            "materialize piece by piece. Open it with load_dataset(name, split=...)."
        )


class TableBackedSplits(SplitDeclaration):
    """A dataset whose splits a published derivation states, not its class.

    The table is loaded once per process per derivation directory: it runs to
    ≈1.5 M rows for THEMol MBIS, every caller of one dataset wants the same
    rows, and reading it twice would double the only cost ``.info`` has.

    Args:
        definition: The THEMol dataset class whose shards hold these records.
        source: Which of the derivation's per-source tables states them —
            ``hessian``, ``mbis`` or ``torsion-scan``.
    """

    def __init__(self, definition: _THEMolShardDefinition, *, source: str) -> None:
        self._definition = definition
        self._source = source
        self._tables: dict[Path, _SplitTable] = {}
        self._identities: dict[Path, _SplitTable] = {}

    @property
    def definition(self) -> type:
        """The THEMol dataset class this entry delegates to."""
        return self._definition

    def table(self, home: Path, *, coordinate: Coordinate) -> _SplitTable:
        """The provenance-verified split table for this source under *home*.

        Args:
            home: The molhub home holding ``derived/``.
            coordinate: The dataset that was asked for, named in the refusal —
                a reader meeting a derivation they have never heard of has to be
                told which of their calls provoked it.

        Returns:
            The loaded table, keyed by record uuid, memoized per derivation
            directory.

        Raises:
            SplitTableUnavailable: If the derivation has never been built here.
            SplitProvenanceMismatch: If the derivation's own ``metadata.json``
                does not agree with the table beside it.
        """
        root = self._require_derivation(home, coordinate)
        loaded = self._tables.get(root)
        if loaded is None:
            loaded = _SplitTable.from_derived(root, source=self._source)
            self._tables[root] = loaded
        return loaded

    def identities(self, home: Path, *, coordinate: Coordinate) -> _SplitTable:
        """The molecule-level table the prepare stage routes by.

        The sibling of :meth:`table` in the same derivation: that one answers
        *which split is this record in*, this one answers *which split is this
        molecule in*. Both are needed to materialize one split, and reading them
        from one directory is what keeps them the same version of one answer.

        Args:
            home: The molhub home holding ``derived/``.
            coordinate: The dataset that was asked for, named in the refusal.

        Returns:
            The loaded table, keyed by molecular identity, memoized per
            derivation directory.

        Raises:
            SplitTableUnavailable: If the derivation has never been built here.
            SplitProvenanceMismatch: If the derivation's own ``metadata.json``
                does not agree with the table beside it.
        """
        root = self._require_derivation(home, coordinate)
        loaded = self._identities.get(root)
        if loaded is None:
            loaded = _SplitTable.from_identity(root)
            self._identities[root] = loaded
        return loaded

    def require_split(self, split: str, *, manifest: Manifest, home: Path) -> None:
        """Refuse a name the derivation does not record for this dataset.

        The names of a table-backed dataset are the derivation's own, not a
        class attribute, so this reads the table — which is the one gzipped CSV
        ``.info`` reads anyway, memoized, and no shard bytes.

        Raises:
            SplitTableUnavailable: If the derivation has never been built here.
            UnknownSplit: If *split* is not one it records.
        """
        counts = self.table(home, coordinate=manifest.coordinate).counts()
        if split not in counts:
            raise UnknownSplit(
                f"{manifest.coordinate.canonical} declares splits {sorted(counts)}, not {split!r}."
            )

    def _require_derivation(self, home: Path, coordinate: Coordinate) -> Path:
        """The derivation directory, refusing when this machine has never built it.

        The location is computed rather than requested:
        :meth:`~molhub.conveyor.tier.DerivedLayout.artifact_dir` *creates* what
        it returns, so asking it where the tables would live would leave an empty
        derivation directory behind and the next reader would find a directory
        that exists and is empty. Reading a location creates nothing.

        Args:
            home: The molhub home holding ``derived/``.
            coordinate: The dataset that was asked for.

        Returns:
            The directory holding this derivation's tables.

        Raises:
            SplitTableUnavailable: If the derivation's own record is not there.
        """
        root = self._derivation_root(home)
        if not (root / _DERIVATION_RECORD).is_file():
            raise SplitTableUnavailable(
                f"{coordinate.canonical} takes its splits from {_SPLIT_DERIVATION.canonical}, "
                f"and this molhub has not built it: there is no {_DERIVATION_RECORD} at "
                f"{root}. Nothing downloads that assignment — nobody publishes it, it is "
                f"derived here, by:\n\n    {_SPLIT_TABLE_COMMAND}\n\nThat reads the index "
                f"file of every THEMol subset it folds together ({', '.join(_SPLIT_TABLE_INPUTS)}"
                "), which on a machine that has not cached them is a multi-GB download — so "
                "the generator states the cost and stops until it is re-run with --fetch."
            )
        return root

    @staticmethod
    def _derivation_root(home: Path) -> Path:
        """Where the split derivation's tables live under *home*, created or not."""
        return (
            DerivedLayout(home, subdir=_DERIVED_SUBDIR).directory
            / _SPLIT_DERIVATION.namespace
            / _SPLIT_DERIVATION.name
            / _SPLIT_DERIVATION.version
        )

    def splits(self, *, manifest: Manifest, hub: ArtifactHub, home: Path) -> tuple[SplitInfo, ...]:
        """The derivation's counts, folded from the table it verified.

        Costs one gzipped CSV and no shard bytes, which is the whole point of a
        published split table.
        """
        table = self.table(home, coordinate=manifest.coordinate)
        provenance = table.provenance
        sentence = (
            f"{provenance.coordinate}: {provenance.ratios}, seed {provenance.seed}, "
            f"written by {provenance.generator}"
        )
        return tuple(
            SplitInfo(name=name, num_examples=count, provenance=sentence)
            for name, count in sorted(table.counts().items())
        )

    def view(self, split: str, *, manifest: Manifest, hub: ArtifactHub, home: Path) -> Dataset:
        """One split of a shard-published dataset, read through a lazy index."""
        shards = self._definition(hub=hub)
        index = ShardIndex(
            shards,
            coordinate=manifest.coordinate,
            roles=self._shard_roles(manifest),
            layout=DerivedLayout(home, subdir=_DERIVED_SUBDIR),
        )
        return SplitDataset(
            shards,
            split=split,
            table=self.table(home, coordinate=manifest.coordinate),
            index=index,
        )

    def streaming_view(
        self,
        split: str,
        *,
        manifest: Manifest,
        hub: ArtifactHub,
        home: Path,
        disk_budget: int,
    ) -> StreamingSplitDataset:
        """One split of a shard-published dataset, walked under a byte budget.

        The bookkeeping file is the canonical one — the same
        ``molhub cache coverage`` replays — so a walk's claims and releases are
        visible to it instead of accumulating in a second file nobody reads.
        """
        ledger = Ledger(default_ledger_path(home))
        return StreamingSplitDataset(
            self._definition,
            split=split,
            table=self.table(home, coordinate=manifest.coordinate),
            parts=PublishedParts(manifest).files(),
            transfer=ShardTransfer(hub, ledger),
            ledger=ledger,
            disk_budget=disk_budget,
        )

    def block_export(
        self,
        split: str,
        *,
        manifest: Manifest,
        hub: ArtifactHub,
        home: Path,
        output_dir: str | Path,
        disk_budget: int,
        writer_factory: BlockWriterFactory | None = None,
        provenance: Mapping[str, object] | None = None,
    ) -> BlockExport:
        """One split of a shard-published dataset, materialized as blocks.

        The export is fed the split-filtered walk and the whole molecule-level
        assignment, which is D8: records of another split never arrive, and an
        unassigned molecule is still refused rather than placed.

        **The two free refusals come first** (reachability wave, ruling 6).
        Whether this dataset's targets have a column route at all, and whether
        this install can open a block, are decidable from the arguments alone —
        while reading the split derivation is not free and, on a machine that has
        never built it, is its own refusal. Answering "the split table is not
        here" for an export that was never going to run sends the reader on a
        multi-GB errand for nothing, so the export's own preconditions are put
        first and the walk is built only once they hold.
        """
        BlockExport.refuse_unroutable(manifest.coordinate)
        resolved_writer = BlockExport.resolve_writer(writer_factory)

        self.require_split(split, manifest=manifest, home=home)
        parts = PublishedParts(manifest)
        routing = SplitRouting(
            self.streaming_view(
                split, manifest=manifest, hub=hub, home=home, disk_budget=disk_budget
            ),
            table=self.identities(home, coordinate=manifest.coordinate),
        )
        return BlockExport(
            routing,
            split_of=routing.split_of,
            task=parts.task,
            source=manifest.coordinate.canonical,
            output_dir=output_dir,
            writer_factory=resolved_writer,
            provenance=provenance,
        )

    @staticmethod
    def _shard_roles(manifest: Manifest) -> tuple[str, ...]:
        """The manifest's shard roles, in declaration order — the record order."""
        return tuple(role for role in manifest.artifacts if _SHARD_ROLE.fullmatch(role))


class DeclaredSplits(SplitDeclaration):
    """A dataset class that owns its own splits; the builder delegates to it.

    One subclass per published constructor shape. They exist separately rather
    than as flags on one entry because the shapes differ in what they need —
    a root directory, a hub-resolved path, a ``split=`` or a ``tag=`` — and a
    single parameterized entry would encode three datasets' quirks as
    configuration nobody can read.
    """

    def describe_download_size(self, manifest: Manifest) -> int:
        """Every declared byte: counting these splits means reading them.

        :meth:`SplitDeclaration.splits` takes each declared name's ``len``, which
        is exact and which materializes the split. So describing this dataset
        downloads it, and the number is stated here rather than discovered by the
        reader halfway through a benchmark-sized transfer.
        """
        return sum(artifact.size or 0 for artifact in manifest.artifacts.values())


class UnconvertedPayload(DeclaredSplits):
    """A declared dataset whose payload molhub cannot assemble for you.

    Both espaloma entries publish bytes their own dataset class cannot read: a
    tarball of SDF structures and a zip of DGL heterographs, where the class
    reads a *converted* tree (``splits.json`` + ``mols/``) that only an offline
    conversion produces. They stay declared — they are addressable datasets, and
    the conversion is a documented step — but the refusal moves in **front** of
    the fetch: finding out by downloading 281 MB and raising
    ``FileNotFoundError`` afterwards is the download charged for nothing.

    The type is :class:`ValueError`, matching the sibling refusal for a dataset
    published as whole files: both say "this dataset cannot be opened this way,
    here is what to do instead", and one refusal shape for one situation beats a
    second exception hierarchy for the same sentence.
    """

    def view(self, split: str, *, manifest: Manifest, hub: ArtifactHub, home: Path) -> Dataset:
        """Refuse, naming the conversion that is missing.

        Raises:
            ValueError: Always, and before a byte is fetched.
        """
        raise ValueError(self.conversion_refusal(manifest))

    def splits(self, *, manifest: Manifest, hub: ArtifactHub, home: Path) -> tuple[SplitInfo, ...]:
        """No split, because an exact count would need the payload.

        ``()`` is the honest answer while the conversion is missing. The split
        *names* still exist as :attr:`~SplitDeclaration.NAMES`, which is what
        validates a name — a dataset that cannot be counted is not a dataset
        whose splits are unnamed.
        """
        return ()

    def describe_download_size(self, manifest: Manifest) -> int:
        """Nothing: describing this reads the manifest and refuses the payload."""
        return 0

    @abstractmethod
    def conversion_refusal(self, manifest: Manifest) -> str:
        """Why this dataset cannot be opened from its published bytes.

        Args:
            manifest: The registry manifest of the resolved coordinate.

        Returns:
            A sentence naming the dataset and the conversion that produces the
            tree its reader wants.
        """


class ZincTypingSplits(UnconvertedPayload):
    """zinc-typing: molecule-level splits from the payload's own ``splits.json``."""

    NAMES: ClassVar[tuple[str, ...]] = ("train", "val", "test")
    PROVENANCE: ClassVar[str] = (
        "ZincTypingDataset: the payload's own splits.json, molecule-level 80:10:10 "
        "on the Espaloma recipe."
    )

    @property
    def definition(self) -> type:
        return ZincTypingDataset

    def conversion_refusal(self, manifest: Manifest) -> str:
        """The published tarball is SDF structures; the reader wants the tree."""
        return (
            f"{manifest.coordinate.canonical} is published as a tarball of SDF structures, "
            "and ZincTypingDataset reads a converted tree — a splits.json beside a mols/ "
            "directory — which those bytes do not contain. Downloading them would not "
            "produce one, so nothing was fetched. Point ZincTypingDataset at a converted "
            "root yourself, or open the published archive with "
            "molhub fetch dataset:espaloma/zinc-typing@1 and convert it once."
        )


class PhalkethohSplits(UnconvertedPayload):
    """phalkethoh-mm: molecule-level splits from the payload's own ``splits.json``."""

    NAMES: ClassVar[tuple[str, ...]] = ("train", "val", "test")
    PROVENANCE: ClassVar[str] = (
        "PhalkethohMMDataset: the payload's own splits.json, molecule-level 80:10:10, "
        "every conformer of a molecule in one split."
    )

    @property
    def definition(self) -> type:
        return PhalkethohMMDataset

    def conversion_refusal(self, manifest: Manifest) -> str:
        """The published zip is DGL heterographs; converting them needs dgl."""
        return (
            f"{manifest.coordinate.canonical} is published as a zip of DGL heterographs, "
            "and PhalkethohMMDataset reads a converted tree — a splits.json beside a mols/ "
            "directory. The conversion is offline and once, because it needs dgl, which "
            "molhub does not depend on: run scripts/convert_espaloma_phalkethoh_mm.py in an "
            "environment that has dgl, then point PhalkethohMMDataset at what it wrote. "
            "Nothing was fetched."
        )


class ThreeBPASplits(DeclaredSplits):
    """3BPA: four published files, one manifest role each, named by ``tag=``.

    The one constructor that does not take ``split=``: it takes a required
    positional path and a ``tag``. The path is resolved through the hub here, so
    the caller of :meth:`DatasetBuilder.split_view` still only names a split.

    Each name is also the manifest role and the tag ``ThreeBPADataset`` accepts —
    one spelling, three declarations. A name that is not a published role would
    take the whole dataset down rather than one split: ``view`` fetches
    ``roles=[split]``, and ``.info`` counts *every* declared name, so one wrong
    entry makes the dataset undescribable as well as unopenable.
    """

    NAMES: ClassVar[tuple[str, ...]] = ("train_300K", "test_300K", "test_600K", "test_1200K")
    PROVENANCE: ClassVar[str] = (
        "ThreeBPADataset: each split is one published extended-XYZ file of the "
        "benchmark, carried as its own role in the manifest."
    )

    @property
    def definition(self) -> type:
        return ThreeBPADataset

    def view(self, split: str, *, manifest: Manifest, hub: ArtifactHub, home: Path) -> Dataset:
        path = hub.fetch(manifest.coordinate.canonical, roles=[split])[split]
        return ThreeBPADataset(path, tag=split, hub=hub)


class DatasetBuilder:
    """One dataset, described before it is read.

    Args:
        name: The dataset in HuggingFace spelling, ``"themol/mbis"`` or
            ``"qm9"``. Not a coordinate: the version is *revision*.
        revision: Which version to pin. ``None`` takes the newest the registry
            declares, and refuses when they do not order.
        registry: Where manifests come from; ``None`` loads the configured or
            bundled registry.
        hub: Where bytes come from; ``None`` constructs a
            :class:`~molhub.molhub.Molhub`. Nothing is fetched until a split is
            actually opened (or, for a declared-split dataset, counted).
        home: The molhub home the split derivation and any memo are read from;
            ``None`` resolves ``$MOLHUB_HOME``. A second home is addressable
            without exporting a variable around the call, which is what
            ``molhub info --home`` is.
    """

    #: Which entry describes which artifact, by unversioned coordinate. The
    #: whole per-dataset dispatch of this layer, in one readable table: a
    #: dataset absent from it is still describable — prose, features and size
    #: come from the manifest — it simply declares no splits.
    #:
    #: Every key is a coordinate the bundled registry can address. A row for one
    #: nobody publishes is a promise molhub cannot keep — it could only ever
    #: resolve to :class:`~molhub.registry.UnknownArtifact` — and this table is
    #: what a reader consults to find out what is loadable, so
    #: ``dataset:molcrafts/water-les`` is deliberately absent.
    DECLARATIONS: ClassVar[Mapping[str, SplitDeclaration]] = MappingProxyType(
        {
            "dataset:themol/hessian": TableBackedSplits(THEMolHessian, source="hessian"),
            "dataset:themol/mbis": TableBackedSplits(THEMolMBIS, source="mbis"),
            "dataset:themol/torsion-scan": TableBackedSplits(
                THEMolTorsionScan, source="torsion-scan"
            ),
            "dataset:espaloma/zinc-typing": ZincTypingSplits(),
            "dataset:espaloma/phalkethoh-mm-small": PhalkethohSplits(),
            "dataset:molcrafts/3bpa": ThreeBPASplits(),
        }
    )

    def __init__(
        self,
        name: str,
        *,
        revision: str | None = None,
        registry: Registry | None = None,
        hub: ArtifactHub | None = None,
        home: str | Path | None = None,
    ) -> None:
        self._name = DatasetName(name, revision=revision)
        self._registry = registry
        self._hub = hub
        self._home = BlobStore(home).root
        self._info: DatasetInfo | None = None
        self._resolved: tuple[Coordinate, Manifest] | None = None

    def __repr__(self) -> str:
        """Which dataset this is, at the version it resolved to.

        ``<molhub.loader.builder.DatasetBuilder object at 0x…>`` answers neither
        "which dataset" nor "which version" — and the version is the one fact a
        run has to be able to record. Resolving it reads the registry and no
        shard bytes, which is what makes it printable at all.
        """
        return f"DatasetBuilder({self._addressed()!r})"

    def _addressed(self) -> str:
        """The resolved coordinate, or the name that was asked for.

        Every failure is swallowed on purpose, and only here: a ``__repr__``
        that raises is one a debugger cannot print, which is exactly the moment
        it is needed. The resolution failure itself belongs to :attr:`info` —
        where it is raised with its own message — not to looking at the object.

        Returns:
            The canonical coordinate, or the unversioned name when nothing
            resolves it.
        """
        try:
            coordinate, _ = self._resolve()
        except Exception:
            return self._name.unversioned
        return coordinate.canonical

    @property
    def info(self) -> DatasetInfo:
        """What this dataset contains, computed once per builder.

        Returns:
            The :class:`~molhub.loader.info.DatasetInfo` — content only, and
            never a shard role.

        Raises:
            AmbiguousRevision: If no revision was given and the declared
                versions do not order.
            UnknownArtifact: If the registry has no manifest for the resolved
                coordinate.
            SplitTableUnavailable: If this dataset's splits come from a published
                derivation and this molhub has not built it.
        """
        if self._info is None:
            self._info = self._describe()
        return self._info

    @property
    def describe_download_size(self) -> int:
        """How many bytes :attr:`info` will download before it can answer.

        Zero for every dataset whose splits a published derivation states, and
        for one that declares none: those are read from a manifest and a gzipped
        table. A dataset whose class owns its splits is counted by constructing
        each of them, so describing it costs what reading it costs — and a caller
        that wants to warn before spending that (``molhub info`` does) can ask
        here first.

        Returns:
            The declared byte total, or ``0`` when describing is free.

        Raises:
            AmbiguousRevision: If no revision was given and the declared
                versions do not order.
            UnknownArtifact: If the registry has no manifest for the resolved
                coordinate.
        """
        coordinate, manifest = self._resolve()
        declaration = self.DECLARATIONS.get(coordinate.unversioned)
        return declaration.describe_download_size(manifest) if declaration is not None else 0

    def split_view(self, split: str) -> Dataset:
        """Open one split of this dataset.

        Args:
            split: One of the names :attr:`info` reports.

        Returns:
            A map-style dataset whose records are the ``Frame`` /
            ``Trajectory`` the dataset's own reader builds.

        Raises:
            UnknownSplit: If *split* is not one of the declared splits, or if
                this dataset declares none at all. It is a ``KeyError``, and the
                name is checked against the declaration before anything is
                fetched.
            SplitTableUnavailable: If the splits come from a published derivation
                this molhub has not built.
            ValueError: If the dataset's payload needs an offline conversion this
                machine has not run.
        """
        declaration, manifest = self._declaring(split)
        declaration.require_split(split, manifest=manifest, home=self._home)
        return declaration.view(split, manifest=manifest, hub=self._artifact_hub(), home=self._home)

    def streaming_view(
        self, split: str, *, disk_budget: int = DEFAULT_BUDGET_BYTES
    ) -> StreamingSplitDataset:
        """Walk one split of this dataset, one published file at a time.

        Args:
            split: One of the names :attr:`info` reports.
            disk_budget: How many bytes of fetched files this walk may keep on
                local disk at once.

        Returns:
            An iterable dataset yielding this split's records in published
            order, with at most one file resident at a time.

        Raises:
            UnknownSplit: If *split* is not one of the declared splits, or if
                this dataset declares none at all.
            SplitTableUnavailable: If the splits come from a published derivation
                this molhub has not built.
            ValueError: If this dataset is published as whole files, so there is
                nothing to walk a piece at a time.
        """
        declaration, manifest = self._declaring(split)
        declaration.require_split(split, manifest=manifest, home=self._home)
        return declaration.streaming_view(
            split,
            manifest=manifest,
            hub=self._artifact_hub(),
            home=self._home,
            disk_budget=disk_budget,
        )

    def block_export(
        self,
        split: str,
        *,
        output_dir: str | Path,
        writer_factory: BlockWriterFactory | None = None,
        provenance: Mapping[str, object] | None = None,
        disk_budget: int = DEFAULT_BUDGET_BYTES,
    ) -> BlockExport:
        """Materialize one split of this dataset into a block directory.

        Args:
            split: One of the names :attr:`info` reports.
            output_dir: Directory the sealed block roots are created under.
            writer_factory: How one block is opened; ``None`` resolves molnex's
                own writer and refuses with an actionable message when molnex is
                not importable.
            provenance: Opaque provenance for every block; ``None`` states the
                export's own, which carries the keys the block format requires.
            disk_budget: How many bytes of fetched files the walk behind the
                export may keep on local disk at once.

        Returns:
            The :class:`~molhub.loader.materialize.BlockExport`, ready to run.

        Raises:
            UnknownSplit: If *split* is not one of the declared splits, or if
                this dataset declares none at all.
            ValueError: If this dataset is published as whole files.
            UnsupportedRecordError: If the block format routes none of this
                dataset's targets. Decided before the split derivation is read.
            ImportError: If molnex is not importable and no writer was injected.
                Also decided before the split derivation is read.
        """
        declaration, manifest = self._declaring(split)
        return declaration.block_export(
            split,
            manifest=manifest,
            hub=self._artifact_hub(),
            home=self._home,
            output_dir=output_dir,
            disk_budget=disk_budget,
            writer_factory=writer_factory,
            provenance=provenance,
        )

    def _declaring(self, split: str) -> tuple[SplitDeclaration, Manifest]:
        """The entry that owns this dataset's splits, and its manifest.

        Deliberately does **not** consult :attr:`info`: for a table-backed
        dataset that reads the split derivation, and for a declared-split one it
        constructs every split — so validating a name through it would make a
        typo cost a download and would answer "the split table is not here" for
        an export that a cheaper refusal was about to reject anyway. Which names
        exist is the declaration's own question, asked by
        :meth:`SplitDeclaration.require_split` at the point where the answer is
        actually needed.

        Args:
            split: The name the caller asked for, for the message.

        Raises:
            UnknownSplit: If this dataset declares no splits at all.
        """
        coordinate, manifest = self._resolve()
        declaration = self.DECLARATIONS.get(coordinate.unversioned)
        if declaration is None:
            raise UnknownSplit(
                f"{coordinate.canonical} declares no splits in this molhub, so there is "
                f"no {split!r} to open. Its whole content is one view."
            )
        return declaration, manifest

    def _describe(self) -> DatasetInfo:
        """Compose the description from the manifest and the class declarations."""
        coordinate, manifest = self._resolve()
        declaration = self.DECLARATIONS.get(coordinate.unversioned)
        definition = declaration.definition if declaration is not None else None
        schema = self._target_schema(definition, manifest)
        declared = self._declared_manifest(definition, coordinate)
        names = sorted(set(schema.atom_level) | set(schema.graph_level) | set(declared.blocks))
        splits = (
            declaration.splits(manifest=manifest, hub=self._artifact_hub(), home=self._home)
            if declaration is not None
            else ()
        )
        return DatasetInfo(
            coordinate=coordinate,
            description=manifest.description,
            citation=manifest.doi or "",
            license=manifest.license or "",
            features=tuple(
                Feature.declared(name, schema=schema, manifest=declared) for name in names
            ),
            splits=splits,
            record_type=self._record_type(definition),
            download_size=sum(artifact.size or 0 for artifact in manifest.artifacts.values()),
        )

    def _resolve(self) -> tuple[Coordinate, Manifest]:
        """The pinned coordinate and its manifest, resolved once."""
        if self._resolved is None:
            registry = self._registry if self._registry is not None else Registry.load()
            self._registry = registry
            coordinate = self._name.resolve(registry)
            self._resolved = (coordinate, registry.get(coordinate))
        return self._resolved

    def _artifact_hub(self) -> ArtifactHub:
        """The hub bytes come from; constructed on first use, never at import."""
        if self._hub is None:
            self._hub = Molhub()
        return self._hub

    @staticmethod
    def _target_schema(definition: type | None, manifest: Manifest) -> TargetSchema:
        """The dataset class's layout declaration, or the manifest's own."""
        declared = getattr(definition, "TARGET_SCHEMA", None)
        if isinstance(declared, TargetSchema):
            return declared
        return TargetSchema(
            graph_level=frozenset(manifest.targets.graph_level),
            atom_level=frozenset(manifest.targets.atom_level),
        )

    @staticmethod
    def _declared_manifest(definition: type | None, coordinate: Coordinate) -> DatasetManifest:
        """The class's ``@dataset`` declaration, or an empty one for a class without.

        A dataset declaring neither units nor blocks renders ``units=""`` for
        every feature and has no block features — the documented default, not a
        special case.
        """
        declared = getattr(definition, "manifest", None)
        if isinstance(declared, DatasetManifest):
            return declared
        return DatasetManifest(coordinate=coordinate)

    @staticmethod
    def _record_type(definition: type | None) -> str:
        """What one record is, read off the class's declared generic argument.

        ``THEMolMBIS(_THEMolDefinition[Frame])`` says ``Frame`` in the one place
        that cannot drift from what its reader returns. A class that does not
        parameterize its record type is reported as the ``Sample`` union.
        """
        for base in getattr(definition, "__orig_bases__", ()):
            arguments = get_args(base)
            if arguments and isinstance(arguments[0], type):
                return arguments[0].__name__
        return _SAMPLE_RECORD_TYPE
