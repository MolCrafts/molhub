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

No network, no environment variable, no disk-layout decision, and stdlib plus
``molhub`` only: the caller supplies the ledger's path, and the enumeration,
transfer and residency stages build on top of this memory rather than each
inventing their own.
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
]
