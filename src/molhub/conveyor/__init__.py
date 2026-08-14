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

:class:`~molhub.conveyor.splits.SplitTable` is the split assignment of record,
loaded only once the derivation's own ``metadata.json`` sha256 agrees.

The prepare stage is the CPU half that turns those verified bytes into training
blocks: :class:`~molhub.conveyor.encoder.THEMolUnitEncoder` maps one THEMol
record onto one whole :class:`~molhub.conveyor.encoder.RawUnit` of numpy columns,
and :class:`~molhub.conveyor.prepare.PrepareJob` routes each unit to its
molecule's split and feeds it — whole, never in pieces — to a block writer,
returning the evidence a ``READY`` record needs::

    table = SplitTable.from_identity(splits_root)      # provenance-verified
    prepared = PrepareJob(
        shard,
        encoder=THEMolUnitEncoder(task="torsion-scan"),
        split_of={identity: table.split_of(identity) for identity in identities},
        writer_factory=MolnexBlockWriter,
        root=blocks_root,
        name="themol-torsion-scan-shard-000",
        provenance=provenance,
    ).run()
    prepared.blocks[0].block_digest   # what the READY record quotes

molnex enters through :class:`~molhub.conveyor.prepare.MolnexBlockWriter` alone,
which imports ``molix`` lazily, so the base install stays torch-free.

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
"""

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
    MolnexBlockWriter,
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
    SplitTable,
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

__all__ = [
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
    "SplitTable",
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
    "MolnexBlockWriter",
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
