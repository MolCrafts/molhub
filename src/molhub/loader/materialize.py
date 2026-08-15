"""One split of one dataset, materialized as sealed molnex blocks.

:func:`prepare` is the doorway and :class:`BlockExport` is the work — the entry
sits beside the type it delegates to, and ``molhub/__init__`` re-exports it, so
``from molhub import prepare`` reaches the same object. The export reads the
split's records through the same bounded walk :mod:`molhub.loader.streaming`
yields — so materializing a 150 GB dataset costs one file of disk at a time —
encodes each record whole, and hands it to
:class:`~molhub.conveyor.prepare.PrepareJob`, which routes it to its molecule's
split and seals the blocks. What comes back is the conveyor's own
:class:`~molhub.conveyor.prepare.PreparedBlocks`; this layer adds no fourth block
type and no second block format.

**One split in, one split's roots out** (D8). ``PrepareJob`` routes by *molecular
identity* while a split view filters by *record uuid*, and the two are different
key spaces of the same published derivation. So the job is fed the
**split-filtered** walk together with the **whole** identity assignment: records
of another split never arrive, so no writer for them is ever opened and
``output_dir`` holds only the requested split's roots — while an identity the
derivation genuinely never assigned still reaches
:class:`~molhub.conveyor.errors.UnroutableUnitError`, because nothing here
defaults a split. ``PrepareJob`` is unchanged; there is no second routing.

**The identity assignment is resolved one record ahead**
(:class:`SplitRouting`). ``identity_splits.csv.gz`` runs to millions of rows, and
materialising all of it to route the few thousand molecules of one split would
read a whole derivation to answer a question about the records that actually
arrive. So each record's identity is resolved — through
:meth:`~molhub.conveyor.encoder.THEMolUnitEncoder.identity`, the one
implementation of that rule — as the record passes on its way to the encoder. An
identity the table does not assign is simply absent from the mapping, which is
exactly what the refusal above reads.

**Fail closed without molnex** (ac-005). Blocks are molnex's format, and this
distribution can neither import nor install it by itself. So the default writer
is resolved — by really importing what it needs — **before anything is created**,
and a missing half is re-raised as an :class:`ImportError` naming the ``prepare``
extra and the ``MOLNEX_SRC`` escape hatch. A bare ``No module named 'torch'`` is
not an answer to "why did my export not run", and a half-written block directory
is not a smaller failure than none.

**A dataset ``molix.block/1`` has no routes for is refused, not exported.**
:class:`~molhub.conveyor.encoder.THEMolUnitEncoder` refuses the subset label
``"mbis"`` because the block format defines no columns for its atom-level
electrostatics targets, and labelling those units with the *collection role*
they are published under (``electrostatic``) is a second name for the same
records rather than a second answer: an export that succeeded on them would
write the geometry and topology and **drop** the per-atom charges, volumes,
dipoles, quadrupoles and Slater parameters the dataset exists for. So
:class:`BlockExport` puts the question to the encoder's own constructor — the
one place that route table is stated — with the subset label its coordinate
names, and re-raises the refusal in this layer's vocabulary before anything is
fetched or created. The named future route is a molnex spec adding a routable
atom-level column space to ``molix.block/1``; until it lands, the targets are
read with ``load_dataset(name, split=...)`` and this refusal stands.

Reference:
    ``.claude/specs/hf-facade-04-streaming-prepare.md`` § Design (D8), ac-004
    and ac-005, under the 2026-08-15 operator override recorded in
    ``.claude/notes/notes.md`` (``mol:note:topic:hf-style-api``).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

from molhub.conveyor import DEFAULT_BUDGET_BYTES
from molhub.conveyor.encoder import THEMolUnitEncoder
from molhub.conveyor.errors import UnsupportedRecordError
from molhub.conveyor.prepare import (
    BlockWriterFactory,
    MolnexBlockWriter,
    PreparedBlocks,
    PrepareJob,
)
from molhub.conveyor.splits import _SplitTable
from molhub.coordinate import Coordinate
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.protocol import Sample
from molhub.dataset.themol import THEMOL_UNITS
from molhub.registry import Registry

__all__ = ["SplitRouting", "BlockExport", "prepare"]

# What the default writer needs before it can open anything, in the order a
# reader would install them: the publishable half, then molnex itself.
_WRITER_MODULES = ("torch", "molix.store.block")

# The block format this layer writes, named in the refusal above so a reader
# knows where the missing column routes have to be added. Mirrored from
# ``molhub.conveyor.prepare`` rather than imported, as
# ``molhub.conveyor.coverage`` mirrors it: it is molnex's public identifier, and
# a private constant is not a cross-module surface.
_BLOCK_FORMAT = "molix.block/1"

# Who a block says wrote it, when the caller states no provenance of its own.
_GENERATOR = "molhub.loader.materialize.BlockExport"

# The one target column a THEMol record carries its molecular identity in.
_SMILES = "mapped_isomeric_smiles"


class SplitRouting:
    """The walk's records, with each molecule's split resolved as it passes.

    Iterating this yields the records unchanged and fills :attr:`split_of` —
    identity to split label, from the verified table, one record ahead of the
    unit that needs it. See this module's docstring for why the whole table is
    not materialised. The mapping is handed to
    :class:`~molhub.conveyor.prepare.PrepareJob` live: the job encodes and routes
    each record immediately after pulling it from :meth:`__iter__`, so every
    identity it asks about has already been resolved.

    Args:
        records: The split-filtered walk.
        table: The identity-keyed split assignment, provenance-verified.
    """

    def __init__(self, records: Iterable[Sample], *, table: _SplitTable) -> None:
        self._records = records
        self._table = table
        self._assignments: dict[str, str] = {}

    @property
    def split_of(self) -> Mapping[str, str]:
        """Molecular identity to split, for every record that has passed so far.

        Returns:
            The live mapping. An identity the derivation never assigned is
            absent rather than defaulted, which is what makes a unit nobody
            assigned a split refusable instead of silently placed.
        """
        return self._assignments

    def __iter__(self) -> Iterator[Sample]:
        """Yield every record, resolving its molecule's split first."""
        for record in self._records:
            self._resolve(record)
            yield record

    def _resolve(self, record: Sample) -> None:
        """Record the split of *record*'s molecule, when the table assigns one."""
        smiles = self._smiles(record)
        if smiles is None:
            return
        identity = THEMolUnitEncoder.identity(smiles)
        if identity in self._assignments:
            return
        try:
            self._assignments[identity] = self._table.split_of(identity)
        except KeyError:
            # Left absent on purpose: the encoder is about to name this unit, and
            # its refusal says which molecule and which derivation disagree.
            return

    @staticmethod
    def _smiles(record: Sample) -> str | None:
        """The mapped SMILES of *record*, or ``None`` when it carries none.

        A frame states it in its own ``meta``; a trajectory's frames each state
        the same one, so the first is read. A record with neither is left for
        the encoder to refuse, which is where that diagnosis already lives.
        """
        meta = getattr(record, "meta", None)
        if meta is None:
            frames = getattr(record, "frames", ())
            meta = frames[0].meta if len(frames) else {}
        value = meta.get(_SMILES)
        return value if isinstance(value, str) and value else None


class BlockExport:
    """Turns one split of one dataset into sealed, split-pure molnex blocks.

    Every collaborator is an explicit narrow parameter, as on
    :class:`~molhub.conveyor.prepare.PrepareJob`, and the writer is injected so
    that a test — and the base install — never needs torch.

    Args:
        records: The split-filtered walk, in record order.
        split_of: The identity-keyed split assignment the units are routed by.
        task: The label every unit carries — the collection role the dataset's
            parts are published under, which is also what the bookkeeping
            addresses them by.
        source: The **resolved** coordinate, as text. It names the export's
            blocks and is the ``source`` of the default provenance.
        output_dir: Directory the sealed block roots are created under.
        writer_factory: How one block is opened. ``None`` resolves molnex's own
            writer, and says so with an actionable :class:`ImportError` when
            molnex is not importable.
        provenance: Opaque provenance for every block. ``None`` states this
            layer's own, which carries the four keys ``molix.block/1`` requires.

    Raises:
        UnsupportedRecordError: If ``molix.block/1`` routes none of this
            dataset's targets, so exporting it could only drop them. Raised at
            construction, before any directory exists and before a byte is read.
        ImportError: If *writer_factory* is ``None`` and molnex or torch cannot
            be imported. Raised at construction, before any directory exists.
        InvalidCoordinate: If *source* is not a version-pinned coordinate.
    """

    def __init__(
        self,
        records: Iterable[Sample],
        *,
        split_of: Mapping[str, str],
        task: str,
        source: str,
        output_dir: str | Path,
        writer_factory: BlockWriterFactory | None = None,
        provenance: Mapping[str, object] | None = None,
    ) -> None:
        self._coordinate = Coordinate.parse(source)
        self._refuse_unroutable()
        self._records = records
        self._split_of = split_of
        self._task = task
        self._output_dir = Path(output_dir)
        self._writer_factory = self._resolved_factory(writer_factory)
        self._provenance = dict(provenance) if provenance is not None else self._own_provenance()

    @property
    def name(self) -> str:
        """What this export's blocks are named after: the pinned artifact."""
        return f"{self._coordinate.namespace}-{self._coordinate.name}@{self._coordinate.version}"

    def run(self) -> PreparedBlocks:
        """Encode, route and seal this split.

        Returns:
            The conveyor's own evidence for every root sealed: one entry per
            block, each carrying the split it holds, its unit and frame counts,
            its committed bytes and the digest its sealed manifest states.

        Raises:
            UnroutableUnitError: If a record's molecule has no split in the
                derivation.
            IncompleteProvenanceError: If the stated provenance is missing a key
                ``molix.block/1`` requires; raised before a writer is opened.
            BlockFormatError: If a sealed block does not witness what molhub
                would report about it.
        """
        return PrepareJob(
            self._records,
            encoder=THEMolUnitEncoder(task=self._task),
            split_of=self._split_of,
            writer_factory=self._writer_factory,
            root=self._output_dir,
            name=self.name,
            provenance=self._provenance,
        ).run()

    def _refuse_unroutable(self) -> None:
        """Refuse a dataset whose targets this block format has no columns for.

        Asked of :class:`~molhub.conveyor.encoder.THEMolUnitEncoder`'s
        constructor rather than answered here: that constructor is where the
        route table is stated, and a second copy of it in this layer would be a
        second thing to be wrong. What this layer supplies is the *translation* —
        the encoder is keyed by subset label, which is the coordinate's own name
        (``dataset:themol/mbis@1`` -> ``mbis``), while the units of an export are
        labelled with the collection role the parts are published under. Those
        are two names for the same records, so the collection role is not an
        exemption from the refusal.

        Deciding it from the coordinate alone is what makes it cheap: a refusal
        that first had to read 150 GB of published files would not be one.

        Raises:
            UnsupportedRecordError: If the encoder refuses this dataset's subset
                label, restated with the coordinate, the format whose column
                routes are missing, and what exporting anyway would cost.
        """
        try:
            THEMolUnitEncoder(task=self._coordinate.name)
        except UnsupportedRecordError as error:
            raise UnsupportedRecordError(
                f"{self._coordinate.canonical} cannot be materialized as {_BLOCK_FORMAT} "
                "blocks: its atom-level electrostatics targets (atomic_charge, "
                "atomic_volume, the dipole and quadrupole components and the per-atom "
                f"Slater parameters) have no column route in {_BLOCK_FORMAT}. Exporting it "
                "anyway would write the geometry and topology and silently drop every "
                "target the dataset exists for, so nothing was written and nothing was "
                f"created. The fix is a routable atom-level column space in {_BLOCK_FORMAT}, "
                "not a flag here; until it exists, read the targets with "
                "load_dataset(name, split=...)."
            ) from error

    def _own_provenance(self) -> dict[str, object]:
        """The four keys ``molix.block/1`` requires, stated by this layer.

        The units are the dataset's own declaration rather than a restatement:
        a second spelling of "kcal/mol" is a second thing to be wrong.
        """
        return {
            "source": self._coordinate.canonical,
            "generator": _GENERATOR,
            "created_at": datetime.now(UTC).isoformat(),
            "units": dict(THEMOL_UNITS),
        }

    @staticmethod
    def _resolved_factory(factory: BlockWriterFactory | None) -> BlockWriterFactory:
        """The writer to open blocks with, or a refusal a reader can act on.

        The default is probed by importing what it will import anyway, here,
        where nothing has been created yet — so an install without molnex fails
        with an answer instead of with a bare missing-module error halfway
        through a directory tree.
        """
        if factory is not None:
            return factory
        try:
            for module in _WRITER_MODULES:
                import_module(module)
        except ImportError as error:
            raise ImportError(
                f"prepare writes molnex 'molix.block/1' blocks and this environment cannot "
                f"import them ({error}). Install the publishable half with the 'prepare' "
                "extra (pip install 'molhub[prepare]'), and molnex itself from a source "
                "checkout — it is not on PyPI — or point MOLNEX_SRC at its 'src' directory. "
                "Passing writer_factory= a writer of your own is the other way out; nothing "
                "was written."
            ) from error
        return MolnexBlockWriter


def prepare(
    name: str,
    *,
    split: str,
    output_dir: str | Path,
    revision: str | None = None,
    registry: Registry | None = None,
    hub: ArtifactHub | None = None,
    writer_factory: BlockWriterFactory | None = None,
    provenance: Mapping[str, object] | None = None,
    disk_budget: int = DEFAULT_BUDGET_BYTES,
) -> PreparedBlocks:
    """Materialize one split of one dataset as sealed blocks under *output_dir*.

    A thin delegation to
    :meth:`~molhub.loader.builder.DatasetBuilder.block_export`: the export is the
    type that does the work, and composing describe → export → consume stays the
    caller's job.

    Args:
        name: The dataset in HuggingFace spelling, e.g. ``"themol/torsion-scan"``.
        split: Which split to materialize. Blocks are split-pure, so this is
            required: a directory holding two splits is one nobody can sample
            from without re-deriving which is which.
        output_dir: Directory the sealed block roots are created under.
        revision: Which version to pin; ``None`` takes the newest declared.
        registry: Where manifests come from.
        hub: Where bytes come from.
        writer_factory: How one block is opened. ``None`` resolves molnex's own
            writer and refuses with a message naming the ``prepare`` extra and
            the ``MOLNEX_SRC`` escape hatch when molnex is not importable.
        provenance: Opaque provenance recorded in every block; ``None`` states
            molhub's own, carrying the keys the block format requires.
        disk_budget: How many bytes of fetched files the walk behind the export
            may keep on local disk at once.

    Returns:
        The :class:`~molhub.conveyor.prepare.PreparedBlocks` evidence for every
        root that was sealed — where it is, which split it holds, how many units
        and frames, and the digest its own manifest states. molnex reads the
        directory back with ``BlockDataset.load_from_disk(output_dir)``.

    Raises:
        KeyError: If *split* is not one of the dataset's declared splits.
        ValueError: If the dataset is published as whole files, which there is
            no way to materialize a piece at a time.
        UnsupportedRecordError: If ``molix.block/1`` routes none of the
            dataset's targets, so exporting it could only drop them. Nothing is
            fetched and nothing is created before that is known.
        ImportError: If molnex is not importable and no writer was injected.
            Nothing is written before that is known.
    """
    # Imported here because `builder` imports this module for `BlockExport`: the
    # entry lives beside the type it delegates to, and the delegation runs one
    # layer up from it.
    from molhub.loader.builder import DatasetBuilder

    return (
        DatasetBuilder(name, revision=revision, registry=registry, hub=hub)
        .block_export(
            split,
            output_dir=output_dir,
            writer_factory=writer_factory,
            provenance=provenance,
            disk_budget=disk_budget,
        )
        .run()
    )
