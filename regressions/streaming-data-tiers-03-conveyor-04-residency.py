#!/usr/bin/env python
"""Regression: byte-budgeted tiers, a byte-bounded handoff, and coverage replayed from the ledger.

Exercises the residency half of the conveyor
(``streaming-data-tiers-03-conveyor-04-residency``) offline, inside a temporary
directory this script creates, through the public :mod:`molhub.conveyor` surface
only. One object plays the conveyor **driver** of the spec's § 1b: it owns both
:class:`~molhub.conveyor.TierStore`\\ s, holds the only
:class:`~molhub.conveyor.Ledger` handle, and is therefore the single transition
writer. The prepare workers that "sealed" the fixture blocks write no ledger
record — which is exactly why leg 6's counts are reproducible from the file
alone, and why one block (``b04``) is sealed *on disk* while the ledger has not
yet been told: ``ReadyBlocks`` answers "what can be consumed right now",
``CoverageReport`` answers "what has this run seen", and the two are allowed to
disagree by one collection.

The seven legs are the spec's § "Testing strategy" walkthrough, in order:

1. Two published shards in the raw tier (``split=None``) and five hand-written
   sealed ``molix.block/1`` manifests for the derived blocks; blocks tier budget
   3 000 000 B, raw tier budget 2 000 000 B, every block declared 1 000 000 B.
2. Admit ``b00``/``b01``/``b02``; ``b00``/``b01`` CONSUMED, ``b02`` READY and
   leased; ``VisitOrder((b00..b04), cursor=2)``; ``evict_until(1_000_000)`` is
   **``("b00",)``** and leaves 2 000 000 B resident.
3. Admit ``b03``, pin ``b01``: ``evict_until(1_000_000)`` raises
   :class:`~molhub.conveyor.TierOverBudget` with residency still **3 000 000 B**,
   all three entries (``b01`` pinned, ``b02`` leased, ``b03`` not CONSUMED) still
   on disk with their manifests intact, and **not one ledger record written** —
   the plan is built and checked before anything is unlinked.
4. Release ``b02``'s lease, consume it, advance the cursor:
   ``evict_until(1_000_000)`` is **``("b02",)``**; admit ``b04``. Peak
   blocks-tier residency never exceeds **3 000 000 B**; the raw tier sits at
   **2 000 000 B** across every blocks-tier eviction and only drops to
   **1 000 000 B** when its own shard is released after the prepare that
   consumed it (I3) — two budgets, no shared counter.
5. ``ByteBoundedQueue(capacity_bytes=2_000_000)``: the ``held_bytes`` trace
   **(1 000 000, 2 000 000, 2 000 000, 2 000 000, 1 000 000, 2 000 000)** across
   reserve, reserve, refused ``timeout=0`` probe, ``take``, ``release``, reserve
   — ``take`` hands the item on without freeing a byte — and a 3 000 000 B
   reservation refused with :class:`~molhub.conveyor.QueueOversized`.
6. :meth:`~molhub.conveyor.CoverageReport.replay` over the ledger this run
   actually wrote: ``bytes_downloaded == 5_000_000`` (five network attempts for
   two shards — a retried fetch counts twice), ``bytes_prepared == 5_000_000``,
   ``bytes_evicted == 2_000_000`` (derived ``b00``/``b02``),
   ``bytes_raw_released == 1_000_000`` (``shard-000``, ``split=None``),
   ``blocks_seen`` the five ids that reached READY,
   ``blocks_consumed == ("b00", "b01", "b02")``, ``units_seen == 12``,
   ``fraction(8) == 0.375`` and the cumulative timeline ``((1, 3), (2, 5),
   (3, 8))``. Timestamps are asserted **monotone**, never pinned to a literal.
7. :meth:`~molhub.conveyor.ReadyBlocks.metadata` for ``b03``: ``split ==
   "train"``, ``units == 2``, ``frames == 8``, ``task_names ==
   ("equilibrium", "torsion")`` and a ``block_digest`` equal to the literal
   this script wrote into the fixture manifest — copied, never computed.

Determinism: no network, no environment variable, no wall clock (a stepping
:class:`~molhub.conveyor.Clock` supplies every instant), no subprocess and no
third-party oracle. Two runs print identical bytes.

Provenance of the goldens (this repo's spec and this file's own fixture, no
external tool runs):

* Every eviction sequence, byte total, queue trace, coverage count and
  ``b03`` metadata field is the literal pinned by
  ``.claude/specs/streaming-data-tiers-03-conveyor-04-residency.md``
  § "Testing strategy" steps 1-7 and by ``ac-014``.
* ``block_digest`` / ``digests`` values are arbitrary 64-hex literals authored
  here and written into the fixture manifests; they are the sha256 of nothing
  on disk, which is what makes "digests are copied, never computed" a checkable
  claim rather than a promise.
* ``units_by_block`` is the caller's mapping (``-02``'s roster in production):
  the derived counts are read off the same fixture records that produce the
  manifests, so the roster and the manifest cannot silently disagree here.

tool: python
command: python regressions/streaming-data-tiers-03-conveyor-04-residency.py
date: 2026-08-14
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from molhub.conveyor import (  # noqa: E402
    BlockId,
    BlockLedger,
    BlockState,
    ByteBoundedQueue,
    Clock,
    CoverageReport,
    Ledger,
    QueueOversized,
    QueueTimeout,
    ReadyBlocks,
    TierOverBudget,
    TierStore,
    VisitOrder,
)

# The residency half is bookkeeping over JSON and directories; molnex owns the
# block *reader*. If either name ever reaches sys.modules through this import,
# the torch-free sampler handoff has stopped being torch-free.
assert "torch" not in sys.modules, "molhub.conveyor pulled torch into the process"
assert "molix" not in sys.modules, "molhub.conveyor pulled molix into the process"

# ---------------------------------------------------------------------------
# Budgets and the fixture corpus
# ---------------------------------------------------------------------------

_SOURCE = "dataset:themol/torsion-scan@1"
_TASK = "torsion"
_ACTOR = "plan:residency-walkthrough"

_BLOCKS_SUBDIR = "conveyor/blocks"
_RAW_SUBDIR = "conveyor/raw"

#: Every block in this walkthrough declares the same size, so a budget reads as
#: a block count and no assertion below has to do arithmetic in its head.
_BLOCK_BYTES = 1_000_000
_BLOCKS_BUDGET = 3_000_000
_RAW_BUDGET = 2_000_000

#: The queue bounds what may be resident in the raw tier, so it carries that
#: tier's budget: two shards in flight, never three.
_QUEUE_CAPACITY = 2_000_000
_OVERSIZED_BYTES = 3_000_000

#: The corpus denominator ``-02``'s roster declares for this role. This window
#: plans five of those blocks; coverage is honest about the other three.
_CORPUS_BLOCKS = 8

_LEASE_TTL = timedelta(hours=1)
_START = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
_STEP = timedelta(seconds=1)

_TASK_NAMES = ("equilibrium", "torsion")


def _derived(name: str, split: str) -> BlockId:
    """One split-pure derived block: the prepare stage's output."""
    return BlockId(_SOURCE, _TASK, split, name)


def _shard(name: str) -> BlockId:
    """One published shard, whose split cannot be known without opening it."""
    return BlockId(_SOURCE, _TASK, None, name)


B00 = _derived("b00", "train")
B01 = _derived("b01", "train")
B02 = _derived("b02", "train")
B03 = _derived("b03", "train")
B04 = _derived("b04", "val")

R0 = _shard("shard-000")
R1 = _shard("shard-001")
#: Two more shards the plan will reach later. They never land: the queue's
#: capacity is precisely what has kept them out of the raw tier so far.
R2 = _shard("shard-002")
R3 = _shard("shard-003")

#: The visit plan the consumer published; ``cursor`` advances in leg 4.
_PLAN_ORDER = (B00, B01, B02, B03, B04)


@dataclass(frozen=True)
class _Sealed:
    """One hand-written sealed block, as a prepare worker left it on disk.

    Attributes:
        block: The block this directory holds.
        units: Sampling units the manifest declares.
        frames: Rows in the ``frame`` space, which is what a batch counts.
        block_digest: The producer's digest, arbitrary here — molhub copies it.
        column_digests: The producer's per-column digests, likewise.
    """

    block: BlockId
    units: int
    frames: int
    block_digest: str
    column_digests: Mapping[str, str]

    def document(self) -> dict[str, object]:
        """The ``molix.block/1`` manifest this block's directory carries.

        Returns:
            The object ``molnex:src/molix/store/block.py`` writes, hand-built:
            molhub reads eight of these fields as JSON and validates two, and
            never opens a column.
        """
        return {
            "format": "molix.block/1",
            "schema_version": 1,
            "columns": {
                "frame.pos": {"dtype": "float32", "shape": [3], "space": "frame"},
                "topology.z": {"dtype": "int8", "shape": [], "space": "topology"},
            },
            "split": self.block.split,
            "task_names": list(_TASK_NAMES),
            "units": self.units,
            "rows": {"frame": self.frames, "topology": self.frames * 3, "molecule": self.units},
            "provenance": {
                "source": _SOURCE,
                "generator": "molhub.conveyor.prepare.PrepareJob",
                "created_at": "2026-08-14T10:00:00+00:00",
                "units": "molecule",
            },
            "digests": dict(self.column_digests),
            "sealed": True,
            "block_digest": self.block_digest,
        }


#: Five fake block directories' worth of manifest, one per derived block. The
#: digests are 64-hex literals authored here: nothing under the fixture root
#: hashes to any of them, so a recomputation anywhere in molhub would fail leg 7
#: rather than pass it by luck.
SEALED = (
    _Sealed(
        B00,
        units=3,
        frames=12,
        block_digest="1f2e3d4c5b6a79887766554433221100" * 2,
        column_digests={"frame.pos": "a1" * 32, "topology.z": "b2" * 32},
    ),
    _Sealed(
        B01,
        units=2,
        frames=8,
        block_digest="2a3b4c5d6e7f80918273645546372819" * 2,
        column_digests={"frame.pos": "c3" * 32, "topology.z": "d4" * 32},
    ),
    _Sealed(
        B02,
        units=3,
        frames=12,
        block_digest="3c4d5e6f70819a2b3c4d5e6f70819a2b" * 2,
        column_digests={"frame.pos": "e5" * 32, "topology.z": "f6" * 32},
    ),
    _Sealed(
        B03,
        units=2,
        frames=8,
        block_digest="4d5e6f708192a3b4c5d6e7f809112233" * 2,
        column_digests={"frame.pos": "0a" * 32, "topology.z": "1b" * 32},
    ),
    _Sealed(
        B04,
        units=2,
        frames=8,
        block_digest="5e6f708192a3b4c5d6e7f80911223344" * 2,
        column_digests={"frame.pos": "2c" * 32, "topology.z": "3d" * 32},
    ),
)

_BY_BLOCK: Mapping[BlockId, _Sealed] = {sealed.block: sealed for sealed in SEALED}

#: What ``-02``'s roster says each block carries. The derived counts come off
#: the same records that produce the manifests, so roster and manifest agree by
#: construction; the two shards' counts are the roster's own.
UNITS_BY_BLOCK: Mapping[BlockId, int] = {
    R0: 2,
    R1: 2,
    **{sealed.block: sealed.units for sealed in SEALED},
}

# ---------------------------------------------------------------------------
# Goldens — see the module docstring for provenance
# ---------------------------------------------------------------------------

_FIRST_EVICTION = ("b00",)
_SECOND_EVICTION = ("b02",)

_HELD_BYTES_TRACE = (1_000_000, 2_000_000, 2_000_000, 2_000_000, 1_000_000, 2_000_000)

_BYTES_DOWNLOADED = 5_000_000
_BYTES_PREPARED = 5_000_000
_BYTES_EVICTED = 2_000_000
_BYTES_RAW_RELEASED = 1_000_000
_BLOCKS_SEEN = ("shard-000", "b00", "b01", "b02", "b03")
_BLOCKS_CONSUMED = ("b00", "b01", "b02")
_UNITS_SEEN = 12
_FRACTION = 0.375
_TIMELINE = ((1, 3), (2, 5), (3, 8))

#: Every transition the driver and the two tiers write, together.
_TRANSITIONS = 20


class StepClock:
    """A :class:`~molhub.conveyor.Clock` that advances one fixed step per read.

    Determinism without a frozen instant: every record this run writes gets a
    distinct, reproducible timestamp, so leg 6 can assert the coverage timeline
    is **monotone** — the property the spec pins — without pinning a literal
    that would turn a scheduling change into a golden diff.

    Args:
        start: The first instant handed out; must be timezone-aware.
        step: How far the clock moves between reads.
    """

    def __init__(self, start: datetime, step: timedelta) -> None:
        self._next = start
        self._step = step

    def now(self) -> datetime:
        """Return the next instant and advance."""
        moment = self._next
        self._next = moment + self._step
        return moment


class Driver:
    """The conveyor driver: both tiers, one ledger, and every transition.

    The spec's § 1b discharged operationally — the one object that owns the
    :class:`~molhub.conveyor.TierStore`\\ s is the ledger's only transition
    writer. Prepare workers in this script "run" by leaving a sealed manifest on
    disk and never touch the ledger, which is what lets leg 6 derive its counts
    from the file instead of from process memory.

    Args:
        root: The conveyor root; both tiers hang off it in their own
            subdirectory, and the ledger file sits beside them.
    """

    def __init__(self, root: Path) -> None:
        self.clock = StepClock(_START, _STEP)
        self.ledger = Ledger(root / "conveyor.jsonl", clock=self.clock, actor=_ACTOR)
        self.raw = TierStore(root, subdir=_RAW_SUBDIR, budget_bytes=_RAW_BUDGET, ledger=self.ledger)
        self.blocks = TierStore(
            root, subdir=_BLOCKS_SUBDIR, budget_bytes=_BLOCKS_BUDGET, ledger=self.ledger
        )
        self.samples: list[int] = []

    def record(self, block: BlockId, state: BlockState, *, size_bytes: int | None = None) -> None:
        """Append one transition. Every driver-side fact goes through here."""
        self.ledger.append(block, state, size_bytes=size_bytes)

    def observe(self) -> int:
        """Sample the blocks tier's residency, for the peak assertion.

        Returns:
            Bytes currently charged to the blocks tier.
        """
        resident = self.blocks.resident_bytes
        self.samples.append(resident)
        return resident

    def seal(self, sealed: _Sealed, *, ready: bool = True) -> Path:
        """Admit *sealed*'s block, leave a worker's sealed manifest in it.

        Args:
            sealed: The fixture block to admit and write.
            ready: Whether the driver has collected the worker's outcome yet.
                ``False`` models the sealed-on-disk, not-yet-recorded gap the
                single-writer rule creates.

        Returns:
            The block's directory in the blocks tier.
        """
        directory = self.blocks.admit(sealed.block, nbytes=_BLOCK_BYTES)
        (directory / "manifest.json").write_text(
            json.dumps(sealed.document(), indent=2) + "\n", encoding="utf-8"
        )
        (directory / "frame.pos").write_bytes(b"column bytes molhub never opens")
        if ready:
            self.record(sealed.block, BlockState.READY, size_bytes=_BLOCK_BYTES)
        self.observe()
        return directory

    def raw_state(self) -> tuple[int, tuple[str, ...]]:
        """The raw tier's residency and entries, for the isolation assertions.

        Returns:
            ``(resident bytes, block ids)`` with the ids sorted.
        """
        return self.raw.resident_bytes, _resident_ids(self.raw)


def _ids(blocks: tuple[BlockId, ...]) -> tuple[str, ...]:
    """Project block identities onto their short ids, for readable goldens."""
    return tuple(block.block_id for block in blocks)


def _resident_ids(store: TierStore) -> tuple[str, ...]:
    """The short ids of everything *store* currently holds, sorted."""
    return tuple(sorted(block.block_id for block in store.entries()))


def _manifest_on_disk(store: TierStore, block: BlockId) -> Mapping[str, object]:
    """Re-read one block's manifest from disk, as JSON and nothing else."""
    document = json.loads((store.path_for(block) / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


# ---------------------------------------------------------------------------
# Leg 1 — the fixture: two shards in the raw tier, five sealed manifests to come
# ---------------------------------------------------------------------------


def check_fixture(driver: Driver) -> None:
    """Fetch two shards into the raw tier; certify one, leave one in flight.

    ``shard-000`` costs two attempts (its first delivery failed verification and
    the partial was dropped) and reaches READY; ``shard-001`` costs three (a
    dropped partial, then a transfer that has resumed once and has not finished),
    so it occupies its **declared** bytes without ever being READY. Five network
    attempts, two shards, 5 000 000 B on the wire for 1 000 000 B certified —
    which is what ``bytes_downloaded`` is supposed to say out loud.
    """
    assert isinstance(driver.clock, Clock), "the stepping clock drifted from the Clock protocol"
    assert isinstance(driver.ledger, BlockLedger), (
        "-01's Ledger no longer satisfies the tier's read/append view"
    )
    assert driver.blocks.budget_bytes == _BLOCKS_BUDGET
    assert driver.raw.budget_bytes == _RAW_BUDGET
    assert driver.observe() == 0, "the blocks tier starts empty"

    for shard in (R0, R1):
        directory = driver.raw.admit(shard, nbytes=_BLOCK_BYTES)
        (directory / "shard.h5").write_bytes(b"raw shard bytes")

    # A destination is charged before its bytes exist — that is the whole reason
    # the budget is enforced on declared sizes.
    assert driver.raw_state() == (_RAW_BUDGET, ("shard-000", "shard-001"))

    driver.record(R0, BlockState.REMOTE)
    driver.record(R0, BlockState.DOWNLOADING, size_bytes=_BLOCK_BYTES)
    driver.record(R0, BlockState.REMOTE)  # digest mismatch: partial dropped
    driver.record(R0, BlockState.DOWNLOADING, size_bytes=_BLOCK_BYTES)
    driver.record(R0, BlockState.READY, size_bytes=_BLOCK_BYTES)

    driver.record(R1, BlockState.REMOTE)
    driver.record(R1, BlockState.DOWNLOADING, size_bytes=_BLOCK_BYTES)
    driver.record(R1, BlockState.REMOTE)  # dropped partial again
    driver.record(R1, BlockState.DOWNLOADING, size_bytes=_BLOCK_BYTES)
    driver.record(R1, BlockState.DOWNLOADING, size_bytes=_BLOCK_BYTES)  # resumed, still in flight

    states = driver.ledger.replay()
    assert states[R0] is BlockState.READY
    assert states[R1] is BlockState.DOWNLOADING
    assert len(SEALED) == 5, "the walkthrough is written against five derived blocks"
    assert {sealed.block.split for sealed in SEALED} == {"train", "val"}

    print(
        f"  Fixture: raw tier {driver.raw.resident_bytes} B of {_RAW_BUDGET} B across "
        f"{driver.raw_state()[1]} (shard-000 READY, shard-001 in flight), blocks tier "
        f"{driver.blocks.resident_bytes} B of {_BLOCKS_BUDGET} B, five sealed manifests "
        f"declared at {_BLOCK_BYTES} B each"
    )


# ---------------------------------------------------------------------------
# Leg 2 — eviction follows the visit plan
# ---------------------------------------------------------------------------


def check_first_eviction(driver: Driver) -> VisitOrder:
    """Three blocks resident, two consumed, one leased: the coldest goes.

    Returns:
        The plan the next leg carries on with.
    """
    for name in (B00, B01, B02):
        driver.seal(_BY_BLOCK[name])
    assert driver.observe() == _BLOCKS_BUDGET
    assert _resident_ids(driver.blocks) == ("b00", "b01", "b02")

    driver.record(B00, BlockState.CONSUMED)
    driver.record(B01, BlockState.CONSUMED)
    granted = driver.ledger.lease([B02], ttl=_LEASE_TTL)
    assert [record.holder for record in granted] == [_ACTOR]
    assert driver.ledger.active_leases()[B02] == (_ACTOR,)

    plan = VisitOrder(_PLAN_ORDER, cursor=2)
    evicted = driver.blocks.evict_until(_BLOCK_BYTES, plan=plan)

    # b00 and b01 are both candidates; b00 sits at position 0, the slot the plan
    # passed longest ago, so plan distance — not access time — picks it.
    assert _ids(evicted) == _FIRST_EVICTION, f"eviction order drifted: {_ids(evicted)}"
    assert driver.observe() == 2_000_000
    assert _resident_ids(driver.blocks) == ("b01", "b02")
    assert not driver.blocks.path_for(B00).exists(), "the evicted block's bytes survived"

    last = driver.ledger.records()[-1]
    assert (last.block, last.state, last.size_bytes) == (B00, BlockState.REMOTE, _BLOCK_BYTES), (
        "a tier writes exactly one kind of record, and the deletion is it"
    )
    assert driver.raw_state() == (_RAW_BUDGET, ("shard-000", "shard-001")), (
        "blocks-tier pressure reached into the raw tier"
    )

    print(
        f"  Plan-ordered eviction: evict_until({_BLOCK_BYTES}) -> {_ids(evicted)} with "
        f"cursor=2, leaving {driver.blocks.resident_bytes} B across "
        f"{_resident_ids(driver.blocks)}; raw tier untouched at {driver.raw.resident_bytes} B"
    )
    return plan


# ---------------------------------------------------------------------------
# Leg 3 — an infeasible target stalls, having deleted nothing
# ---------------------------------------------------------------------------


def check_infeasible_eviction(driver: Driver, plan: VisitOrder) -> None:
    """Pinned, leased and not-yet-consumed: the tier stalls instead of deleting."""
    driver.seal(_BY_BLOCK[B03])
    driver.blocks.flag_resident(B01)
    assert driver.observe() == _BLOCKS_BUDGET
    assert _resident_ids(driver.blocks) == ("b01", "b02", "b03")

    before = len(driver.ledger.records())
    digests_before = {
        block: _manifest_on_disk(driver.blocks, block)["block_digest"] for block in (B01, B02, B03)
    }

    try:
        driver.blocks.evict_until(_BLOCK_BYTES, plan=plan)
    except TierOverBudget as error:
        message = str(error)
    else:  # pragma: no cover - deleting a leased or pinned block is the failure
        raise AssertionError("an infeasible target must stall, not break a lease")

    # Nothing partially deleted: residency, entries, bytes and manifests all as
    # they were, and not one ledger record written.
    assert driver.observe() == _BLOCKS_BUDGET, "a refused eviction changed residency"
    assert _resident_ids(driver.blocks) == ("b01", "b02", "b03")
    for block in (B01, B02, B03):
        assert driver.blocks.path_for(block).is_dir(), f"{block.key()} was deleted anyway"
        assert _manifest_on_disk(driver.blocks, block)["block_digest"] == digests_before[block]
    assert len(driver.ledger.records()) == before, "a refused eviction wrote to the ledger"

    # The refusal names who is holding what, and only this tier.
    for block in (B01, B02, B03):
        assert block.key() in message, f"the blocked candidate {block.key()} went unnamed"
    assert _BLOCKS_SUBDIR in message
    assert _RAW_SUBDIR not in message, "one tier's pressure was reported against both"
    assert driver.raw_state() == (_RAW_BUDGET, ("shard-000", "shard-001"))

    print(
        f"  Infeasible eviction: TierOverBudget with {driver.blocks.resident_bytes} B still "
        f"resident across {_resident_ids(driver.blocks)} (b01 pinned, b02 leased, b03 not "
        f"CONSUMED), 0 records written, 0 directories removed"
    )


# ---------------------------------------------------------------------------
# Leg 4 — the lease lifts, the cursor advances, and the raw tier reclaims
# ---------------------------------------------------------------------------


def check_second_eviction(driver: Driver) -> None:
    """``b02`` becomes evictable, ``b04`` takes its room, ``shard-000`` goes (I3)."""
    assert driver.ledger.release([B02]) == frozenset({B02})
    assert B02 not in driver.ledger.active_leases(), "the lease outlived its release"
    driver.record(B02, BlockState.CONSUMED)

    plan = VisitOrder(_PLAN_ORDER, cursor=3)
    evicted = driver.blocks.evict_until(_BLOCK_BYTES, plan=plan)
    assert _ids(evicted) == _SECOND_EVICTION, f"eviction order drifted: {_ids(evicted)}"
    assert driver.observe() == 2_000_000
    assert not driver.blocks.path_for(B02).exists()
    assert _resident_ids(driver.blocks) == ("b01", "b03")

    # A worker sealed b04 and returned its outcome; the driver has admitted the
    # room but not yet recorded READY, so leg 7 sees it and leg 6 does not.
    driver.seal(_BY_BLOCK[B04], ready=False)
    assert driver.observe() == _BLOCKS_BUDGET
    assert _resident_ids(driver.blocks) == ("b01", "b03", "b04")
    assert B04 not in driver.ledger.replay(), "the worker wrote a ledger record"

    # I3: the shard whose prepare produced those blocks is released, and only it.
    assert driver.raw_state() == (_RAW_BUDGET, ("shard-000", "shard-001"))
    assert driver.raw.release(R0) == _BLOCK_BYTES
    assert driver.raw_state() == (_BLOCK_BYTES, ("shard-001",))
    assert not driver.raw.path_for(R0).exists(), "the raw copy survived its prepare"
    last = driver.ledger.records()[-1]
    assert (last.block, last.state, last.size_bytes) == (R0, BlockState.REMOTE, _BLOCK_BYTES)

    assert driver.blocks.resident_bytes == _BLOCKS_BUDGET, "the raw release touched the blocks tier"
    peak = max(driver.samples)
    assert peak == _BLOCKS_BUDGET, f"peak blocks residency was {peak} B"
    assert peak <= driver.blocks.budget_bytes
    assert len(driver.ledger.records()) == _TRANSITIONS

    print(
        f"  Lease lifted: evict_until({_BLOCK_BYTES}) -> {_ids(evicted)} with cursor=3, then "
        f"b04 admitted; peak blocks residency {peak} B of {_BLOCKS_BUDGET} B across "
        f"{len(driver.samples)} samples; raw tier {driver.raw.resident_bytes} B after "
        f"releasing shard-000 (I3)"
    )


# ---------------------------------------------------------------------------
# Leg 5 — the byte-bounded handoff
# ---------------------------------------------------------------------------


def check_queue() -> None:
    """Bytes free when a file is deleted, not when an item is dequeued."""
    queue = ByteBoundedQueue(capacity_bytes=_QUEUE_CAPACITY)
    trace: list[int] = []

    queue.reserve(R0.key(), nbytes=_BLOCK_BYTES, timeout=0)
    trace.append(queue.held_bytes)
    queue.reserve(R1.key(), nbytes=_BLOCK_BYTES, timeout=0)
    trace.append(queue.held_bytes)

    # Full: the single-threaded, sleep-free probe refuses rather than blocking.
    try:
        queue.reserve(R2.key(), nbytes=_BLOCK_BYTES, timeout=0)
    except QueueTimeout:
        trace.append(queue.held_bytes)
    else:  # pragma: no cover - admitting past the capacity is the leak this stops
        raise AssertionError("a full queue must refuse the zero-timeout probe")

    handed = queue.take(timeout=0)
    assert handed == (R0.key(), _BLOCK_BYTES), f"take handed on {handed}"
    trace.append(queue.held_bytes)  # still held: the bytes are still on disk

    queue.release(R0.key())
    trace.append(queue.held_bytes)
    queue.reserve(R2.key(), nbytes=_BLOCK_BYTES, timeout=0)
    trace.append(queue.held_bytes)

    assert tuple(trace) == _HELD_BYTES_TRACE, f"held_bytes trace drifted: {tuple(trace)}"
    assert queue.pending == 2

    # A reservation no sequence of releases could satisfy is a deadlock, named.
    try:
        queue.reserve(R3.key(), nbytes=_OVERSIZED_BYTES, timeout=0)
    except QueueOversized:
        pass
    else:  # pragma: no cover - waiting forever is not backpressure
        raise AssertionError("a reservation larger than the capacity must be refused")
    assert queue.held_bytes == _QUEUE_CAPACITY, "the refused reservation held bytes"

    print(
        f"  Byte-bounded handoff: capacity {_QUEUE_CAPACITY} B, held_bytes trace "
        f"{_HELD_BYTES_TRACE} across reserve, reserve, refused probe, take, release, reserve; "
        f"{_OVERSIZED_BYTES} B refused as QueueOversized"
    )


# ---------------------------------------------------------------------------
# Leg 6 — coverage, replayed from the ledger this run wrote
# ---------------------------------------------------------------------------


def check_coverage(driver: Driver) -> None:
    """Every number folded out of the file, not out of a counter in memory."""
    report = CoverageReport.replay(driver.ledger.records(), units_by_block=UNITS_BY_BLOCK)

    assert report.bytes_downloaded == _BYTES_DOWNLOADED, (
        f"a retried fetch stopped counting twice: {report.bytes_downloaded}"
    )
    assert report.bytes_prepared == _BYTES_PREPARED
    # split is not None -> pressure; split is None -> the pipeline working.
    assert report.bytes_evicted == _BYTES_EVICTED, f"bytes_evicted {report.bytes_evicted}"
    assert report.bytes_raw_released == _BYTES_RAW_RELEASED, (
        f"bytes_raw_released {report.bytes_raw_released}"
    )

    assert _ids(report.blocks_seen) == _BLOCKS_SEEN, f"blocks_seen {_ids(report.blocks_seen)}"
    assert _ids(report.blocks_consumed) == _BLOCKS_CONSUMED
    assert B04 not in report.blocks_seen, "a block the driver never recorded was reported as seen"
    assert report.units_seen == _UNITS_SEEN
    assert report.fraction(_CORPUS_BLOCKS) == _FRACTION

    timeline = tuple((point.blocks, point.units) for point in report.timeline)
    assert timeline == _TIMELINE, f"the cumulative timeline drifted: {timeline}"

    # Monotone, never pinned: the instants are the run's, not a golden's.
    stamps = [point.at for point in report.timeline]
    assert stamps == sorted(stamps), "the coverage timeline went backwards"
    assert all(stamp.tzinfo is not None for stamp in stamps)

    print(
        f"  Coverage: downloaded {report.bytes_downloaded} B, prepared {report.bytes_prepared} B, "
        f"evicted {report.bytes_evicted} B, raw released {report.bytes_raw_released} B; seen "
        f"{_ids(report.blocks_seen)}, consumed {_ids(report.blocks_consumed)}, units "
        f"{report.units_seen}, fraction({_CORPUS_BLOCKS}) {report.fraction(_CORPUS_BLOCKS)}, "
        f"timeline {timeline} with monotone timestamps"
    )


# ---------------------------------------------------------------------------
# Leg 7 — the sampler handoff, torch-free
# ---------------------------------------------------------------------------


def check_metadata(driver: Driver) -> None:
    """What a consumer may open right now, read as JSON and nothing else."""
    metadata = ReadyBlocks(driver.blocks).metadata()
    assert tuple(entry.block_id.block_id for entry in metadata) == ("b01", "b03", "b04"), (
        "the sealed set is not what the tier holds"
    )

    (found,) = [entry for entry in metadata if entry.block_id == B03]
    assert found.split == "train"
    assert found.units == 2
    assert found.frames == 8, "frames come from rows['frame'], not from units"
    assert found.task_names == _TASK_NAMES
    assert found.root == driver.blocks.path_for(B03)
    assert (found.root / "manifest.json").is_file()

    # Copied, never computed: identical to the bytes on disk and to the literal
    # this script wrote, which is the sha256 of nothing in the fixture.
    sealed = _BY_BLOCK[B03]
    document = _manifest_on_disk(driver.blocks, B03)
    assert found.block_digest == sealed.block_digest == document["block_digest"]
    assert dict(found.column_digests) == dict(sealed.column_digests) == document["digests"]
    assert UNITS_BY_BLOCK[B03] == found.units, "the roster and the manifest disagree on units"

    # b04 is sealed on disk while the ledger has not been told: one surface
    # answers "right now", the other "over time", and they may differ by one.
    assert B04 in {entry.block_id for entry in metadata}
    assert B04 not in driver.ledger.replay()

    print(
        f"  Sampler handoff: {tuple(entry.block_id.block_id for entry in metadata)} sealed; b03 "
        f"split {found.split!r}, units {found.units}, frames {found.frames}, task_names "
        f"{found.task_names}, block_digest {found.block_digest} copied verbatim"
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="molhub-conveyor-residency-") as workdir:
        driver = Driver(Path(workdir))

        check_fixture(driver)
        plan = check_first_eviction(driver)
        check_infeasible_eviction(driver, plan)
        check_second_eviction(driver)
        check_queue()
        check_coverage(driver)
        check_metadata(driver)

    print("streaming-data-tiers-03-conveyor-04-residency: OK")


if __name__ == "__main__":
    main()
