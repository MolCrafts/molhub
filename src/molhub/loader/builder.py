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
  bytes** — which is what makes ``.info`` usable on a 150 GB artifact.
* *declared* (water-les, zinc-typing, phalkethoh-mm, 3BPA): the dataset class
  already owns its splits, so the builder delegates to its constructor. The
  four constructors do not agree on a spelling — three take ``split=``, 3BPA
  takes ``tag=`` with a required positional path — so each gets its own small
  adapter below rather than a uniform ``Ctor(split=split)`` dispatch that would
  be wrong for one of them.

**What the declared flavour costs, said out loud.** Its counts are exact
because they come from the dataset itself — which means constructing it, which
means its bytes. ``load_dataset_builder(...).info`` is therefore free only for
the table-backed datasets; for a declared-split one it costs what
``load_dataset`` costs. That is the price of a dataset whose splits nobody
published a table for, and it is charged here rather than hidden.

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
from molhub.dataset.water_les import WaterLESDataset
from molhub.dataset.zinc_typing import ZincTypingDataset
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
    "WaterLESSplits",
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

    def table(self, home: Path) -> _SplitTable:
        """The provenance-verified split table for this source under *home*.

        Args:
            home: The molhub home holding ``derived/``.

        Returns:
            The loaded table, keyed by record uuid, memoized per derivation
            directory.

        Raises:
            SplitProvenanceMismatch: If the derivation's own ``metadata.json``
                does not agree with the table beside it.
        """
        root = self._derivation_root(home)
        loaded = self._tables.get(root)
        if loaded is None:
            loaded = _SplitTable.from_derived(root, source=self._source)
            self._tables[root] = loaded
        return loaded

    def identities(self, home: Path) -> _SplitTable:
        """The molecule-level table the prepare stage routes by.

        The sibling of :meth:`table` in the same derivation: that one answers
        *which split is this record in*, this one answers *which split is this
        molecule in*. Both are needed to materialize one split, and reading them
        from one directory is what keeps them the same version of one answer.

        Args:
            home: The molhub home holding ``derived/``.

        Returns:
            The loaded table, keyed by molecular identity, memoized per
            derivation directory.

        Raises:
            SplitProvenanceMismatch: If the derivation's own ``metadata.json``
                does not agree with the table beside it.
        """
        root = self._derivation_root(home)
        loaded = self._identities.get(root)
        if loaded is None:
            loaded = _SplitTable.from_identity(root)
            self._identities[root] = loaded
        return loaded

    @staticmethod
    def _derivation_root(home: Path) -> Path:
        """Where the split derivation's tables live under *home*."""
        return DerivedLayout(home, subdir=_DERIVED_SUBDIR).artifact_dir(
            _SPLIT_DERIVATION.namespace, _SPLIT_DERIVATION.name, _SPLIT_DERIVATION.version
        )

    def splits(self, *, manifest: Manifest, hub: ArtifactHub, home: Path) -> tuple[SplitInfo, ...]:
        """The derivation's counts, folded from the table it verified.

        Costs one gzipped CSV and no shard bytes, which is the whole point of a
        published split table.
        """
        table = self.table(home)
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
        return SplitDataset(shards, split=split, table=self.table(home), index=index)

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
            table=self.table(home),
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
        """
        parts = PublishedParts(manifest)
        routing = SplitRouting(
            self.streaming_view(
                split, manifest=manifest, hub=hub, home=home, disk_budget=disk_budget
            ),
            table=self.identities(home),
        )
        return BlockExport(
            routing,
            split_of=routing.split_of,
            task=parts.task,
            source=manifest.coordinate.canonical,
            output_dir=output_dir,
            writer_factory=writer_factory,
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
    single parameterized entry would encode four datasets' quirks as
    configuration nobody can read.
    """

    def _cache_root(self, manifest: Manifest, home: Path) -> Path:
        """This artifact's own cache directory, for a payload unpacked locally.

        The dataset classes take a local root and fall back to the hub when it
        holds nothing; pointing them at the artifact's cache directory keeps an
        unpacked payload beside the bytes it came from instead of inventing a
        second layout.
        """
        return BlobStore(home).path_for(manifest.coordinate.cache_path())


class WaterLESSplits(DeclaredSplits):
    """WaterLES: two views of the training file plus the published test file."""

    NAMES: ClassVar[tuple[str, ...]] = ("train", "val", "test")
    PROVENANCE: ClassVar[str] = (
        "WaterLESDataset: 'train' and 'val' are the upstream recipe's deterministic "
        "95:5 split of one training file; 'test' is the published test file."
    )

    @property
    def definition(self) -> type:
        return WaterLESDataset

    def view(self, split: str, *, manifest: Manifest, hub: ArtifactHub, home: Path) -> Dataset:
        """``WaterLESDataset`` names a split cheaply; ``load`` is its fetch boundary."""
        return WaterLESDataset(self._cache_root(manifest, home), split=split, hub=hub).load()


class ZincTypingSplits(DeclaredSplits):
    """zinc-typing: molecule-level splits from the payload's own ``splits.json``."""

    NAMES: ClassVar[tuple[str, ...]] = ("train", "val", "test")
    PROVENANCE: ClassVar[str] = (
        "ZincTypingDataset: the payload's own splits.json, molecule-level 80:10:10 "
        "on the Espaloma recipe."
    )

    @property
    def definition(self) -> type:
        return ZincTypingDataset

    def view(self, split: str, *, manifest: Manifest, hub: ArtifactHub, home: Path) -> Dataset:
        return ZincTypingDataset(self._cache_root(manifest, home), split=split, hub=hub)


class PhalkethohSplits(DeclaredSplits):
    """phalkethoh-mm: molecule-level splits from the payload's own ``splits.json``."""

    NAMES: ClassVar[tuple[str, ...]] = ("train", "val", "test")
    PROVENANCE: ClassVar[str] = (
        "PhalkethohMMDataset: the payload's own splits.json, molecule-level 80:10:10, "
        "every conformer of a molecule in one split."
    )

    @property
    def definition(self) -> type:
        return PhalkethohMMDataset

    def view(self, split: str, *, manifest: Manifest, hub: ArtifactHub, home: Path) -> Dataset:
        return PhalkethohMMDataset(self._cache_root(manifest, home), split=split, hub=hub)


class ThreeBPASplits(DeclaredSplits):
    """3BPA: four published files, one manifest role each, named by ``tag=``.

    The one constructor that does not take ``split=``: it takes a required
    positional path and a ``tag``. The path is resolved through the hub here, so
    the caller of :meth:`DatasetBuilder.split_view` still only names a split.
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
    """

    #: Which entry describes which artifact, by unversioned coordinate. The
    #: whole per-dataset dispatch of this layer, in one readable table: a
    #: dataset absent from it is still describable — prose, features and size
    #: come from the manifest — it simply declares no splits.
    DECLARATIONS: ClassVar[Mapping[str, SplitDeclaration]] = MappingProxyType(
        {
            "dataset:themol/hessian": TableBackedSplits(THEMolHessian, source="hessian"),
            "dataset:themol/mbis": TableBackedSplits(THEMolMBIS, source="mbis"),
            "dataset:themol/torsion-scan": TableBackedSplits(
                THEMolTorsionScan, source="torsion-scan"
            ),
            "dataset:molcrafts/water-les": WaterLESSplits(),
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
    ) -> None:
        self._name = DatasetName(name, revision=revision)
        self._registry = registry
        self._hub = hub
        self._info: DatasetInfo | None = None
        self._resolved: tuple[Coordinate, Manifest] | None = None

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
        """
        if self._info is None:
            self._info = self._describe()
        return self._info

    def split_view(self, split: str) -> Dataset:
        """Open one split of this dataset.

        Args:
            split: One of the names :attr:`info` reports.

        Returns:
            A map-style dataset whose records are the ``Frame`` /
            ``Trajectory`` the dataset's own reader builds.

        Raises:
            KeyError: If *split* is not one of the declared splits, or if this
                dataset declares none at all. Discovery is ``info.splits``, so
                the message says what discovery would have.
        """
        declaration, manifest = self._declaring(split)
        return declaration.view(
            split, manifest=manifest, hub=self._artifact_hub(), home=self._home()
        )

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
            KeyError: If *split* is not one of the declared splits, or if this
                dataset declares none at all.
            ValueError: If this dataset is published as whole files, so there is
                nothing to walk a piece at a time.
        """
        declaration, manifest = self._declaring(split)
        return declaration.streaming_view(
            split,
            manifest=manifest,
            hub=self._artifact_hub(),
            home=self._home(),
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
            KeyError: If *split* is not one of the declared splits, or if this
                dataset declares none at all.
            ValueError: If this dataset is published as whole files.
            ImportError: If molnex is not importable and no writer was injected.
        """
        declaration, manifest = self._declaring(split)
        return declaration.block_export(
            split,
            manifest=manifest,
            hub=self._artifact_hub(),
            home=self._home(),
            output_dir=output_dir,
            disk_budget=disk_budget,
            writer_factory=writer_factory,
            provenance=provenance,
        )

    def _declaring(self, split: str) -> tuple[SplitDeclaration, Manifest]:
        """The entry that owns *split*, and the manifest it is opened against.

        Raises:
            KeyError: If this dataset declares no splits at all, or not this
                one. Discovery is ``info.splits``, so the message says what
                discovery would have.
        """
        declared = tuple(entry.name for entry in self.info.splits)
        coordinate, manifest = self._resolve()
        declaration = self.DECLARATIONS.get(coordinate.unversioned)
        if declaration is None:
            raise KeyError(
                f"{coordinate.canonical} declares no splits in this molhub, so there is "
                f"no {split!r} to open. Its whole content is one view."
            )
        if split not in declared:
            raise KeyError(
                f"{coordinate.canonical} declares splits {list(declared)}, not {split!r}."
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
            declaration.splits(manifest=manifest, hub=self._artifact_hub(), home=self._home())
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
    def _home() -> Path:
        """The molhub home, resolved by the one class that owns that rule."""
        return BlobStore().root

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
