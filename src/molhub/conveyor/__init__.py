"""Conveyor bookkeeping — which block, and what has already happened to it.

The conveyor cannot fetch, prepare or reclaim anything until it can name a
block and say what its history is, across a crash. This package is that
foundation and nothing else: a validated :class:`~molhub.conveyor.block.BlockId`,
a closed four-member :class:`~molhub.conveyor.block.BlockState` whose legality
table makes an impossible history unrepresentable, and one append-only
:class:`~molhub.conveyor.ledger.Ledger` that replays into a mapping of block to
state, discards a line torn by a kill mid-append, and grants TTL leases as
ordinary records rather than filesystem locks::

    from datetime import timedelta

    from molhub.conveyor import BlockId, BlockState, Ledger

    ledger = Ledger(root / "conveyor.jsonl", actor="plan:train-epoch-3")
    block = BlockId("dataset:themol/torsion-scan@1", "torsion", "train", "shard-003")

    ledger.append(block, BlockState.REMOTE)
    ledger.append(block, BlockState.DOWNLOADING)
    ledger.append(block, BlockState.READY, size_bytes=2_000_000_000)

    ledger.lease([block], ttl=timedelta(minutes=30))
    ledger.replay()[block]          # BlockState.READY
    ledger.active_leases()[block]   # ("plan:train-epoch-3",)

On top of that memory sit the REMOTE tier's two questions — *what blocks exist,
how big are they, and what must their bytes hash to*, and *how do those bytes
get here without a corrupt shard being mistaken for a good one*.
:class:`~molhub.conveyor.roster.BlockRoster` answers the first by **projecting**
the registry manifest molhub already ships, so there is no second index to
drift; :class:`~molhub.conveyor.transfer.ShardTransfer` answers the second by
leasing the block, re-verifying every delivered file against the manifest
digest, deleting bytes that disagree, and failing with a typed aggregate error
rather than letting an unverified block advance::

    roster = BlockRoster(Manifest.from_path(path), collection.role("electrostatic"))
    roster.total_bytes()                    # what this role's REMOTE tier costs
    ShardTransfer(hub, ledger).transfer(roster.blocks()[0])   # verified local path

:class:`~molhub.conveyor.splits._SplitTable` is the split assignment of record,
loaded only once the derivation's own ``metadata.json`` sha256 agrees. It is
package-internal (``hf-facade-03-builder-info`` D9): its two callers are the
prepare stage below and :class:`~molhub.loader.builder.DatasetBuilder`, both
inside this distribution, so it is imported by its private name rather than
exported for anyone to construct.

The prepare stage is the CPU half that turns those verified bytes into training
blocks: :class:`~molhub.conveyor.encoder.THEMolUnitEncoder` maps one THEMol
record onto one whole :class:`~molhub.conveyor.encoder.RawUnit` of numpy columns,
and :class:`~molhub.conveyor.prepare.PrepareJob` routes each unit to its
molecule's split and feeds it — whole, never in pieces — to a block writer,
returning the evidence a ``READY`` record needs::

    table = _SplitTable.from_identity(splits_root)     # provenance-verified
    prepared = PrepareJob(
        shard,
        encoder=THEMolUnitEncoder(task="torsion-scan"),
        split_of={identity: table.split_of(identity) for identity in identities},
        writer_factory=YourBlockWriter,   # no default; bring a writer
        root=blocks_root,
        name="themol-torsion-scan-shard-000",
        provenance=provenance,
    ).run()
    prepared.blocks[0].block_digest   # what the READY record quotes

``writer_factory`` has **no default**. The caller brings a writer.
:class:`~molhub.conveyor.prepare.BlockWriterLike` /
:class:`~molhub.conveyor.prepare.BlockWriterFactory` are that seam. This
package does not import a block writer, and a base install stays torch-free.

The residency half decides what stays on local disk and what the run can prove
it saw. :class:`~molhub.conveyor.tier.TierStore` bounds one subdirectory in
bytes and evicts in the order the consumer's
:class:`~molhub.conveyor.tier.VisitOrder` implies — planning the whole deletion
before unlinking anything, and never at the cost of a live lease;
:class:`~molhub.conveyor.backpressure.ByteBoundedQueue` and
:class:`~molhub.conveyor.backpressure.PrepareWorkers` bound the handoff between
stages in bytes and run the prepare jobs in processes; and
:class:`~molhub.conveyor.coverage.CoverageReport` plus
:class:`~molhub.conveyor.coverage.ReadyBlocks` report what was seen and what can
be consumed right now::

    blocks = TierStore(subdir="conveyor/blocks", budget_bytes=40_000_000_000, ledger=ledger)
    blocks.admit(block, nbytes=2_000_000_000)
    blocks.evict_until(2_000_000_000, plan=VisitOrder(order, cursor=7))

    CoverageReport.replay(ledger.records(), units_by_block=units).fraction(total)
    ReadyBlocks(blocks).metadata()[0].block_digest   # copied, never computed

No network, no environment variable of its own and no disk-layout decision: the
caller supplies the ledger's path, the tier root comes from
:class:`~molhub.sources.blobs.BlobStore`, the bookkeeping half is stdlib plus
``molhub``, and the prepare half adds numpy.

Two of those caller decisions are the *same* decision everywhere, and are stated
here so that two callers cannot make it differently: :func:`default_ledger_path`
is where the bookkeeping file sits under a molhub home, and
:data:`DEFAULT_BUDGET_BYTES` is the rolling working set one tier is allowed. Both
were private to ``src/molhub/cli.py`` while the command line was their only
caller; ``hf-facade-04-streaming-prepare`` (D7) added the second — a streaming
walk that leases and releases the very blocks ``molhub cache coverage`` replays —
and two default paths would have silently desynchronised those leases, which is
the ledger's own R1 hazard.
"""

from pathlib import Path

from molhub.conveyor.backpressure import (
    ByteBoundedQueue,
    DuplicateReservation,
    JobRunner,
    PrepareWorkers,
    QueueError,
    QueueOversized,
    QueueTimeout,
    UnknownReservation,
    WorkerRefusal,
)
from molhub.conveyor.block import (
    BlockId,
    BlockState,
    ConveyorError,
    IllegalTransition,
    InvalidBlockId,
    UnknownBlockState,
)
from molhub.conveyor.coverage import (
    BlockMetadata,
    BlockNotSealed,
    CoveragePoint,
    CoverageReport,
    ReadyBlocks,
    UnsupportedBlockFormat,
)
from molhub.conveyor.encoder import (
    RawUnit,
    THEMolUnitEncoder,
)
from molhub.conveyor.errors import (
    BlockFormatError,
    IncompleteProvenanceError,
    IncompleteRecordError,
    PrepareError,
    UnroutableUnitError,
    UnsupportedRecordError,
)
from molhub.conveyor.ledger import (
    Clock,
    InvalidRecord,
    LeaseRecord,
    Ledger,
    LedgerCorruption,
    LedgerRecord,
    SystemClock,
)
from molhub.conveyor.prepare import (
    BlockWriterFactory,
    BlockWriterLike,
    PreparedBlock,
    PreparedBlocks,
    PrepareJob,
)
from molhub.conveyor.roster import (
    BlockRoster,
    NoShardArtifacts,
    RemoteBlock,
    RoleSourceMismatch,
    RosterError,
    UnsizedBlock,
    UnverifiableBlock,
)
from molhub.conveyor.splits import (
    SplitProvenance,
    SplitProvenanceMismatch,
)
from molhub.conveyor.tier import (
    BlockLedger,
    BlockNotResident,
    BlockUnevictable,
    DerivedLayout,
    IncompleteDerivation,
    TierError,
    TierOverBudget,
    TierStore,
    VisitOrder,
)
from molhub.conveyor.transfer import (
    Backoff,
    ExponentialBackoff,
    PersistentDigestMismatch,
    ShardTransfer,
    TransferAttempt,
    TransferError,
    TransferLedger,
)

#: Where the conveyor keeps its bookkeeping under a molhub home, as path
#: segments. Not under ``files/``, which stays the cross-client cache layout the
#: TypeScript client reads.
_LEDGER_SEGMENTS = ("conveyor", "ledger.jsonl")

#: The strategy's per-tier rolling working set, in bytes, stated once
#: (``.claude/notes/streaming-data-tiers.md``). It is what ``molhub cache
#: status`` measures a tier against and what a streaming walk keeps resident.
DEFAULT_BUDGET_BYTES = 40_000_000_000


def default_ledger_path(home: str | Path) -> Path:
    """The one conveyor ledger under *home*.

    A free function rather than a method because it belongs to no object a
    caller already holds: :class:`~molhub.sources.blobs.BlobStore` owns
    ``files/`` and :class:`~molhub.conveyor.tier.TierStore` owns a tier
    directory, while this is the file both the command line and the streaming
    walk must agree on before either has constructed anything.

    Args:
        home: The molhub home — ``config.home_dir``, or whatever ``--home`` names.

    Returns:
        ``<home>/conveyor/ledger.jsonl``. The path, not the file: a
        :class:`~molhub.conveyor.ledger.Ledger` creates its parent on the first
        write, so asking for it costs nothing and creates nothing.
    """
    return Path(home).joinpath(*_LEDGER_SEGMENTS)


__all__ = [
    "DEFAULT_BUDGET_BYTES",
    "default_ledger_path",
    "BlockId",
    "BlockState",
    "ConveyorError",
    "IllegalTransition",
    "InvalidBlockId",
    "UnknownBlockState",
    "Clock",
    "SystemClock",
    "LedgerRecord",
    "LeaseRecord",
    "Ledger",
    "InvalidRecord",
    "LedgerCorruption",
    "RemoteBlock",
    "BlockRoster",
    "RosterError",
    "NoShardArtifacts",
    "UnsizedBlock",
    "UnverifiableBlock",
    "RoleSourceMismatch",
    "SplitProvenance",
    "SplitProvenanceMismatch",
    "TransferLedger",
    "Backoff",
    "ExponentialBackoff",
    "TransferAttempt",
    "ShardTransfer",
    "TransferError",
    "PersistentDigestMismatch",
    "RawUnit",
    "THEMolUnitEncoder",
    "BlockWriterLike",
    "BlockWriterFactory",
    "PreparedBlock",
    "PreparedBlocks",
    "PrepareJob",
    "PrepareError",
    "UnsupportedRecordError",
    "IncompleteRecordError",
    "UnroutableUnitError",
    "IncompleteProvenanceError",
    "BlockFormatError",
    "BlockLedger",
    "VisitOrder",
    "DerivedLayout",
    "TierStore",
    "TierError",
    "TierOverBudget",
    "BlockUnevictable",
    "BlockNotResident",
    "IncompleteDerivation",
    "ByteBoundedQueue",
    "QueueError",
    "QueueTimeout",
    "QueueOversized",
    "DuplicateReservation",
    "UnknownReservation",
    "JobRunner",
    "PrepareWorkers",
    "WorkerRefusal",
    "CoveragePoint",
    "CoverageReport",
    "BlockMetadata",
    "ReadyBlocks",
    "BlockNotSealed",
    "UnsupportedBlockFormat",
]
