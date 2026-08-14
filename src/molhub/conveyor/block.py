"""Block identity and the closed four-state block lifecycle.

A conveyor block is one unit of remote data the conveyor can fetch, prepare,
hand to a consumer, and reclaim. Every later stage of the chain *writes* block
state, so the vocabulary for **which** block and **what has already happened to
it** lives here, once. Nothing downstream is allowed a second encoding of it —
three stages with three encodings is exactly how "the true state is
re-derivable from the files present and the ledger" degrades into three
disagreeing opinions.

**Why exactly four states, closed.** ``REMOTE``, ``DOWNLOADING``, ``READY`` and
``CONSUMED`` are the only positions a block's history can occupy. The single
``str`` → :class:`BlockState` boundary is :meth:`BlockState.parse`; no other
signature in the package accepts a state as text. A fifth member would reopen
the hole this module exists to close — a state meaning "some bytes are here"
without a record of the download that put them there. Because the set is
closed, all sixteen ordered pairs are decided once in one frozen module-level
mapping, and an impossible history is unrepresentable both on the write side
(:meth:`BlockState.transition_to`) and on the read side (the ledger re-checks
every fold against the same mapping). Ten pairs are legal, six are not. The
four self-transitions are legal deliberately: a stage re-run after a crash must
be able to record a fact instead of raising.

**Why residency is not a state.** "This ``READY`` block is pinned, do not
delete it" describes one consumer's claim, not the block's history: it can flip
twice while the block's lifecycle position does not move at all, and two
consumers can hold opposite opinions about it at the same instant. Encoding it
as a fifth member would make the legality table depend on who is asking. It
stays a flag owned by the residency stage, orthogonal to this lifecycle, and
the claim itself is expressed as a lease record in the ledger — which is why a
lease composes with the state machine instead of joining it.

**Why ``split`` may be ``None`` and never ``"unsplit"``.** A derived block is
split-pure and carries its label; a published shard's split cannot be known
without opening its bytes, so ``None`` is the honest encoding rather than a
fabricated label that would travel into paths and reports as if it had been
measured. :meth:`BlockId.key` spends the path segment ``unsplit`` on that case,
which is precisely why the literal string ``"unsplit"`` is refused as a real
split: accepting both would map two different blocks onto one key, and the key
is what the ledger and every successor address a block by.

Validation happens at construction and nothing is ever sanitised: a sanitiser
that folded an unsafe character into ``_`` would silently collapse two distinct
blocks onto one key, whereas a refusal at construction cannot.

Reference:
    ``.claude/specs/streaming-data-tiers-03-conveyor-01-ledger.md`` §§ 2-3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from molhub.coordinate import Coordinate, InvalidCoordinate

__all__ = [
    "BlockState",
    "BlockId",
    "ConveyorError",
    "IllegalTransition",
    "InvalidBlockId",
    "UnknownBlockState",
]

# One path-safe segment: what `key()` may join with "/" without ambiguity.
_SEGMENT = re.compile(r"[A-Za-z0-9._@-]+")

# The segment `key()` writes when `split is None`; reserved, never a real split.
_UNSPLIT_SEGMENT = "unsplit"


class ConveyorError(Exception):
    """Base class for every conveyor bookkeeping failure."""


class IllegalTransition(ConveyorError):
    """A block state change the lifecycle does not allow.

    Raised on the write side by :meth:`BlockState.transition_to` and on the read
    side by the ledger, which re-checks a recorded history against the same
    mapping so a hand-edited file cannot smuggle in a history the writer would
    have refused.
    """


class InvalidBlockId(ConveyorError):
    """A block identity field is not a usable one.

    Carries the underlying :class:`~molhub.coordinate.InvalidCoordinate` as
    ``__cause__`` when the ``source`` coordinate is the part that was refused.
    """


class UnknownBlockState(ConveyorError):
    """Text at the file boundary does not name one of the four states."""


class BlockState(Enum):
    """Where one block stands in its lifecycle.

    The string values exist for the file boundary only: they are what a ledger
    line carries, and :meth:`parse` is the single way one comes back in.
    """

    REMOTE = "remote"
    DOWNLOADING = "downloading"
    READY = "ready"
    CONSUMED = "consumed"

    @classmethod
    def parse(cls, text: str) -> BlockState:
        """Return the state whose value is *text*.

        Args:
            text: A state value as written in a ledger line, e.g. ``"ready"``.

        Returns:
            The matching :class:`BlockState`.

        Raises:
            UnknownBlockState: If no member carries that value. A new lifecycle
                position means adding a member *and* its legality row, not
                inventing a new string at a call site.
        """
        try:
            return cls(text)
        except ValueError as error:
            raise UnknownBlockState(
                f"Unknown block state {text!r}; expected one of {[state.value for state in cls]}."
            ) from error

    def may_become(self, other: BlockState) -> bool:
        """Whether a change from this state to *other* is legal.

        Args:
            other: The candidate next state.

        Returns:
            ``True`` if the pair appears in the legality mapping. A member with
            no row is permitted nothing, so a member added without its row shows
            up as a refused transition rather than a ``KeyError`` in production.
        """
        return other in _LEGAL_TRANSITIONS.get(self, frozenset())

    def transition_to(self, other: BlockState) -> BlockState:
        """Return *other*, enforcing that this state may become it.

        Args:
            other: The state being recorded next.

        Returns:
            *other*, unchanged — so a caller can write
            ``state = state.transition_to(next_state)``.

        Raises:
            IllegalTransition: If the pair is one of the six illegal ones. The
                message names both endpoints and what *is* reachable.
        """
        if not self.may_become(other):
            reachable = sorted(state.value for state in _LEGAL_TRANSITIONS.get(self, frozenset()))
            raise IllegalTransition(
                f"Illegal block transition {self.value!r} -> {other.value!r}; "
                f"from {self.value!r} only {reachable} may follow. Record the "
                "intermediate fact first — the lifecycle has no shortcuts."
            )
        return other


# The spec's 4x4 table: ten legal pairs, six illegal, keyed by exactly the four
# members so that a member added without a row is a test failure, not a hole.
#
#   REMOTE      -> REMOTE (re-declare), DOWNLOADING (fetch starts).
#                  Not READY: bytes cannot appear without a download record.
#                  Not CONSUMED: nothing that was never local can be consumed.
#   DOWNLOADING -> REMOTE (dropped partial, retry from scratch), DOWNLOADING
#                  (re-attempt / resume), READY (unpack AND prepare AND verify).
#                  Not CONSUMED: unverified bytes are never consumed.
#   READY       -> REMOTE (local copy released without being consumed: byte-budget
#                  eviction, or clean-up of prepared files after a crash),
#                  READY (re-verify), CONSUMED.
#                  Not DOWNLOADING: a re-fetch restarts from REMOTE, otherwise
#                  the already-prepared files are unaccounted for.
#   CONSUMED    -> REMOTE (deleted locally; a later pass re-fetches it),
#                  CONSUMED (several consumers finishing).
#                  Not DOWNLOADING / READY: re-declare REMOTE first, so every
#                  cycle through the lifecycle is a clean one.
_LEGAL_TRANSITIONS: MappingProxyType[BlockState, frozenset[BlockState]] = MappingProxyType(
    {
        BlockState.REMOTE: frozenset({BlockState.REMOTE, BlockState.DOWNLOADING}),
        BlockState.DOWNLOADING: frozenset(
            {BlockState.REMOTE, BlockState.DOWNLOADING, BlockState.READY}
        ),
        BlockState.READY: frozenset({BlockState.REMOTE, BlockState.READY, BlockState.CONSUMED}),
        BlockState.CONSUMED: frozenset({BlockState.REMOTE, BlockState.CONSUMED}),
    }
)


@dataclass(frozen=True)
class BlockId:
    """Which block a fact is about: the strategy's four-tuple, validated.

    None of the four fields invents a taxonomy. ``task`` is a collection role
    name, ``block_id`` is a manifest artifact role, ``split`` is the upstream
    split label, and ``source`` is a MolHub coordinate — parsed by
    :class:`~molhub.coordinate.Coordinate`, so there is no second coordinate
    parser and no second rule for turning one into path segments.

    Attributes:
        source: A version-pinned MolHub coordinate, e.g.
            ``"dataset:themol/torsion-scan@1"``.
        task: Collection role name, one path-safe segment, e.g. ``"torsion"``.
        split: ``"train"`` / ``"val"`` / ``"test"`` for a split-pure derived
            block; ``None`` for a split-mixed published shard, whose split
            cannot be known without opening its bytes. Never a sentinel string.
        block_id: Manifest artifact role, e.g. ``"shard-003"``.
    """

    source: str
    task: str
    split: str | None
    block_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, str):
            raise InvalidBlockId(f"Block source must be a coordinate string; got {self.source!r}.")
        try:
            Coordinate.parse(self.source)
        except InvalidCoordinate as error:
            raise InvalidBlockId(
                f"Block source {self.source!r} is not a MolHub coordinate ({error}). "
                "Use the version-pinned form, e.g. 'dataset:themol/torsion-scan@1'."
            ) from error
        self._require_segment("task", self.task)
        self._require_segment("block_id", self.block_id)
        if self.split is not None:
            self._require_segment("split", self.split)
            if self.split == _UNSPLIT_SEGMENT:
                raise InvalidBlockId(
                    f"Split {_UNSPLIT_SEGMENT!r} is reserved: key() writes that segment "
                    "for a split-mixed block. Pass split=None for a block whose split "
                    "is unknown, or the real label for a split-pure one."
                )

    @staticmethod
    def _require_segment(label: str, value: str) -> None:
        """Refuse anything that is not one non-empty path-safe segment."""
        if not isinstance(value, str) or not _SEGMENT.fullmatch(value):
            raise InvalidBlockId(
                f"Invalid {label} {value!r}; expected one non-empty segment matching "
                f"{_SEGMENT.pattern} (no '/', no whitespace). Fix the value where it is "
                "produced — sanitising it here would collapse two blocks onto one key."
            )

    def key(self) -> str:
        """A single injective string naming this block, safe as a path.

        Returns:
            ``<coordinate cache path>/<task>/<split or 'unsplit'>/<block_id>``,
            e.g. ``"dataset/themol/torsion-scan@1/torsion/train/shard-003"``, or
            ``"dataset/themol/mbis@1/electrostatic/unsplit/shard-003"`` for a
            split-mixed block. The leading segments come from
            :meth:`~molhub.coordinate.Coordinate.cache_path`, which already owns
            the repo's one rule for turning a coordinate into path segments —
            the layout the TypeScript client reads on the same machine.
        """
        coordinate = Coordinate.parse(self.source)
        split = self.split or _UNSPLIT_SEGMENT
        return f"{coordinate.cache_path()}/{self.task}/{split}/{self.block_id}"
