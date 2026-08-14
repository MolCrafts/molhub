#!/usr/bin/env python
"""Regression: the conveyor ledger survives a kill mid-append, byte for byte.

Exercises the public surface of ``molhub.conveyor``
(``streaming-data-tiers-03-conveyor-01-ledger``) end to end and offline, inside
a temporary directory this script creates:

1. Three blocks — two split-pure derived shards and one split-mixed published
   shard whose ``split`` is ``None`` and whose key spends the reserved
   ``unsplit`` segment — driven through their legal arcs, with one illegal
   append refused and proven to leave the file untouched.
2. A kill mid-append, simulated by appending the train shard's fourth
   transition and truncating the file to a byte offset *inside* that final line.
3. A fresh :class:`~molhub.conveyor.Ledger` over the torn file, whose
   :meth:`~molhub.conveyor.Ledger.replay` equals the hard-coded pre-crash
   ``{key: state}`` mapping — the fragment is discarded and nothing it
   half-said is believed.
4. The re-append of that same transition, yielding a file **byte-identical** to
   the uninterrupted run, pinned by a hard-coded sha256 hex literal and a
   hard-coded final line.
5. A 60 s lease: held at +30 s, gone at +61 s, and gone immediately after
   ``release`` — leases and transitions sharing one file without disturbing the
   state fold.
6. One byte flipped inside line 2 of a copy, raising
   :class:`~molhub.conveyor.LedgerCorruption` naming that line.

Determinism comes from the two seams the package exposes for exactly this: a
frozen ``Clock`` stopped at ``2026-08-14T09:15:00+00:00`` and the literal actor
``"1234@golden-host"``. Nothing here opens a socket, reads an environment
variable, or runs a third-party oracle; every expected value below is a
literal, so a change to the record format is a loud diff rather than a silent
fork.

Provenance of the goldens (this repo's own code, no external oracle):

* ``_GOLDEN_SHA256`` / ``_GOLDEN_FINAL_LINE`` — recorded from this script's own
  first run against ``src/molhub/conveyor/`` at the commit that landed it;
  command ``.venv/bin/python
  regressions/streaming-data-tiers-03-conveyor-01-ledger.py``; CPython 3.14.5,
  stdlib only; 2026-08-14. The whole-file digest is taken with stdlib
  ``hashlib`` deliberately — an outside witness, not the
  ``molhub.sources.digest.Sha256Stream`` the ledger stamps its own lines with.
* ``_PRE_CRASH_STATES`` / ``_RESUMED_STATES`` and the three block keys — the
  spec's worked examples,
  ``.claude/specs/streaming-data-tiers-03-conveyor-01-ledger.md`` §§ 3-4.

tool: python
command: python regressions/streaming-data-tiers-03-conveyor-01-ledger.py
date: 2026-08-14
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from molhub.conveyor import (  # noqa: E402
    BlockId,
    BlockState,
    Clock,
    IllegalTransition,
    InvalidBlockId,
    Ledger,
    LedgerCorruption,
)

# ---------------------------------------------------------------------------
# The two determinism seams: a stopped clock and a literal actor
# ---------------------------------------------------------------------------

_ACTOR = "1234@golden-host"
_MOMENT = datetime(2026, 8, 14, 9, 15, tzinfo=UTC)
_TTL = timedelta(seconds=60)
_HELD_AT = _MOMENT + timedelta(seconds=30)  # strictly inside the lease
_GONE_AT = _MOMENT + timedelta(seconds=61)  # strictly past its deadline

# ---------------------------------------------------------------------------
# Fixture — three blocks, one of them split-mixed (split=None)
# ---------------------------------------------------------------------------

_TORSION = "dataset:themol/torsion-scan@1"
_MBIS = "dataset:themol/mbis@1"

#: Two split-pure derived shards …
_TRAIN_SHARD = BlockId(_TORSION, "torsion", "train", "shard-003")
_VAL_SHARD = BlockId(_TORSION, "torsion", "val", "shard-004")
#: … and one published shard whose split cannot be known without opening its
#: bytes, so it is ``None`` rather than a fabricated label.
_PUBLISHED_SHARD = BlockId(_MBIS, "electrostatic", None, "shard-003")

_TRAIN_KEY = "dataset/themol/torsion-scan@1/torsion/train/shard-003"
_VAL_KEY = "dataset/themol/torsion-scan@1/torsion/val/shard-004"
_PUBLISHED_KEY = "dataset/themol/mbis@1/electrostatic/unsplit/shard-003"

_SHARD_BYTES = 2_000_000_000
_PUBLISHED_BYTES = 512_000_000

_PRE_CRASH_LINES = 9
_RESUMED_LINES = 10

#: What the ledger says before the kill: the train shard is prepared, the val
#: shard is back at REMOTE after its partial was dropped, the published shard is
#: prepared. Blocks the ledger never mentioned are *absent*, never REMOTE.
_PRE_CRASH_STATES = {
    _TRAIN_KEY: "READY",
    _VAL_KEY: "REMOTE",
    _PUBLISHED_KEY: "READY",
}

#: And after the killed transition is replayed back in.
_RESUMED_STATES = {
    _TRAIN_KEY: "CONSUMED",
    _VAL_KEY: "REMOTE",
    _PUBLISHED_KEY: "READY",
}

# ---------------------------------------------------------------------------
# Goldens — see the module docstring for provenance
# ---------------------------------------------------------------------------

_GOLDEN_SHA256 = "573c2d99807eb4a167d6c7b2dac9038bb7d2963a3935ab9af519763ad050cdc7"

#: The killed-then-resumed transition, exactly as it lands on disk: canonical
#: JSON, sorted keys, no whitespace, its own digest, one trailing newline.
_GOLDEN_FINAL_LINE = (
    '{"actor":"1234@golden-host",'
    '"at":"2026-08-14T09:15:00+00:00",'
    '"block_id":"shard-003",'
    '"digest":"sha256:18d77eca42ddbd51ba571d327fa7028d00b94289b0b45fe0681f2c24a8dae80b",'
    '"payload":{},'
    '"record":"transition",'
    '"size_bytes":null,'
    '"source":"dataset:themol/torsion-scan@1",'
    '"split":"train",'
    '"state":"consumed",'
    '"task":"torsion"}\n'
)

#: The byte the corruption leg flips lives in this column of line 2.
_FLIP_MARKER = b'"task":"torsion"'


class FrozenClock:
    """A :class:`~molhub.conveyor.Clock` stopped at one instant.

    Satisfies the protocol by shape, exactly as the package intends: injecting a
    fixed instant is what makes the bytes a ledger writes fully determined by the
    code under test, which is what lets the crash-resume leg compare two files
    byte for byte instead of "close enough".
    """

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


def _ledger(path: Path) -> Ledger:
    """A ledger over *path* with the fixed clock and the literal actor."""
    return Ledger(path, clock=FrozenClock(_MOMENT), actor=_ACTOR)


def _states(ledger: Ledger) -> dict[str, str]:
    """``replay()`` rendered as the ``{block key: state name}`` map to compare."""
    return {block.key(): state.name for block, state in ledger.replay().items()}


def _holders(ledger: Ledger, *, now: datetime) -> dict[str, tuple[str, ...]]:
    """``active_leases(now=…)`` rendered as ``{block key: holders}``."""
    return {block.key(): names for block, names in ledger.active_leases(now=now).items()}


def _drive_pre_crash(ledger: Ledger) -> None:
    """Record the three blocks' arcs up to the moment of the kill.

    Interleaved on purpose: a per-block fold that secretly tracked one global
    "current state" would pass a serial history and fail this one.
    """
    ledger.append(_TRAIN_SHARD, BlockState.REMOTE)
    ledger.append(_VAL_SHARD, BlockState.REMOTE)
    ledger.append(_PUBLISHED_SHARD, BlockState.REMOTE)
    ledger.append(_TRAIN_SHARD, BlockState.DOWNLOADING)
    ledger.append(_VAL_SHARD, BlockState.DOWNLOADING)
    ledger.append(_PUBLISHED_SHARD, BlockState.DOWNLOADING)
    # The val shard's transfer failed: the partial is dropped and the block goes
    # back to REMOTE to be retried from scratch, not forward to READY.
    ledger.append(_VAL_SHARD, BlockState.REMOTE)
    ledger.append(_TRAIN_SHARD, BlockState.READY, size_bytes=_SHARD_BYTES)
    ledger.append(
        _PUBLISHED_SHARD,
        BlockState.READY,
        size_bytes=_PUBLISHED_BYTES,
        payload={"unpacked": "ok"},
    )


# ---------------------------------------------------------------------------
# Leg 1 — identity
# ---------------------------------------------------------------------------


def check_identity() -> None:
    """The three keys are the literals below, injective, and never sanitised."""
    assert _TRAIN_SHARD.key() == _TRAIN_KEY
    assert _VAL_SHARD.key() == _VAL_KEY
    assert _PUBLISHED_SHARD.key() == _PUBLISHED_KEY
    assert len({_TRAIN_KEY, _VAL_KEY, _PUBLISHED_KEY}) == 3, "two blocks share one key"

    # `unsplit` is the segment `key()` spends on `split is None`, so accepting it
    # as a real split would map two different blocks onto one key.
    try:
        BlockId(_MBIS, "electrostatic", "unsplit", "shard-003")
    except InvalidBlockId:
        pass
    else:  # pragma: no cover - the reserved segment must never be a real split
        raise AssertionError("split='unsplit' must be refused, not accepted alongside None")

    print(
        f"  Identity: {_TRAIN_KEY}, {_VAL_KEY}, "
        f"{_PUBLISHED_KEY} (split=None -> reserved 'unsplit' segment, refused as a real split)"
    )


# ---------------------------------------------------------------------------
# Leg 2 — the uninterrupted run, which the crashed one must reproduce
# ---------------------------------------------------------------------------


def check_uninterrupted(path: Path) -> tuple[bytes, bytes]:
    """Drive the arcs to completion; pin the resulting bytes.

    Returns:
        ``(pre_crash_bytes, full_bytes)`` — the file as it stands just before the
        final transition, and with it.
    """
    ledger = _ledger(path)
    assert isinstance(FrozenClock(_MOMENT), Clock), "the frozen clock drifted from the protocol"
    assert not path.exists(), "constructing a Ledger must not touch the disk"

    _drive_pre_crash(ledger)
    pre_crash = path.read_bytes()
    assert pre_crash.endswith(b"\n")
    assert pre_crash.count(b"\n") == _PRE_CRASH_LINES
    assert _states(ledger) == _PRE_CRASH_STATES
    assert len(ledger.records()) == _PRE_CRASH_LINES

    # A block the ledger never mentioned is absent, not REMOTE.
    never_seen = BlockId(_TORSION, "torsion", "test", "shard-009")
    assert never_seen not in ledger.replay()

    # The refused fact leaves no trace: bytes cannot appear without a download
    # record, so REMOTE -> READY is one of the six illegal pairs.
    try:
        ledger.append(_VAL_SHARD, BlockState.READY, size_bytes=_SHARD_BYTES)
    except IllegalTransition:
        pass
    else:  # pragma: no cover - a silent half-ready block is what I5 exists to stop
        raise AssertionError("remote -> ready must be refused")
    assert path.read_bytes() == pre_crash, "a refused transition wrote to the file"

    ledger.append(_TRAIN_SHARD, BlockState.CONSUMED)
    full = path.read_bytes()
    assert full.startswith(pre_crash), "the append rewrote earlier lines"
    assert full.count(b"\n") == _RESUMED_LINES
    assert _states(ledger) == _RESUMED_STATES

    digest = hashlib.sha256(full).hexdigest()
    assert digest == _GOLDEN_SHA256, f"ledger bytes drifted; observed sha256 {digest}"
    final_line = full[len(pre_crash) :].decode("utf-8")
    assert final_line == _GOLDEN_FINAL_LINE, f"final line drifted; observed {final_line!r}"

    print(
        f"  Uninterrupted: {_RESUMED_LINES} lines, {len(full)} bytes, "
        f"states {_RESUMED_STATES}, sha256 {_GOLDEN_SHA256}"
    )
    return pre_crash, full


# ---------------------------------------------------------------------------
# Leg 3 — the kill mid-append, and the resume that must be byte-identical
# ---------------------------------------------------------------------------


def check_crash_resume(path: Path, pre_crash: bytes, full: bytes) -> Ledger:
    """Tear the final line, replay, re-append, compare byte for byte.

    Returns:
        The resumed ledger, for the lease leg to go on writing to.
    """
    ledger = _ledger(path)
    _drive_pre_crash(ledger)
    assert path.read_bytes() == pre_crash, "the same drive produced different bytes"
    ledger.append(_TRAIN_SHARD, BlockState.CONSUMED)
    assert path.read_bytes() == full

    # Kill the process inside the final write: keep a prefix of the last line.
    torn_at = len(full) - 20
    assert len(pre_crash) < torn_at < len(full) - 1, "the cut must land inside the final line"
    with open(path, "r+b") as handle:
        handle.truncate(torn_at)
    torn = path.read_bytes()
    assert not torn.endswith(b"\n"), "a torn tail is by definition unterminated"
    assert len(torn) == torn_at

    # A fresh Ledger — the process that died holds nothing.
    resumed = _ledger(path)
    assert _states(resumed) == _PRE_CRASH_STATES, "the torn fragment was believed"
    assert len(resumed.records()) == _PRE_CRASH_LINES

    resumed.append(_TRAIN_SHARD, BlockState.CONSUMED)
    repaired = path.read_bytes()
    assert repaired == full, "resume did not reproduce the uninterrupted file"
    digest = hashlib.sha256(repaired).hexdigest()
    assert digest == _GOLDEN_SHA256, f"resumed bytes drifted; observed sha256 {digest}"
    assert repaired.endswith(_GOLDEN_FINAL_LINE.encode("utf-8"))
    assert repaired.count(b"\n") == _RESUMED_LINES, "the fragment survived as part of a line"
    assert len(resumed.records()) == _RESUMED_LINES
    assert _states(resumed) == _RESUMED_STATES

    print(
        f"  Crash + resume: cut at byte {torn_at} of {len(full)} "
        f"({len(full) - torn_at} bytes of the final line lost), replay == pre-crash "
        f"{_PRE_CRASH_STATES}, re-append byte-identical (sha256 {_GOLDEN_SHA256})"
    )
    return resumed


# ---------------------------------------------------------------------------
# Leg 4 — TTL leases in the same file
# ---------------------------------------------------------------------------


def check_leases(ledger: Ledger, path: Path) -> None:
    """A 60 s claim: held at +30 s, expired at +61 s, gone on release."""
    granted = ledger.lease([_PUBLISHED_SHARD], ttl=_TTL)
    assert len(granted) == 1
    assert granted[0].holder == _ACTOR
    assert granted[0].expires_at == _MOMENT + _TTL

    assert _holders(ledger, now=_HELD_AT) == {_PUBLISHED_KEY: (_ACTOR,)}
    assert _holders(ledger, now=_GONE_AT) == {}, "a lease outlived its ttl"

    released = ledger.release([_PUBLISHED_SHARD])
    assert released == frozenset({_PUBLISHED_SHARD})
    assert _holders(ledger, now=_HELD_AT) == {}, "release did not take effect immediately"

    # Releasing what this actor no longer holds writes nothing and raises nothing.
    size = path.stat().st_size
    assert ledger.release([_PUBLISHED_SHARD]) == frozenset()
    assert path.stat().st_size == size

    # Lease lines share the file with transitions and do not disturb the fold.
    assert _states(ledger) == _RESUMED_STATES
    assert len(ledger.records()) == _RESUMED_LINES

    print(
        f"  Leases: {_PUBLISHED_KEY} held by {_ACTOR} at +30 s, "
        "absent at +61 s and immediately after release (re-release wrote 0 bytes)"
    )


# ---------------------------------------------------------------------------
# Leg 5 — one flipped byte, located
# ---------------------------------------------------------------------------


def check_corruption(healthy_path: Path, corrupt_path: Path, full: bytes) -> None:
    """A single flipped byte in line 2 is detected and named, not repaired."""
    healthy_path.write_bytes(full)
    assert _states(_ledger(healthy_path)) == _RESUMED_STATES, "the copy is not a healthy control"

    lines = full.split(b"\n")
    second = bytearray(lines[1])
    # The last character of the `task` value: flipping one bit of one byte turns
    # "torsion" into "torsioN" — still valid JSON, so only the digest can catch it.
    position = second.index(_FLIP_MARKER) + len(_FLIP_MARKER) - 2
    second[position] ^= 0x20
    lines[1] = bytes(second)
    corrupted = b"\n".join(lines)
    assert len(corrupted) == len(full)
    changed = sum(1 for old, new in zip(full, corrupted) if old != new)
    assert changed == 1, f"flipped {changed} bytes, not one"
    corrupt_path.write_bytes(corrupted)

    try:
        _ledger(corrupt_path).replay()
    except LedgerCorruption as error:
        message = str(error)
    else:  # pragma: no cover - silently folding bit rot into the state map
        raise AssertionError("a flipped byte must stop the read, not be folded in")
    assert f"{corrupt_path}:2:" in message, f"the corrupt line was not named: {message}"
    assert "digest" in message

    print(
        f"  Corruption: 1 byte flipped at offset {position} of line 2 -> "
        "LedgerCorruption naming ':2:'; the untouched copy still replays"
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="molhub-conveyor-ledger-") as workdir:
        root = Path(workdir)

        check_identity()
        pre_crash, full = check_uninterrupted(root / "uninterrupted" / "conveyor.jsonl")
        resumed = check_crash_resume(root / "crashed" / "conveyor.jsonl", pre_crash, full)
        check_leases(resumed, root / "crashed" / "conveyor.jsonl")
        check_corruption(root / "healthy.jsonl", root / "corrupt.jsonl", full)

    print("streaming-data-tiers-03-conveyor-01-ledger: OK")


if __name__ == "__main__":
    main()
