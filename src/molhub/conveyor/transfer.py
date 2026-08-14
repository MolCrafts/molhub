"""Moving one shard here, under a lease, and refusing to believe it on arrival.

The transport layer's job ends when a locator's bytes are on disk;
:class:`~molhub.sources.fetcher.Fetcher` checks a digest once, and when a
mirror serves the wrong content it raises
:class:`~molhub.sources.errors.DigestMismatch` and moves on, because for an
*upstream change* retrying the same locator is exactly the wrong answer. This
module is the other case, and it is a real one: ``themol/mbis`` shard-003 once
served corrupt bytes under a correct manifest, and the honest response to that
is a bounded retry — which is why retry lives **here**, one layer up, and the
fetcher's no-retry semantics are generalized around rather than edited.

**Why a delivered file is deleted before it is re-fetched.**
``Fetcher.fetch`` returns a cached file without re-verifying it
(``src/molhub/sources/fetcher.py:82-84``). Leaving bad bytes in the cache would
make every "retry" return the identical bad bytes, and the bounded retry would
be theatre. The unlink is load-bearing, not tidiness.

**Why the lease comes before the first fetch.**

    **Carried verbatim, and not to be mistaken for handled.** ``BlobStore.temp_path``
    (``sources/blobs.py:69-75``) derives ONE fixed ``.part`` path per key — a real
    multi-process correctness hazard in L1; this spec neutralizes it by lease at
    the conveyor layer but does **NOT** fix L1; the underlying gap is routed
    separately to ``/mol:fix`` (pid/uuid-suffixed temp name) and must not be
    mistaken for handled.

The lease serializes *conveyor* callers against each other; a concurrent
non-conveyor ``Fetcher`` call still races into the same ``.part``.

**Why nothing here ever writes READY.** READY is conjunctive — downloaded *and*
unpacked *and* prepared *and* verified — and this module does none of the middle
two. A mismatching block therefore cannot reach READY structurally, rather than
by everyone remembering not to write it: no code path here names that member at
all, and a grep for it comes back empty. What it writes is one ``DOWNLOADING`` row per call
(the ledger is a state log, not a retry log; attempts are evidence carried by
the error) and, on exhaustion, a regression to ``REMOTE`` — *after* the bad
bytes are gone, because REMOTE means "nothing local" and regressing to it while
garbage sits in the cache would be a false statement in a durable file.

Reference:
    ``.claude/specs/streaming-data-tiers-03-conveyor-02-roster.md``
    § *``ShardTransfer`` — bounded, leased, re-verified*.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from molhub.conveyor.block import BlockId, BlockState, ConveyorError
from molhub.conveyor.roster import RemoteBlock
from molhub.sources.digest import Digest

if TYPE_CHECKING:  # pragma: no cover - typing only; see the note below.
    # Imported for the annotation alone. `molhub.dataset`'s package __init__
    # pulls in molpy and numpy, and this layer is bookkeeping that must stay
    # importable without them; a transfer depends on the hub's *shape* — one
    # verb — not on its module.
    from molhub.dataset.hub import ArtifactHub

__all__ = [
    "TransferLedger",
    "Backoff",
    "ExponentialBackoff",
    "TransferAttempt",
    "ShardTransfer",
    "TransferError",
    "PersistentDigestMismatch",
]


@runtime_checkable
class TransferLedger(Protocol):
    """The three verbs a transfer needs of a ledger, and not one more.

    A required-side view of :class:`molhub.conveyor.ledger.Ledger`, not a second
    ledger: the real one satisfies this by shape and declares nothing, exactly as
    :class:`molhub.molhub.Molhub` satisfies
    :class:`~molhub.dataset.hub.ArtifactHub`. Keeping the view at three verbs is
    what lets a transfer be unit-tested against a recording fake with no file,
    no clock and no replay — and what makes "the transfer depends on the ledger"
    a statement someone can check.

    Return types are :class:`object` because a transfer reads none of them: the
    real ledger hands back the records it wrote, a fake hands back nothing, and
    both are honest implementations of a seam whose whole content is the write.
    """

    def append(self, block: BlockId, state: BlockState) -> object:
        """Record that *block* reached *state*."""
        ...

    def lease(self, blocks: Iterable[BlockId], *, ttl: timedelta) -> object:
        """Claim *blocks* for *ttl*."""
        ...

    def release(self, blocks: Iterable[BlockId]) -> object:
        """Give up the claim on *blocks*."""
        ...


@runtime_checkable
class Backoff(Protocol):
    """How long a transfer pauses before re-fetching."""

    def wait(self, attempt: int) -> None:
        """Pause after *attempt* (1-based) before the next one."""
        ...


@dataclass(frozen=True)
class ExponentialBackoff:
    """Doubling waits, with the schedule kept separate from the sleeping.

    :meth:`delay` is pure, so the schedule is testable without a clock and
    without a test that takes seven seconds to prove it can add; :meth:`wait` is
    the one impure line. Nothing here jitters or caps: a conveyor moves one
    shard at a time against one mirror, so there is no thundering herd to spread
    and no unbounded ladder to clamp.

    Attributes:
        base: Seconds before the second attempt.
    """

    base: float = 1.0

    def __post_init__(self) -> None:
        if self.base <= 0:
            raise ValueError(
                f"Backoff base must be positive; got {self.base!r}. A zero base is not a "
                "faster retry policy, it is no retry policy — re-fetching a 4 GB shard "
                "instantly after a mismatch just asks the same mirror the same question."
            )

    def delay(self, attempt: int) -> float:
        """Seconds to wait after *attempt*.

        Args:
            attempt: Which attempt just concluded, 1-based.

        Returns:
            ``base * 2 ** (attempt - 1)``.

        Raises:
            ValueError: If *attempt* is below 1; attempts are counted from one.
        """
        if attempt < 1:
            raise ValueError(f"Attempts are 1-based; got attempt {attempt!r}.")
        return self.base * float(2 ** (attempt - 1))

    def wait(self, attempt: int) -> None:
        """Sleep for :meth:`delay` seconds."""
        time.sleep(self.delay(attempt))


@dataclass(frozen=True)
class TransferAttempt:
    """One delivered file that did not verify.

    Carried by :class:`PersistentDigestMismatch` so a multi-attempt failure is
    diagnosable from one traceback, in the aggregate style of
    :class:`~molhub.sources.errors.AllLocatorsFailed`.

    Attributes:
        index: Which attempt this was, 1-based.
        path: Where the delivered file was before it was deleted.
        reason: ``"size"`` when the byte count already disagreed, ``"digest"``
            when a right-sized file hashed to the wrong value.
        expected: What the manifest declared, as text — a byte count or a
            digest, so one attempt type covers both halves of one predicate.
        actual: What arrived, in the same form.
    """

    index: int
    path: Path
    reason: Literal["size", "digest"]
    expected: str
    actual: str

    def __str__(self) -> str:
        return (
            f"attempt {self.index}: {self.reason} was {self.actual}, "
            f"manifest declares {self.expected} ({self.path})"
        )


class TransferError(ConveyorError):
    """A block's bytes could not be brought here in a state worth keeping."""


class PersistentDigestMismatch(TransferError):
    """A block did not verify within its retry bound, and its bytes are gone.

    Deliberately **not** a subclass of
    :class:`molhub.sources.errors.DigestMismatch`. That type means "upstream
    changed, update the manifest, stop using this mirror", and code catching it
    must not silently swallow "the same artifact did not verify three times in a
    row" — which is a corrupt delivery, a different incident with a different
    remedy.

    Args:
        block: The block that did not verify.
        attempts: Every attempt, in order, each naming its own reason.

    Attributes:
        block: The block that did not verify.
        attempts: The attempts, 1-based and in order.
    """

    def __init__(self, block: RemoteBlock, attempts: Sequence[TransferAttempt]) -> None:
        self.block = block
        self.attempts = tuple(attempts)
        detail = "\n".join(f"  {attempt}" for attempt in self.attempts)
        super().__init__(
            f"{block.id.key()} did not verify in {len(self.attempts)} attempt(s):\n{detail}\n"
            "The delivered bytes were deleted and the block was recorded REMOTE again. "
            "If a re-run reproduces this, the mirror is serving corrupt content — check "
            "upstream before raising the retry bound."
        )


class ShardTransfer:
    """Brings one block's bytes here, under a lease, and verifies them on arrival.

    Args:
        hub: Where bytes come from — one verb, ``fetch(coordinate, roles=...)``.
            This is the transfer's only transport dependency: no driver table,
            no URL, no HTTP.
        ledger: Where the state log goes; three verbs, see
            :class:`TransferLedger`.
        retries: Attempts **in total**, not extra ones after a first: ``3`` means
            three fetches.
        backoff: How long to pause between attempts; defaults to
            :class:`ExponentialBackoff`.
        lease_ttl: How long the lease on the block lasts, passed to the ledger
            unconverted. A documented bound, not a renewal mechanism — a
            transfer that outlives it is a later stage's problem.

    Raises:
        ValueError: If *retries* is below 1. A bounded retry of zero attempts is
            not a policy, it is a typo, and it would return no path and raise
            nothing.
    """

    def __init__(
        self,
        hub: ArtifactHub,
        ledger: TransferLedger,
        *,
        retries: int = 3,
        backoff: Backoff | None = None,
        lease_ttl: timedelta = timedelta(hours=1),
    ) -> None:
        if retries < 1:
            raise ValueError(
                f"retries must be at least 1; got {retries!r}. It counts attempts in total, "
                "so 1 is one fetch and 3 is three."
            )
        self._hub = hub
        self._ledger = ledger
        self._retries = retries
        self._backoff: Backoff = backoff if backoff is not None else ExponentialBackoff()
        self._lease_ttl = lease_ttl

    def transfer(self, block: RemoteBlock) -> Path:
        """Fetch *block*, verify it, and return where its bytes are.

        The sequence is the contract: lease before the first fetch, one
        ``DOWNLOADING`` row for the whole call, up to ``retries`` verified
        attempts with the delivered file deleted between them, and the lease
        released whether this returns or raises.

        Args:
            block: The block to bring here, as projected by
                :class:`~molhub.conveyor.roster.BlockRoster`.

        Returns:
            The verified local path. The block stays ``DOWNLOADING``: READY is
            conjunctive and this call has done only the first of its four parts.

        Raises:
            PersistentDigestMismatch: If every attempt disagreed with the
                manifest. The delivered bytes are deleted and the block is
                recorded ``REMOTE`` before this is raised — in that order, since
                ``REMOTE`` claims nothing is local.
        """
        self._ledger.lease([block.id], ttl=self._lease_ttl)
        try:
            self._ledger.append(block.id, BlockState.DOWNLOADING)
            attempts: list[TransferAttempt] = []
            for index in range(1, self._retries + 1):
                served = self._hub.fetch(block.id.source, roles=[block.id.block_id])
                path = served[block.id.block_id]
                attempt = self._mismatch(path, block, index)
                if attempt is None:
                    return path
                # Before the backoff, and before anything is recorded: the cache
                # short-circuit would otherwise re-serve these exact bytes.
                path.unlink(missing_ok=True)
                attempts.append(attempt)
                if index < self._retries:
                    self._backoff.wait(index)
            self._ledger.append(block.id, BlockState.REMOTE)
            raise PersistentDigestMismatch(block, attempts)
        finally:
            self._ledger.release([block.id])

    def _mismatch(self, path: Path, block: RemoteBlock, index: int) -> TransferAttempt | None:
        """Check a delivered file against the manifest, size first.

        Size is checked before the digest because a truncated 4 GB file is one
        ``stat`` to detect and some twenty seconds to hash, and a wrong size
        always implies a wrong digest — one predicate with a fast pre-filter,
        not two failure modes.

        Args:
            path: The delivered file.
            block: What the manifest declares about it.
            index: Which attempt this is, 1-based.

        Returns:
            ``None`` when the file is what the manifest declares, else the
            :class:`TransferAttempt` describing the disagreement.
        """
        size = path.stat().st_size
        if size != block.size:
            return TransferAttempt(
                index=index,
                path=path,
                reason="size",
                expected=str(block.size),
                actual=str(size),
            )
        actual = Digest.of_file(path, algorithm=block.digest.algorithm)
        if actual.matches(block.digest):
            return None
        return TransferAttempt(
            index=index,
            path=path,
            reason="digest",
            expected=str(block.digest),
            actual=str(actual),
        )
