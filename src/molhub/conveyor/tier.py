"""One tier's on-disk residency: a declared-byte budget, planned eviction, one record.

A tier is one subdirectory of the conveyor root plus the rule for how many bytes
may live in it. There are two instances in a run — ``conveyor/raw`` for published
shards in flight and ``conveyor/blocks`` for sealed derived blocks — and they are
two objects on purpose: two budgets with no shared counter and no shared
candidate set means pressure on one tier can never delete an entry of the other.
Neither is under ``files/``, which stays the cross-client layout contract the
TypeScript client reads.

**Why the budget is enforced on declared bytes.** A shard has to be admitted
*before* its bytes exist: the transfer needs a destination directory, and the
only honest number available at that moment is the size the manifest declares.
Charging what is on disk instead would let a 20 GB fetch start inside a tier with
2 GB of headroom and discover the problem when the filesystem fills — which is
not backpressure, it is a crash with a fuller disk. So :meth:`TierStore.admit`
charges the declared size, and disk is consulted as the source of truth exactly
once, at construction, where the store re-derives its entries by walking its own
subdirectory. That is what makes residency survive a crash from *files present ∧
ledger* with no separate recovery verb, and it is also why constructing a store
over a directory that already exceeds its budget **reports** the excess rather
than refusing: ``molhub cache status`` exists to print exactly that, and a
constructor that raised would make the invariant failure unobservable.

**Why eviction plans before it deletes.** :meth:`TierStore.evict_until` builds
its ordered candidate list, checks that the list can actually meet the target,
and only then unlinks anything. A loop that deleted as it went would, on an
infeasible target, leave the tier with fewer bytes *and* the same failure —
having destroyed blocks that will have to be fetched again — and the failure
that matters here is a stall, not a lost lease. Leased blocks (I9),
flag-pinned blocks and blocks that are not ``CONSUMED`` are never candidates, so
"free 40 GB" can legitimately be answered with "I cannot, and here is who is
holding it".

**Eviction order is the consumer's plan, not observed access time.** Candidates
are ordered by their position in a :class:`VisitOrder`: absent from the plan
first (nothing will ask for them again), then behind the cursor by ascending
position (longest since the plan passed them), then ahead of the cursor by
descending position (the furthest future first), ties by ascending block id so
the sequence is reproducible. That is LRU re-expressed as plan distance, which
is what makes "plan globally, consume rolling" mechanical instead of hopeful.

**One ledger record, and only one.** A tier appends exactly one kind of fact:
the return to ``REMOTE`` when local bytes are deleted. No fifth state is
invented — a block with nothing local *is* ``REMOTE`` by ``-01``'s own
definition — and that one record is what makes ``bytes_evicted`` and the
coverage timeline derivable after a restart instead of living in process memory.
Every other transition belongs to the transfer and prepare stages.

Reference:
    ``.claude/specs/streaming-data-tiers-03-conveyor-04-residency.md`` §§ 2-3.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from molhub.conveyor.block import BlockId, BlockState, ConveyorError
from molhub.sources import BlobStore

__all__ = [
    "BlockLedger",
    "VisitOrder",
    "DerivedLayout",
    "TierStore",
    "TierError",
    "TierOverBudget",
    "BlockUnevictable",
    "BlockNotResident",
    "IncompleteDerivation",
]

# `BlockId.key()` is `<kind>/<ns>/<name>@<ver>/<task>/<split|unsplit>/<block_id>`:
# `Coordinate.cache_path()` is always three segments and the other three are each
# one validated segment, so an entry directory sits at exactly this depth below
# the tier's own subdirectory. Re-derivation walks that depth and nothing else.
_KEY_DEPTH = 6

# The segment `BlockId.key()` spends on a block whose split is not knowable.
_UNSPLIT_SEGMENT = "unsplit"

# The provenance a derived artifact cannot be filed without: who produced it and
# when. Everything else in the document is the producer's business.
_REQUIRED_PROVENANCE = ("generator", "generated_at")

_METADATA_NAME = "metadata.json"


class TierError(ConveyorError):
    """A tier cannot honestly do what was asked of its bytes."""


class TierOverBudget(TierError):
    """The bytes asked for do not fit, and nothing was deleted to make them fit.

    Raised by :meth:`TierStore.admit` when a declared size exceeds the headroom —
    admission never evicts silently, because a stage that is out of room has to
    decide whether stalling or evicting is correct — and by
    :meth:`TierStore.evict_until` when the plan-ordered candidates cannot reach
    the target, in which case the message names the blocked candidates and why.
    """


class BlockUnevictable(TierError):
    """This block's bytes may not be deleted right now.

    Raised for a block a lease is live on (I9) or one that has been pinned with
    :meth:`TierStore.flag_resident`. A byte budget never wins against a live
    claim; stalling is the correct failure.
    """


class BlockNotResident(TierError):
    """This tier holds no entry for that block, so it has nothing to free."""


class IncompleteDerivation(TierError):
    """A derived artifact's metadata does not say who produced it, or when.

    Who derived a file and at what instant is the one provenance question its
    path cannot answer, so :meth:`DerivedLayout.write_metadata` refuses a
    document missing ``generator`` or ``generated_at`` rather than filing an
    artifact nobody can attribute.
    """


@runtime_checkable
class BlockLedger(Protocol):
    """The three verbs a tier needs from ``-01``'s ledger, and no fourth.

    A read/append *view*, spelled exactly as
    :class:`~molhub.conveyor.ledger.Ledger` spells it, so the real ledger
    satisfies it structurally and a unit test can drive a tier with a fake that
    implements these three and nothing else. A wider view would rebuild the
    ledger instead of depending on it.
    """

    def replay(self) -> Mapping[BlockId, BlockState]:
        """The last state recorded for every block the ledger mentions."""
        ...

    def active_leases(self, *, now: datetime | None = None) -> Mapping[BlockId, tuple[str, ...]]:
        """Who currently holds which block."""
        ...

    def append(
        self,
        block: BlockId,
        state: BlockState,
        *,
        size_bytes: int | None = None,
        payload: Mapping[str, str] | None = None,
    ) -> object:
        """Record that *block* reached *state*."""
        ...


@dataclass(frozen=True)
class VisitOrder:
    """The consumer's plan: which blocks it will visit, and where it has got to.

    Metadata only. A plan is never admitted to a tier, occupies no entry and is
    not a :class:`~molhub.conveyor.block.BlockId`, so nothing in a tier can
    represent the plan and nothing can evict it. House vocabulary: ``position``
    and ``cursor``, never "index".

    Attributes:
        order: The blocks in the order the consumer will visit them.
        cursor: The position the consumer has reached. Blocks at positions below
            it are behind; the block at the cursor is the nearest future.
    """

    order: tuple[BlockId, ...]
    cursor: int

    def position(self, block: BlockId) -> int | None:
        """The slot *block* occupies in this plan.

        Args:
            block: The block to locate.

        Returns:
            Its zero-based position, or ``None`` when the plan never visits it —
            which makes it the coldest possible eviction candidate.
        """
        try:
            return self.order.index(block)
        except ValueError:
            return None


class DerivedLayout:
    """Where a derived artifact lives, and how its provenance is written.

    The convention ``scripts/build_class1_splits.py`` invented and this chain's
    blocks tier needs: a coordinate-shaped directory
    ``<root>/<subdir>/<namespace>/<name>/<version>/`` plus a ``metadata.json``
    recording the derivation run. Generalized rather than reimplemented, so the
    splits script and the conveyor share one rule instead of two copies that
    drift.

    ``metadata.json`` sits at the *artifact* level and describes the derivation
    (inputs, outputs, seed, generator). ``manifest.json`` sits *inside* a block
    directory and is molnex's ``molix.block/1`` contract. They never merge and
    never nest: a block directory that grew a ``metadata.json`` would be a schema
    collision waiting to be mis-parsed by one of the two repos.

    Args:
        root: The directory this layout files artifacts under.
        subdir: The one subdirectory it owns, e.g. ``"derived"`` or
            ``"conveyor/blocks"``. Slash-separated; nothing is created until
            :meth:`artifact_dir` is called.
    """

    def __init__(self, root: str | Path, *, subdir: str) -> None:
        self._root = Path(root)
        self._subdir = subdir
        self._directory = self._root.joinpath(*subdir.split("/"))

    @property
    def subdir(self) -> str:
        """The one subdirectory this layout owns, as it was configured."""
        return self._subdir

    @property
    def directory(self) -> Path:
        """``<root>/<subdir>`` — the base every artifact of this layout sits in.

        Returns:
            The path. Whether it exists is not asserted; reading a location
            creates nothing.
        """
        return self._directory

    def artifact_dir(self, namespace: str, name: str, version: str) -> Path:
        """The directory one derived artifact occupies, created if absent.

        Args:
            namespace: Coordinate namespace, e.g. ``"molcrafts"``.
            name: Artifact name, e.g. ``"class1-universal-splits"``.
            version: Version label, e.g. ``"1"``.

        Returns:
            ``<root>/<subdir>/<namespace>/<name>/<version>``, existing.
        """
        directory = self._directory / namespace / name / version
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def write_metadata(self, directory: str | Path, document: Mapping[str, object]) -> Path:
        """Write *document* as this artifact's ``metadata.json``, atomically.

        Serialized with ``indent=2`` and one trailing newline, in the
        document's own key order, then written to a temporary file, fsynced and
        moved into place with :func:`os.replace` — so no reader ever sees a
        partial document, and the bytes are identical to what the splits script
        has been writing since the convention was invented.

        Args:
            directory: The artifact directory, usually from :meth:`artifact_dir`.
            document: The derivation record. Contents belong to the producer;
                only the presence of ``generator`` and ``generated_at`` is
                checked here.

        Returns:
            The path of the written ``metadata.json``.

        Raises:
            IncompleteDerivation: If ``generator`` or ``generated_at`` is
                missing, in which case nothing is written at all.
        """
        missing = [key for key in _REQUIRED_PROVENANCE if key not in document]
        if missing:
            raise IncompleteDerivation(
                f"Derived metadata for {directory} declares no {missing}. Who derived an "
                "artifact and when is the one provenance question its path cannot answer, "
                "so an unattributable document is refused before anything is written."
            )
        target = Path(directory) / _METADATA_NAME
        temporary = target.with_name(f".{_METADATA_NAME}.{os.getpid()}.tmp")
        payload = (json.dumps(dict(document), indent=2) + "\n").encode("utf-8")
        with open(temporary, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return target


class TierStore:
    """One subdirectory of the conveyor root, bounded in bytes.

    Construct, admit what fits, read residency, free what the plan says is
    coldest. Each primitive does one named thing: :meth:`admit` never evicts and
    :meth:`evict_until` never admits, because a stage that is out of room has to
    choose between stalling and evicting and hiding that choice inside an
    admission would be exactly the all-in-one façade this layer forbids.

    Args:
        root: The conveyor root. ``None`` defers to
            :class:`~molhub.sources.blobs.BlobStore`, which reads
            ``config.home_dir`` — this class never reads the process home
            itself, so the repo resolves it in exactly one place.
        subdir: The one subdirectory this tier owns, slash-separated, e.g.
            ``"conveyor/raw"`` or ``"conveyor/blocks"``. Never under ``files/``.
        budget_bytes: How many bytes may be resident in this tier. Enforced
            against declared sizes, not against what has landed yet.
        ledger: Anything satisfying :class:`BlockLedger`. Read for block state
            and live leases; appended to only on deletion.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        subdir: str,
        budget_bytes: int,
        ledger: BlockLedger,
    ) -> None:
        self._layout = DerivedLayout(BlobStore(root).root, subdir=subdir)
        self._budget_bytes = budget_bytes
        self._ledger = ledger
        self._flagged: set[BlockId] = set()
        self._entries: dict[BlockId, int] = self._on_disk()

    @property
    def directory(self) -> Path:
        """The one subdirectory this tier owns. Reading it creates nothing."""
        return self._layout.directory

    @property
    def budget_bytes(self) -> int:
        """How many bytes may be resident in this tier."""
        return self._budget_bytes

    @property
    def resident_bytes(self) -> int:
        """Bytes currently charged to this tier.

        Returns:
            The sum of every entry's charge in bytes — declared sizes for blocks
            admitted by this process, on-disk sizes for those re-derived at
            construction. May exceed :attr:`budget_bytes`, which is what
            ``molhub cache status`` reports as a failing residency invariant.
        """
        return sum(self._entries.values())

    @property
    def headroom(self) -> int:
        """Bytes still admissible.

        Returns:
            :attr:`budget_bytes` less :attr:`resident_bytes`, in bytes. Negative
            when the tier is already over its budget — reported, never clamped.
        """
        return self._budget_bytes - self.resident_bytes

    def entries(self) -> Mapping[BlockId, int]:
        """What this tier holds, and what each entry is charged.

        Returns:
            A read-only mapping of block to its charge in bytes. One read, not
            two: "which blocks" and "what they cost" are the same question about
            the same table.
        """
        return MappingProxyType(dict(self._entries))

    def path_for(self, block: BlockId) -> Path:
        """Where *block*'s bytes live in this tier.

        Args:
            block: The block to locate.

        Returns:
            ``<root>/<subdir>/<block key>``. Nothing is created and nothing is
            charged: this answers where, and only :meth:`admit` records that
            anything is there.
        """
        return self._layout.directory.joinpath(*block.key().split("/"))

    def admit(self, block: BlockId, *, nbytes: int) -> Path:
        """Charge *nbytes* to this tier for *block* and return its directory.

        Admitting a block this tier already holds re-charges that one entry at
        *nbytes* rather than opening a second one: a block occupies one
        directory here, so it can only cost one charge.

        Args:
            block: The block being admitted. A :class:`VisitOrder` is not a
                block and is refused: no tier entry may represent the plan.
            nbytes: The block's declared size in bytes — what the manifest says,
                not what has landed, because admission necessarily precedes the
                bytes.

        Returns:
            The block's directory in this tier, created.

        Raises:
            TypeError: If *block* is not a :class:`~molhub.conveyor.block.BlockId`.
            TierOverBudget: If *nbytes* does not fit in the headroom. Nothing is
                charged and no directory is created; admission never evicts on
                its own.
        """
        if not isinstance(block, BlockId):
            raise TypeError(
                f"A tier admits blocks, not {type(block).__name__}. A visit plan is "
                "metadata about what the consumer will read; it occupies no entry and "
                "no tier may hold one."
            )
        projected = self.resident_bytes - self._entries.get(block, 0) + nbytes
        if projected > self._budget_bytes:
            raise TierOverBudget(
                f"{self._layout.subdir} holds {self.resident_bytes} B of {self._budget_bytes} B; "
                f"admitting {block.key()} at {nbytes} B would need {projected} B. Evict "
                "with a visit plan or stall — an admission never deletes on its own."
            )
        directory = self.path_for(block)
        directory.mkdir(parents=True, exist_ok=True)
        self._entries[block] = nbytes
        return directory

    def release(self, block: BlockId) -> int:
        """Delete this tier's copy of *block* and free its bytes.

        Args:
            block: The block to free.

        Returns:
            The bytes freed.

        Raises:
            BlockNotResident: If this tier holds no entry for *block*.
            BlockUnevictable: If a lease is live on it or it has been pinned by
                :meth:`flag_resident`. Nothing is deleted and nothing is
                recorded.
        """
        charged = self._entries.get(block)
        if charged is None:
            raise BlockNotResident(
                f"{self._layout.subdir} holds no entry for {block.key()}, so it has nothing to "
                "free. Another tier's copy is another tier's business."
            )
        blocked = self._blocked(block)
        if blocked is not None:
            raise BlockUnevictable(
                f"{block.key()} may not be deleted from {self._layout.subdir}: {blocked}. A byte "
                "budget never wins against a live claim."
            )
        self._delete(block)
        return charged

    def flag_resident(self, block: BlockId) -> None:
        """Pin *block* in this tier: the T-HOT exemption.

        Validation sets and the Hessian core are read all run long, so they are
        exempted from eviction by a flag this stage owns — not by a fifth block
        state, which would make the lifecycle depend on who is asking.
        Idempotent, and it records nothing in the ledger.

        Args:
            block: The block to pin. Must already be an entry of this tier.

        Raises:
            BlockNotResident: If this tier holds no entry for *block*; a pin on
                nothing is a silent no-op, and this stage does not do those.
        """
        if block not in self._entries:
            raise BlockNotResident(
                f"{self._layout.subdir} holds no entry for {block.key()}, so there is nothing "
                "here to pin. Admit it first."
            )
        self._flagged.add(block)

    def evict_until(self, free_bytes: int, *, plan: VisitOrder) -> tuple[BlockId, ...]:
        """Free at least *free_bytes* bytes, in the order *plan* implies.

        Plans first, deletes second. The candidate list is built, its total is
        compared with the target, and only then is anything unlinked — so an
        infeasible request costs nothing rather than destroying blocks and
        failing anyway.

        Args:
            free_bytes: How many bytes to free, at least. Zero or less frees
                nothing.
            plan: The consumer's visit order, which decides eviction order:
                blocks absent from the plan first, then behind the cursor by
                ascending position, then ahead of it by descending position,
                ties by ascending block id.

        Returns:
            The blocks deleted, in the order they were deleted.

        Raises:
            TierOverBudget: If the eligible candidates hold fewer than
                *free_bytes* bytes. Nothing is deleted and nothing is recorded;
                the message names the blocked candidates and why each is
                blocked.
        """
        if free_bytes <= 0:
            return ()
        candidates = self._candidates(plan)
        if sum(self._entries[block] for block in candidates) < free_bytes:
            raise TierOverBudget(
                f"{self._layout.subdir} cannot free {free_bytes} B: its eligible entries hold "
                f"{sum(self._entries[block] for block in candidates)} B of "
                f"{self.resident_bytes} B. Blocked: {self._blocked_report()}. Stalling is "
                "the correct failure here; breaking a lease is not."
            )
        evicted: list[BlockId] = []
        freed = 0
        for block in candidates:
            if freed >= free_bytes:
                break
            freed += self._entries[block]
            self._delete(block)
            evicted.append(block)
        return tuple(evicted)

    # -- internals ---------------------------------------------------------

    def _delete(self, block: BlockId) -> None:
        """Unlink one entry's bytes and record the block's return to REMOTE."""
        charged = self._entries.pop(block)
        path = self.path_for(block)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        # `size_bytes` must be positive or absent: an entry charged nothing had
        # nothing on disk, and zero is the shape of an interrupted transfer.
        self._ledger.append(block, BlockState.REMOTE, size_bytes=charged or None)

    def _blocked(self, block: BlockId) -> str | None:
        """Why *block*'s bytes may not be deleted, or ``None`` when they may."""
        if block in self._flagged:
            return "it is pinned in this tier"
        holders = self._ledger.active_leases().get(block)
        if holders:
            return f"held by {list(holders)}"
        return None

    def _candidates(self, plan: VisitOrder) -> tuple[BlockId, ...]:
        """This tier's evictable entries, coldest first by plan distance."""
        states = self._ledger.replay()
        leases = self._ledger.active_leases()
        eligible = [
            block
            for block in self._entries
            if states.get(block) is BlockState.CONSUMED
            and not leases.get(block)
            and block not in self._flagged
        ]
        return tuple(sorted(eligible, key=lambda block: self._distance(block, plan)))

    @staticmethod
    def _distance(block: BlockId, plan: VisitOrder) -> tuple[int, int, str]:
        """Sort key: plan group, distance within it, then block key for ties.

        Group 0 is absent from the plan — nothing will ask for it again, so it
        is the coldest. Group 1 is behind the cursor, ordered by ascending
        position: the earliest slot is the one the plan passed longest ago.
        Group 2 is at or ahead of the cursor, ordered by descending position, so
        the furthest future goes first and the nearest one survives longest.
        The block key breaks ties, which is what makes the sequence reproducible
        (:class:`~molhub.conveyor.block.BlockId` is unordered by design).
        """
        position = plan.position(block)
        if position is None:
            return (0, 0, block.key())
        if position < plan.cursor:
            return (1, position, block.key())
        return (2, -position, block.key())

    def _blocked_report(self) -> str:
        """Every entry that is not a candidate, with the reason, for a message."""
        states = self._ledger.replay()
        reports = []
        for block in sorted(self._entries, key=lambda entry: entry.key()):
            reason = self._blocked(block)
            if reason is None and states.get(block) is not BlockState.CONSUMED:
                reason = f"state is {states.get(block)}"
            if reason is not None:
                reports.append(f"{block.key()} ({reason})")
        return ", ".join(reports) if reports else "nothing"

    def _on_disk(self) -> dict[BlockId, int]:
        """Re-derive residency by walking this tier's own subdirectory.

        Disk is the source of truth exactly once, here: an entry is a directory
        at block-key depth whose name parses back into a
        :class:`~molhub.conveyor.block.BlockId`, charged the bytes it actually
        holds. Anything else under the subdirectory is somebody else's file and
        is left alone.
        """
        directory = self._layout.directory
        if not directory.is_dir():
            return {}
        entries: dict[BlockId, int] = {}
        for path in sorted(directory.glob("/".join(["*"] * _KEY_DEPTH))):
            if not path.is_dir():
                continue
            block = self._block_at(path.relative_to(directory).parts)
            if block is None:
                continue
            entries[block] = sum(
                child.stat().st_size for child in path.rglob("*") if child.is_file()
            )
        return entries

    @staticmethod
    def _block_at(parts: tuple[str, ...]) -> BlockId | None:
        """Invert :meth:`~molhub.conveyor.block.BlockId.key` for one entry path.

        Args:
            parts: The entry's path segments below the tier's subdirectory.

        Returns:
            The block those segments name, or ``None`` when they do not name one
            — a foreign directory is skipped, never repaired into a block.
        """
        kind, namespace, versioned, task, split, block_id = parts
        try:
            return BlockId(
                source=f"{kind}:{namespace}/{versioned}",
                task=task,
                split=None if split == _UNSPLIT_SEGMENT else split,
                block_id=block_id,
            )
        except ConveyorError:
            return None
