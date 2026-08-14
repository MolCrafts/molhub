"""The conveyor's one durable memory: what happened to which block, and who holds it.

One append-only JSONL file, one JSON object per line, two record kinds
discriminated by the ``record`` column. :class:`LedgerRecord` says *this block
reached this state*; :class:`LeaseRecord` says *this holder claims this block
until this instant*. They share one file because they are the same fact stream
about the same subject and share one crash-repair rule; duplicating that rule
across two files would be the real coupling. The named split trigger is a
**third** record kind — that splits the reader.

**The append protocol, and the repair it depends on.** A record is written as
one ``write()`` of one canonical line terminated by ``\\n``, then flushed and
``fsync``ed. Replay therefore sees only two shapes: whole lines, and — after a
process is killed mid-write — one unterminated fragment at the end. That
fragment is a *torn tail*: it is discarded silently, and the offset where it
starts is remembered as the last good boundary. The first write after such a
replay **truncates the file back to that boundary** before it writes. Without
the truncation the new record would concatenate onto the fragment and corrupt a
line boundary permanently; with it, a killed process resumes into a
byte-identical file. Everything else is a hard stop: a *terminated* line that
does not parse, misses a column, or does not match its own digest is bit rot or
an interleaved writer, not a crash artifact, and :class:`LedgerCorruption` names
``path:line`` rather than guessing which columns were the true ones.

**R1 — one transition writer per ledger; any number of lease holders.**
:meth:`Ledger.append` replays once and then maintains its view incrementally, so
a second process that writes *transitions* concurrently would be invisible to
the first and could have an illegal transition accepted or a legal one refused.
The repair truncation has the same exposure: it removes only bytes after the
last valid record, but a line another process appended between replay and
truncation would be lost. Lease writes are safe under concurrency — each line is
self-contained, holders differ, ordering does not matter — and every read
(:meth:`Ledger.records`, :meth:`Ledger.replay`, :meth:`Ledger.active_leases`)
re-reads from disk, so cross-process lease visibility is already correct. The
constraint is therefore: **reads re-read; transition writes assume a single
writer, and repair happens at start-up before other processes attach.** Writer
election and multi-node visibility belong to the residency stage.

**Plan-scoped actors.** Leases key on ``(block, holder)`` where ``holder`` is
the :class:`Ledger` instance's ``actor``, which defaults to
``"<pid>@<hostname>"``. Refcounting is therefore *by actor*: a process driving
several consumer plans must hold **one Ledger per plan**, each constructed with
an explicit ``actor="plan:<id>"``, all pointing at the same file. Two plans
sharing one instance would collapse onto a single holder key, and one plan's
:meth:`Ledger.release` would drop the other's grip.

**Per-record digests, and the never-compute rule.** Every line carries a sha256
over the canonical JSON of its own body with the ``digest`` column removed,
computed through :class:`~molhub.sources.digest.Sha256Stream` and compared with
:meth:`~molhub.sources.digest.Digest.matches`, which is constant-time. This does
not touch the repo rule that *molhub never computes a digest of its own*
(``.claude/notes/notes.md`` § "版本标识靠 DOI 与钉版本的 locator，不靠 digest"):
that rule is about **upstream artifacts**, where a self-computed digest would
only record what one download happened to contain and would force hauling a
whole artifact before it could be catalogued. A ledger record is molhub's own
bytes, authored locally, whole, in memory, one line at a time; its digest makes
no provenance claim about anything upstream and detects only local corruption
and torn writes in a file molhub itself wrote. Nothing here digests fetched
content. A hash *chain* was rejected: it buys tamper-evidence nobody asked for
and would force every appender to know the previous digest, serialising exactly
the multi-holder lease writes the design depends on.

**The 4096-byte line cap** is not a claim about POSIX write atomicity. It is a
bound that keeps a concurrent-append interleave from spanning many records and
keeps the torn-tail repair singular — at most one fragment, always at the end.
It is enforced when a record is constructed, so a record that cannot be written
never exists.

Reference:
    ``.claude/specs/streaming-data-tiers-03-conveyor-01-ledger.md`` §§ 4-7.
"""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from molhub.conveyor.block import BlockId, BlockState, ConveyorError, IllegalTransition
from molhub.sources.digest import Digest, Sha256Stream
from molhub.sources.errors import InvalidDigest

__all__ = [
    "Clock",
    "SystemClock",
    "LedgerRecord",
    "LeaseRecord",
    "Ledger",
    "InvalidRecord",
    "LedgerCorruption",
]

_TRANSITION_KIND = "transition"
_LEASE_KIND = "lease"
_DIGEST_COLUMN = "digest"

# Including the newline. See the module docstring: a bound, not an atomicity claim.
_MAX_RECORD_BYTES = 4096

_TRANSITION_COLUMNS = frozenset(
    {
        "record",
        "source",
        "task",
        "split",
        "block_id",
        "state",
        "actor",
        "at",
        "size_bytes",
        "payload",
        _DIGEST_COLUMN,
    }
)

_LEASE_COLUMNS = frozenset(
    {
        "record",
        "source",
        "task",
        "split",
        "block_id",
        "holder",
        "at",
        "expires_at",
        _DIGEST_COLUMN,
    }
)


class InvalidRecord(ConveyorError):
    """A record's own values could not honestly be written to the ledger."""


class LedgerCorruption(ConveyorError):
    """A complete line in the ledger file does not verify.

    Distinct from a torn tail, which is an expected crash artifact and is
    discarded silently. This one means bit rot or an interleaved writer, so the
    message names ``path:line`` and the read stops there.
    """


def _canonical(body: Mapping[str, object]) -> str:
    """Serialise *body* the one way this package serialises anything.

    Sorted keys and no whitespace, so the same values always produce the same
    bytes — which is what makes a digest over them mean something.
    """
    return json.dumps(dict(body), sort_keys=True, separators=(",", ":"))


def _digest_of(body: Mapping[str, object]) -> Digest:
    """The sha256 of *body*'s canonical JSON, with the digest column removed."""
    stream = Sha256Stream()
    payload = {column: value for column, value in body.items() if column != _DIGEST_COLUMN}
    stream.update(_canonical(payload).encode("utf-8"))
    return stream.digest()


def _line_for(body: Mapping[str, object]) -> str:
    """The exact terminated line *body* is written as, digest column included.

    Args:
        body: The record's flat columns, with or without a digest column.

    Returns:
        One canonical JSON object terminated by ``\\n``.

    Raises:
        InvalidRecord: If the line would exceed the 4096-byte cap.
    """
    stamped = {column: value for column, value in body.items() if column != _DIGEST_COLUMN}
    stamped[_DIGEST_COLUMN] = str(_digest_of(stamped))
    line = _canonical(stamped) + "\n"
    written = len(line.encode("utf-8"))
    if written > _MAX_RECORD_BYTES:
        raise InvalidRecord(
            f"Record serialises to {written} bytes, over the {_MAX_RECORD_BYTES}-byte line "
            "cap that keeps the torn-tail repair singular. Shorten or drop the payload — "
            "it is diagnostics only, so nothing reads it."
        )
    return line


def _require_aware(label: str, value: datetime) -> None:
    """Refuse a timestamp that cannot be ordered against another machine's."""
    if not isinstance(value, datetime):
        raise InvalidRecord(f"{label} must be a datetime; got {value!r}.")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise InvalidRecord(
            f"{label} {value.isoformat()!r} carries no UTC offset. Stamp it from a Clock — "
            "SystemClock returns timezone-aware UTC — so records written on two machines "
            "can be ordered against each other."
        )


def _text(columns: Mapping[str, object], column: str) -> str:
    """Read one string column of a parsed line, refusing any other JSON type."""
    value = columns[column]
    if not isinstance(value, str):
        raise InvalidRecord(f"Column {column!r} must be a string; got {value!r}.")
    return value


def _instant(columns: Mapping[str, object], column: str) -> datetime:
    """Read one ISO-8601 column of a parsed line as a datetime."""
    return datetime.fromisoformat(_text(columns, column))


def _string_map(value: object, *, label: str) -> dict[str, str]:
    """Read *value* as a string-to-string mapping, refusing anything else."""
    if not isinstance(value, Mapping):
        raise InvalidRecord(f"{label} must be a mapping of strings to strings; got {value!r}.")
    entries: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise InvalidRecord(
                f"{label} entry {key!r}: {item!r} is not string-to-string. {label} is "
                "diagnostics only and no code may branch on it — anything a decision "
                "reads gets a typed field of its own."
            )
        entries[key] = item
    return entries


def _checked_size(value: object) -> int | None:
    """Normalise a ``size_bytes`` value: a positive count, or ``None`` for unknown."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRecord(f"size_bytes must be a whole number of bytes or None; got {value!r}.")
    if value <= 0:
        raise InvalidRecord(
            f"size_bytes {value} is not positive. Zero is not a smaller artifact, it is the "
            "shape of an interrupted transfer; pass None when the size is unknown."
        )
    return value


def _block_from(columns: Mapping[str, object]) -> BlockId:
    """Rebuild a block identity from the four flat columns of a parsed line."""
    split = columns["split"]
    return BlockId(
        source=_text(columns, "source"),
        task=_text(columns, "task"),
        split=None if split is None else _text(columns, "split"),
        block_id=_text(columns, "block_id"),
    )


def _require_columns(columns: Mapping[str, object], expected: frozenset[str], kind: str) -> None:
    """Refuse a line whose column set is not exactly the one *kind* declares."""
    if set(columns) != expected:
        raise InvalidRecord(
            f"{kind} line has columns {sorted(columns)}, expected exactly {sorted(expected)}. "
            "A changed record format changes the conveyor root's name, not this reader."
        )


@runtime_checkable
class Clock(Protocol):
    """Where a record's timestamp comes from.

    One verb, satisfied by shape rather than by subclassing. The seam is not
    symmetry: injecting a fixed instant is what makes the bytes a ledger writes
    fully determined by the code under test, so the crash-resume regression can
    compare files byte for byte.
    """

    def now(self) -> datetime:
        """Return the current instant, timezone-aware."""
        ...


class SystemClock:
    """The wall clock, in UTC.

    UTC rather than local time because a ledger is read on a different machine
    than the one that wrote it, and a naive stamp cannot be ordered at all.
    """

    def now(self) -> datetime:
        """Return the current instant as a timezone-aware UTC datetime."""
        return datetime.now(UTC)


@dataclass(frozen=True)
class LedgerRecord:
    """One transition fact: this block reached this state, recorded by this actor.

    The identity is one :class:`~molhub.conveyor.block.BlockId` field in memory
    and four flat columns on disk, so a line stays greppable by source or by
    task without a parser.

    Attributes:
        block: Which block the fact is about.
        state: The state the block reached.
        actor: Who recorded it — ``"<pid>@<hostname>"`` by default, or a plan id.
        at: Timezone-aware instant the fact was recorded.
        size_bytes: Bytes the block occupies locally when known, else ``None``.
            Never ``0``: a transition that certifies bytes landed cannot
            honestly certify zero of them.
        payload: Diagnostics only, string to string. No code in this package or
            its successors may branch on payload content — that rule is what
            keeps it from becoming an ambient context blob.
    """

    block: BlockId
    state: BlockState
    actor: str
    at: datetime
    size_bytes: int | None = None
    payload: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.actor, str) or not self.actor:
            raise InvalidRecord(
                f"actor must be a non-empty string; got {self.actor!r}. It is the holder "
                "key leases refcount by, so a blank one would merge two plans."
            )
        _require_aware("at", self.at)
        object.__setattr__(self, "size_bytes", _checked_size(self.size_bytes))
        object.__setattr__(
            self, "payload", MappingProxyType(_string_map(self.payload, label="payload"))
        )
        # Serialising here is the cap check: a record that could not be written
        # never exists, so `append` cannot discover the problem half-way.
        self.line()

    def line(self) -> str:
        """The exact line this record is written as.

        Returns:
            One canonical JSON object carrying its own digest, terminated by
            ``\\n``.

        Raises:
            InvalidRecord: If the line would exceed the 4096-byte cap.
        """
        return _line_for(self._columns())

    def _columns(self) -> dict[str, object]:
        """This record's flat file columns, digest excluded."""
        return {
            "record": _TRANSITION_KIND,
            "source": self.block.source,
            "task": self.block.task,
            "split": self.block.split,
            "block_id": self.block.block_id,
            "state": self.state.value,
            "actor": self.actor,
            "at": self.at.isoformat(),
            "size_bytes": self.size_bytes,
            "payload": dict(self.payload),
        }

    @classmethod
    def _from_columns(cls, columns: Mapping[str, object]) -> LedgerRecord:
        """Rebuild a record from one parsed line, refusing anything unusable."""
        _require_columns(columns, _TRANSITION_COLUMNS, _TRANSITION_KIND)
        return cls(
            block=_block_from(columns),
            state=BlockState.parse(_text(columns, "state")),
            actor=_text(columns, "actor"),
            at=_instant(columns, "at"),
            size_bytes=_checked_size(columns["size_bytes"]),
            payload=_string_map(columns["payload"], label="payload"),
        )


@dataclass(frozen=True)
class LeaseRecord:
    """One holder's timed claim on one block.

    A durable line, not an ``fcntl`` lock: on the target filesystem whole-file
    locking across clients is a correctness and performance hazard, and a lock
    dies with its process leaving nothing anyone can audit afterwards. A lease
    expires on its own, and release is the same rule shortened to zero
    (``expires_at == at``), so expiry and release share one code path.

    Attributes:
        block: The block being claimed.
        holder: The claiming actor — the plan id under plan-scoped refcounting.
        at: Timezone-aware instant the claim was recorded.
        expires_at: Instant the claim lapses. Active means strictly
            ``expires_at > now``: at exactly the deadline the grip is gone.
    """

    block: BlockId
    holder: str
    at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.holder, str) or not self.holder:
            raise InvalidRecord(
                f"holder must be a non-empty string; got {self.holder!r}. Leases refcount "
                "by holder, so a blank one would merge two claims into one."
            )
        _require_aware("at", self.at)
        _require_aware("expires_at", self.expires_at)
        if self.expires_at < self.at:
            raise InvalidRecord(
                f"Lease expires_at {self.expires_at.isoformat()!r} precedes at "
                f"{self.at.isoformat()!r}; pass a non-negative ttl. Releasing is a "
                "zero-length lease, not a negative one."
            )
        self.line()

    def line(self) -> str:
        """The exact line this lease is written as.

        Returns:
            One canonical JSON object carrying its own digest, terminated by
            ``\\n``.

        Raises:
            InvalidRecord: If the line would exceed the 4096-byte cap.
        """
        return _line_for(self._columns())

    def _columns(self) -> dict[str, object]:
        """This lease's flat file columns, digest excluded."""
        return {
            "record": _LEASE_KIND,
            "source": self.block.source,
            "task": self.block.task,
            "split": self.block.split,
            "block_id": self.block.block_id,
            "holder": self.holder,
            "at": self.at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    @classmethod
    def _from_columns(cls, columns: Mapping[str, object]) -> LeaseRecord:
        """Rebuild a lease from one parsed line, refusing anything unusable."""
        _require_columns(columns, _LEASE_COLUMNS, _LEASE_KIND)
        return cls(
            block=_block_from(columns),
            holder=_text(columns, "holder"),
            at=_instant(columns, "at"),
            expires_at=_instant(columns, "expires_at"),
        )


@dataclass(frozen=True)
class _Scan:
    """What one pass over the ledger file yields.

    Every public read needs one of these fields and the pass is shared, so this
    is a narrow view of one file read — not an ambient blob layers reach into.

    Attributes:
        transitions: Every transition record, in file order.
        leases: Every lease record, in file order.
        states: Last state per block, folded in file order.
        repair_to: Offset of the torn tail's first byte, or ``None`` when the
            file ends on a line boundary.
    """

    transitions: tuple[LedgerRecord, ...]
    leases: tuple[LeaseRecord, ...]
    states: Mapping[BlockId, BlockState]
    repair_to: int | None


class Ledger:
    """An append-only record of what happened to which block, over one file.

    Args:
        path: The ledger file. Nothing is read or written at construction, so a
            :class:`Ledger` can be built before the file or its directory
            exists; the directory is created on the first write. The path is
            supplied by the caller and no environment variable is consulted —
            the conveyor root is a later stage's decision.
        clock: Anything satisfying :class:`Clock`; defaults to
            :class:`SystemClock`.
        actor: Who is writing, and the holder key leases refcount by. Defaults
            to ``"<pid>@<hostname>"``. Pass a plan id to scope leases to a plan.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Clock | None = None,
        actor: str | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock if clock is not None else SystemClock()
        self._actor = actor if actor is not None else f"{os.getpid()}@{socket.gethostname()}"
        self._states: dict[BlockId, BlockState] | None = None
        self._repair_to: int | None = None

    def append(
        self,
        block: BlockId,
        state: BlockState,
        *,
        size_bytes: int | None = None,
        payload: Mapping[str, str] | None = None,
    ) -> LedgerRecord:
        """Record that *block* reached *state*.

        The transition is checked against this instance's view before anything
        is written, so a refused fact leaves the file untouched. A block the
        ledger has never mentioned may be recorded in any state: absence is not
        ``REMOTE``, so there is nothing to check the first fact against.

        Args:
            block: The block the fact is about.
            state: The state it reached.
            size_bytes: Bytes it occupies locally, when known. Must be positive.
            payload: Diagnostics only, string to string.

        Returns:
            The :class:`LedgerRecord` that was written, stamped with this
            ledger's actor and its clock's instant.

        Raises:
            IllegalTransition: If the lifecycle does not allow the change.
            InvalidRecord: If a value cannot honestly be written.
        """
        states = self._writable_view()
        previous = states.get(block)
        if previous is not None:
            previous.transition_to(state)
        record = LedgerRecord(
            block=block,
            state=state,
            actor=self._actor,
            at=self._clock.now(),
            size_bytes=size_bytes,
            payload=payload if payload is not None else {},
        )
        self._write((record.line(),))
        states[block] = state
        return record

    def records(self) -> tuple[LedgerRecord, ...]:
        """Every transition the file holds, in the order it was written.

        Re-reads from disk, so records another process appended are visible.

        Raises:
            LedgerCorruption: If a complete line does not verify.
            IllegalTransition: If the recorded history is impossible.
        """
        return self._scan().transitions

    def replay(self) -> Mapping[BlockId, BlockState]:
        """The last state recorded for each block the file mentions.

        Returns:
            A read-only mapping. A block the ledger never mentioned is
            **absent** rather than ``REMOTE`` — the ledger asserts only states
            it witnessed, and "not started" is the caller's reading of absence.

        Raises:
            LedgerCorruption: If a complete line does not verify.
            IllegalTransition: If the recorded history is impossible. The state
                machine is enforced on read as well as on write, so a
                hand-edited or raced file cannot smuggle in a history the writer
                would have refused.
        """
        return MappingProxyType(dict(self._scan().states))

    def lease(self, blocks: Iterable[BlockId], *, ttl: timedelta) -> tuple[LeaseRecord, ...]:
        """Claim *blocks* for this ledger's actor for *ttl*.

        A lease is independent of the state machine: claiming a block that is
        still ``REMOTE`` is the "next I will need these" pre-registration the
        conveyor is built around.

        Args:
            blocks: The blocks to claim; each is claimed once.
            ttl: How long the claim lasts, from this ledger's clock.

        Returns:
            One :class:`LeaseRecord` per distinct block, in the order given.
        """
        at = self._clock.now()
        records = tuple(
            LeaseRecord(block=block, holder=self._actor, at=at, expires_at=at + ttl)
            for block in dict.fromkeys(blocks)
        )
        self._write(tuple(record.line() for record in records))
        return records

    def release(self, blocks: Iterable[BlockId]) -> frozenset[BlockId]:
        """Give up this actor's claim on *blocks*.

        Releasing is shortening the lease to zero, so it is the same rule
        expiry uses. A block this actor does not actively hold appends nothing
        and is simply absent from the result — idempotent, and observable
        without an exception.

        Args:
            blocks: The blocks to release.

        Returns:
            Exactly the blocks whose claim this call gave up.
        """
        at = self._clock.now()
        held = self.active_leases(now=at)
        released = tuple(
            block for block in dict.fromkeys(blocks) if self._actor in held.get(block, ())
        )
        records = tuple(
            LeaseRecord(block=block, holder=self._actor, at=at, expires_at=at) for block in released
        )
        self._write(tuple(record.line() for record in records))
        return frozenset(released)

    def active_leases(self, *, now: datetime | None = None) -> Mapping[BlockId, tuple[str, ...]]:
        """Who currently holds which block.

        Re-reads from disk, so claims other processes recorded are visible
        immediately — including those of another plan-scoped :class:`Ledger`
        over the same path.

        Args:
            now: The instant to judge against; defaults to this ledger's clock.
                Must be timezone-aware.

        Returns:
            A read-only mapping from block to its holders, in the order they
            first claimed it. A lease is active iff the newest record for
            ``(block, holder)`` has ``expires_at > now``, strictly — at exactly
            the deadline the grip is already gone. Blocks nobody holds are
            absent.
        """
        moment = now if now is not None else self._clock.now()
        _require_aware("now", moment)
        newest: dict[tuple[BlockId, str], LeaseRecord] = {}
        for record in self._scan().leases:
            newest[(record.block, record.holder)] = record
        holders: dict[BlockId, list[str]] = {}
        for (block, holder), record in newest.items():
            if record.expires_at > moment:
                holders.setdefault(block, []).append(holder)
        return MappingProxyType({block: tuple(names) for block, names in holders.items()})

    def _writable_view(self) -> dict[BlockId, BlockState]:
        """The state map this instance validates writes against.

        Replayed once and then maintained incrementally — the R1 single-writer
        constraint in the module docstring is exactly the cost of that. The
        same first pass is what learns whether a torn tail needs repairing.
        """
        if self._states is None:
            scan = self._scan()
            self._states = dict(scan.states)
            self._repair_to = scan.repair_to
        return self._states

    def _write(self, lines: tuple[str, ...]) -> None:
        """Append *lines*, truncating a torn tail away first, then fsync once.

        Each line is one ``write()``, so an interrupted batch can leave at most
        one fragment and it is always the last thing in the file — which is the
        only shape replay has to repair. The repair offset is cleared only once
        the bytes are durable: if this call dies after truncating, the next one
        truncates to the same boundary and loses nothing that was valid.
        """
        if not lines:
            return
        self._writable_view()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "ab") as handle:
            if self._repair_to is not None:
                handle.truncate(self._repair_to)
            for line in lines:
                handle.write(line.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        self._repair_to = None

    def _scan(self) -> _Scan:
        """Read the whole file once: verify every line, fold, locate a torn tail."""
        try:
            data = self._path.read_bytes()
        except FileNotFoundError:
            return _Scan((), (), {}, None)
        boundary = data.rfind(b"\n") + 1
        repair_to = boundary if boundary != len(data) else None

        transitions: list[LedgerRecord] = []
        leases: list[LeaseRecord] = []
        states: dict[BlockId, BlockState] = {}
        for number, raw in enumerate(data[:boundary].split(b"\n")[:-1], start=1):
            record = self._read(raw, number)
            if isinstance(record, LeaseRecord):
                leases.append(record)
                continue
            previous = states.get(record.block)
            if previous is not None and not previous.may_become(record.state):
                raise IllegalTransition(
                    f"{self._path}:{number}: recorded history is impossible — "
                    f"{previous.value!r} -> {record.state.value!r} for block "
                    f"{record.block.key()}. The ledger enforces the lifecycle on read "
                    "as well as on write, so this file was hand-edited or raced."
                )
            transitions.append(record)
            states[record.block] = record.state
        return _Scan(tuple(transitions), tuple(leases), states, repair_to)

    def _read(self, raw: bytes, number: int) -> LedgerRecord | LeaseRecord:
        """Parse and verify one complete line.

        Args:
            raw: The line's bytes, without its terminator.
            number: Its 1-based position, for the message.

        Returns:
            The record the line holds.

        Raises:
            LedgerCorruption: If the line does not parse, is not an object,
                does not match its own digest, declares an unknown kind, or
                carries unusable columns. Every message names ``path:line``.
        """
        location = f"{self._path}:{number}:"
        try:
            columns = json.loads(raw)
        except ValueError as error:
            raise LedgerCorruption(
                f"{location} is not JSON ({error}). Only an *unterminated* final line is a "
                "crash artifact and discarded; a complete line that does not parse is bit "
                "rot or an interleaved writer. Restore this ledger from a copy."
            ) from error
        if not isinstance(columns, dict):
            raise LedgerCorruption(
                f"{location} is a JSON {type(columns).__name__}, not an object; every "
                "ledger line is one object with a 'record' column."
            )

        recorded = columns.get(_DIGEST_COLUMN)
        if not isinstance(recorded, str):
            raise LedgerCorruption(
                f"{location} carries no {_DIGEST_COLUMN!r} column ({recorded!r}); every line "
                "digests its own body, so a line without one cannot be trusted."
            )
        try:
            declared = Digest.parse(recorded)
        except InvalidDigest as error:
            raise LedgerCorruption(
                f"{location} has an unreadable digest {recorded!r} ({error})."
            ) from error
        if not _digest_of(columns).matches(declared):
            raise LedgerCorruption(
                f"{location} does not match its own digest {recorded!r} — these bytes changed "
                "after the line was written. Restore this ledger from a copy; molhub cannot "
                "tell which columns were the true ones."
            )

        kind = columns.get("record")
        try:
            if kind == _TRANSITION_KIND:
                return LedgerRecord._from_columns(columns)
            if kind == _LEASE_KIND:
                return LeaseRecord._from_columns(columns)
        except (ConveyorError, ValueError, KeyError, TypeError) as error:
            raise LedgerCorruption(f"{location} {error}") from error
        raise LedgerCorruption(
            f"{location} declares record kind {kind!r}; this ledger holds "
            f"{_TRANSITION_KIND!r} and {_LEASE_KIND!r} records only."
        )
