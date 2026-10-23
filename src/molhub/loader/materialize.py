"""One split of one dataset, materialized as sealed blocks.

:func:`prepare` is the doorway and :class:`BlockExport` is the work — the entry
sits beside the type it delegates to, and ``molhub/__init__`` re-exports it, so
``from molhub import prepare`` reaches the same object. The export reads the
split's records through the same bounded walk :mod:`molhub.loader.streaming`
yields — so materializing a dataset of tens of GiB to several TiB costs one file
of disk at a time — encodes each record whole, and hands it to
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

**Fail closed with no writer** (ac-005). ``writer_factory`` has no default.
Omitting it raises :class:`ValueError` **before anything is created**. A
half-written block directory is not a smaller failure than none.

**Two of the preconditions are public** (reachability wave, ruling 6).
:meth:`BlockExport.refuse_unroutable` and :meth:`BlockExport.resolve_writer` are
decidable from the arguments alone, and a caller that can reach them separately
can ask them *before* it pays for anything else — which is what
:meth:`~molhub.loader.builder.TableBackedSplits.block_export` does, so a dataset
that cannot be exported at all never provokes "the split table is not here".
They are the same two checks the constructor makes, so asking early costs an
already-resolved answer rather than a second implementation.

**A dataset whose targets have no :class:`~molhub.conveyor.encoder.RawUnit`
column is refused, not exported.**
:class:`~molhub.conveyor.encoder.THEMolUnitEncoder` refuses the subset label
``"mbis"`` because ``RawUnit`` defines no columns for its atom-level
electrostatics targets, and labelling those units with the *collection role*
they are published under (``electrostatic``) is a second name for the same
records rather than a second answer: an export that succeeded on them would
write the geometry and topology and **drop** the per-atom charges, volumes,
dipoles, quadrupoles and Slater parameters the dataset exists for. So
:class:`BlockExport` puts the question to the encoder's own constructor — the
one place those columns are stated — with the subset label its coordinate
names, and re-raises the refusal in this layer's vocabulary before anything is
fetched or created. Until ``RawUnit`` grows columns for those targets, they are
read with ``load_dataset(name)`` and this refusal stands.

Reference:
    ``.claude/specs/hf-facade-04-streaming-prepare.md`` § Design (D8), ac-004
    and ac-005, under the 2026-08-15 operator override recorded in
    ``.claude/notes/notes.md`` (``mol:note:topic:hf-style-api``).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from molpy import Frame

from molhub.conveyor import DEFAULT_BUDGET_BYTES
from molhub.conveyor.encoder import THEMolUnitEncoder
from molhub.conveyor.errors import UnsupportedRecordError
from molhub.conveyor.prepare import BlockWriterFactory, PreparedBlocks, PrepareJob
from molhub.conveyor.splits import _SplitTable
from molhub.coordinate import Coordinate
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.themol import THEMOL_UNITS
from molhub.registry import Registry

__all__ = ["SplitRouting", "BlockExport", "prepare"]


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

    def __init__(self, records: Iterable[Sequence[Frame]], *, table: _SplitTable) -> None:
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

    def __iter__(self) -> Iterator[Sequence[Frame]]:
        """Yield every record, resolving its molecule's split first."""
        for record in self._records:
            self._resolve(record)
            yield record

    def _resolve(self, record: Sequence[Frame]) -> None:
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
    def _smiles(record: Sequence[Frame]) -> str | None:
        """The mapped SMILES of *record*, or ``None`` when it carries none.

        Every record is a ``Sequence[Frame]``; the first frame states the mapped
        SMILES. A record with none is left for the encoder to refuse, which is
        where that diagnosis already lives.
        """
        frames = tuple(record)
        if not frames:
            return None
        meta = getattr(frames[0], "meta", None) or {}
        value = getattr(meta.get(_SMILES), "value", meta.get(_SMILES))
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
            layer's own, which carries the four provenance keys a block records.

    Raises:
        UnsupportedRecordError: If ``RawUnit`` has no column for this
            dataset's targets, so exporting it could only drop them. Raised at
            construction, before any directory exists and before a byte is read.
        ImportError: If *writer_factory* is ``None`` and molnex or torch cannot
            be imported. Raised at construction, before any directory exists.
        InvalidCoordinate: If *source* is not a version-pinned coordinate.
    """

    def __init__(
        self,
        records: Iterable[Sequence[Frame]],
        *,
        split_of: Mapping[str, str],
        task: str,
        source: str,
        output_dir: str | Path,
        writer_factory: BlockWriterFactory | None = None,
        provenance: Mapping[str, object] | None = None,
    ) -> None:
        self._coordinate = Coordinate.parse(source)
        self.refuse_unroutable(self._coordinate)
        self._records = records
        self._split_of = split_of
        self._task = task
        self._output_dir = Path(output_dir)
        self._writer_factory = self.resolve_writer(writer_factory)
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
                a block records; raised before a writer is opened.
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

    @staticmethod
    def refuse_unroutable(coordinate: Coordinate) -> None:
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
        that first had to read tens of GiB to several TiB of published files
        would not be one, and a caller holding only a coordinate can ask before
        it builds anything.

        Args:
            coordinate: The **resolved** coordinate of the dataset to export.

        Raises:
            UnsupportedRecordError: If the encoder refuses this dataset's subset
                label, restated with the coordinate, the format whose column
                routes are missing, and what exporting anyway would cost.

                Raised ``from None``: the encoder's own refusal is this one's
                *input*, not a second failure to correlate. Chaining it prints
                "the direct cause of the following exception" and then the same
                sentence twice — once in the conveyor's vocabulary, once in this
                layer's — and the reader has to read both to find they say the
                same thing. Suppressing the implicit context too is what makes
                that one traceback rather than one plus a "during handling of
                the above exception" block.
        """
        try:
            THEMolUnitEncoder(task=coordinate.name)
        except UnsupportedRecordError:
            raise UnsupportedRecordError(
                f"{coordinate.canonical} cannot be materialized: its atom-level "
                "electrostatics targets (atomic_charge, atomic_volume, the dipole and "
                "quadrupole components and the per-atom Slater parameters) have no column "
                "on RawUnit. Exporting it anyway would write the geometry and topology and "
                "silently drop every target the dataset exists for, so nothing was written "
                "and nothing was created. The fix is a RawUnit column for those targets, "
                "not a flag here; until it exists, read the targets with "
                "load_dataset(name)."
            ) from None

    def _own_provenance(self) -> dict[str, object]:
        """The four provenance keys a block records, stated by this layer.

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
    def resolve_writer(factory: BlockWriterFactory | None) -> BlockWriterFactory:
        """The writer to open blocks with, or a refusal a reader can act on.

        There is no default. A caller holding nothing but the argument can ask
        before it builds anything; a caller that already has a writer gets it
        back untouched.

        Args:
            factory: The caller's writer. There is no default.

        Returns:
            The factory blocks will be opened with.

        Raises:
            ValueError: *factory* is ``None``. The message names ``writer_factory``.
        """
        if factory is not None:
            return factory
        raise ValueError(
            "prepare has no default writer. Pass writer_factory= a writer of "
            "your own; nothing was written."
        )


def prepare(
    name: str,
    *,
    output_dir: str | Path,
    revision: str | None = None,
    disk_budget: int = DEFAULT_BUDGET_BYTES,
    writer_factory: BlockWriterFactory | None = None,
    provenance: Mapping[str, object] | None = None,
    registry: Registry | None = None,
    hub: ArtifactHub | None = None,
) -> PreparedBlocks:
    """Materialize one dataset as sealed blocks under *output_dir*.

    Args:
        name: HuggingFace spelling, e.g. ``"themol/torsion-scan"``.
        output_dir: Directory the sealed block roots are created under.
        revision: Which version to pin; ``None`` takes the newest declared.
        disk_budget: Bytes of fetched files the walk may keep on disk at once.
        writer_factory: How one block is opened.
        provenance: Opaque provenance recorded in every block.
        registry: Where registry YAML comes from.
        hub: Where bytes come from.

    Raises:
        ValueError: If the dataset is published as whole files.
        UnsupportedRecordError: If ``RawUnit`` has no column for the targets.
        ImportError: If molnex is not importable and no writer was injected.
    """
    from molhub.loader.builder import DatasetBuilder

    return (
        DatasetBuilder(name, revision=revision, registry=registry, hub=hub)
        .block_export(
            output_dir=output_dir,
            writer_factory=writer_factory,
            provenance=provenance,
            disk_budget=disk_budget,
        )
        .run()
    )
