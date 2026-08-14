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

No network, no environment variable, no disk-layout decision, and stdlib plus
``molhub`` only: the caller supplies the ledger's path, unpack / prepare /
``READY`` and the byte-bounded queue belong to the stages after this one, and
none of them invents its own memory.
"""

from molhub.conveyor.block import (
    BlockId,
    BlockState,
    ConveyorError,
    IllegalTransition,
    InvalidBlockId,
    UnknownBlockState,
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
]
