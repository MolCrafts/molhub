"""Tests for the append-only conveyor ledger.

Mirrors ``src/molhub/conveyor/ledger.py``. Every test runs offline against
``tmp_path`` with an injected frozen clock and a fixed actor, so the bytes a
record serialises to are fully determined by the code under test.

Two constructor shapes the spec leaves implicit are assumed here, because a test
cannot call a dataclass without picking one:

* ``LedgerRecord(block=BlockId, state=, actor=, at=, size_bytes=, payload=)`` —
  one ``BlockId`` field rather than four re-spelled block columns; the flat
  ``source`` / ``task`` / ``split`` / ``block_id`` columns are a serialisation
  concern and are asserted on the *file*, not on the dataclass.
* ``ttl`` is a :class:`datetime.timedelta`, so the unit of a lease is carried by
  the type instead of a bare number.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from molhub.conveyor.block import BlockId, BlockState, IllegalTransition
from molhub.conveyor.ledger import (
    Clock,
    InvalidRecord,
    LeaseRecord,
    Ledger,
    LedgerCorruption,
    LedgerRecord,
    SystemClock,
)

ACTOR = "1234@golden-host"
OTHER_ACTOR = "5678@golden-host"
MOMENT = datetime(2026, 8, 14, 9, 15, tzinfo=UTC)
TTL = timedelta(seconds=60)
EXPIRES = MOMENT + TTL

BLOCK = BlockId("dataset:themol/torsion-scan@1", "torsion", "train", "shard-003")
OTHER = BlockId("dataset:themol/torsion-scan@1", "torsion", "val", "shard-004")

# The eleven keys of a transition line, from the spec's worked example.
RECORD_KEYS = frozenset(
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
        "digest",
    }
)


class _FrozenClock:
    """Stand-in for :class:`SystemClock` — one fixed, timezone-aware instant."""

    def __init__(self, moment: datetime = MOMENT) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


@pytest.fixture
def ledger_path(tmp_path):
    return tmp_path / "conveyor.jsonl"


@pytest.fixture
def ledger(ledger_path):
    return Ledger(ledger_path, clock=_FrozenClock(), actor=ACTOR)


def _open(path: Path, *, actor: str = ACTOR) -> Ledger:
    """A second :class:`Ledger` over the same path — a fresh process, in effect."""
    return Ledger(path, clock=_FrozenClock(), actor=actor)


def _record(**overrides: object) -> LedgerRecord:
    """A valid :class:`LedgerRecord` with *overrides* applied to one field."""
    fields: dict[str, object] = {
        "block": BLOCK,
        "state": BlockState.READY,
        "actor": ACTOR,
        "at": MOMENT,
        "size_bytes": 2_000_000_000,
        "payload": {},
    }
    fields.update(overrides)
    return LedgerRecord(**fields)  # type: ignore[arg-type]


def _raw_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _bodies(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in _raw_lines(path)]


def _rewrite_line(path: Path, number: int, replacement: str) -> None:
    """Replace the 1-based line *number*, leaving every other byte untouched."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    terminator = "\n" if lines[number - 1].endswith("\n") else ""
    lines[number - 1] = replacement.rstrip("\n") + terminator
    path.write_text("".join(lines), encoding="utf-8")


def _flip_one_hex_character(line: str) -> str:
    """Flip a single hex character of the line's digest, keeping it valid hex.

    ``rsplit(":")`` handles both spellings a record could use for the field —
    ``sha256:<hex>`` or a bare hex string — so the test pins corruption
    detection, not the digest's serialised form.
    """
    hexdigest = str(json.loads(line)["digest"]).rsplit(":", 1)[-1]
    flipped = ("1" if hexdigest[0] != "1" else "2") + hexdigest[1:]
    return line.replace(hexdigest, flipped)


def _tamper_with_the_body(line: str) -> str:
    """Rewrite one body value, leaving the recorded digest in place."""
    body = json.loads(line)
    body["actor"] = "9999@other-host"
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _hand_written_remote_then_ready(tmp_path: Path) -> Path:
    """A ledger file whose two lines record ``remote -> ready`` for one block.

    Both lines are written by the ledger itself, from the legal history
    ``remote -> downloading -> ready``, so each digest is genuinely valid and
    only their *sequence* is impossible. Per-record digests do not chain — which
    is exactly why the legality check has to exist on the read side too.
    """
    donor_path = tmp_path / "donor.jsonl"
    donor = _open(donor_path)
    donor.append(BLOCK, BlockState.REMOTE)
    donor.append(BLOCK, BlockState.DOWNLOADING)
    donor.append(BLOCK, BlockState.READY)
    remote_line, _downloading, ready_line = donor_path.read_text(encoding="utf-8").splitlines(
        keepends=True
    )

    forged = tmp_path / "hand-written.jsonl"
    forged.write_text(remote_line + ready_line, encoding="utf-8")
    return forged


class TestLedgerRecord:
    """Record invariants: the failure-shaped values never reach the file."""

    def test_a_valid_record_keeps_its_fields(self):
        record = _record()
        assert (record.block, record.state, record.actor, record.at) == (
            BLOCK,
            BlockState.READY,
            ACTOR,
            MOMENT,
        )

    def test_a_naive_timestamp_is_rejected(self):
        """A ledger without an offset cannot be compared across machines."""
        with pytest.raises(InvalidRecord):
            _record(at=datetime(2026, 8, 14, 9, 15))

    def test_zero_size_bytes_is_rejected(self):
        """Zero is not a smaller artifact; it is the shape of a failed transfer."""
        with pytest.raises(InvalidRecord):
            _record(size_bytes=0)

    def test_negative_size_bytes_is_rejected(self):
        with pytest.raises(InvalidRecord):
            _record(size_bytes=-1)

    def test_unknown_size_bytes_is_accepted(self):
        assert _record(size_bytes=None).size_bytes is None

    def test_unknown_size_bytes_serialises_as_null(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE, size_bytes=None)
        assert _bodies(ledger_path)[0]["size_bytes"] is None

    def test_a_non_string_payload_value_is_rejected(self):
        """Payload is diagnostics only; a typed field is what decisions read."""
        with pytest.raises(InvalidRecord):
            _record(payload={"attempt": 3})

    def test_an_over_cap_line_is_rejected(self):
        with pytest.raises(InvalidRecord):
            _record(payload={"note": "x" * 4096})


class TestLedgerAppend:
    """Writing one fact: the injected seams, the line, and the refusal."""

    def test_the_fake_clock_satisfies_the_seam_it_stands_in_for(self):
        assert isinstance(_FrozenClock(), Clock)

    def test_the_default_clock_is_utc_aware(self):
        """The default stamp must survive the naive-datetime invariant."""
        assert SystemClock().now().utcoffset() == timedelta(0)

    def test_construction_touches_no_file(self, ledger_path):
        Ledger(ledger_path)
        assert not ledger_path.exists()

    def test_a_first_append_writes_exactly_one_terminated_line(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        data = ledger_path.read_bytes()
        assert data.endswith(b"\n") and data.count(b"\n") == 1

    def test_the_line_carries_the_eleven_documented_keys(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        assert set(_bodies(ledger_path)[0]) == RECORD_KEYS

    def test_the_line_declares_its_record_kind(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        assert _bodies(ledger_path)[0]["record"] == "transition"

    def test_the_line_carries_the_block_identity(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        body = _bodies(ledger_path)[0]
        assert (body["source"], body["task"], body["split"], body["block_id"]) == (
            BLOCK.source,
            BLOCK.task,
            BLOCK.split,
            BLOCK.block_id,
        )

    def test_the_line_is_stamped_with_the_injected_actor(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        assert _bodies(ledger_path)[0]["actor"] == ACTOR

    def test_the_line_is_stamped_with_the_injected_clock(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        assert _bodies(ledger_path)[0]["at"] == MOMENT.isoformat()

    def test_the_state_is_written_at_the_string_boundary(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.DOWNLOADING)
        assert _bodies(ledger_path)[0]["state"] == BlockState.DOWNLOADING.value

    def test_append_returns_the_record_it_wrote(self, ledger):
        record = ledger.append(BLOCK, BlockState.REMOTE)
        assert (record.block, record.state, record.actor, record.at) == (
            BLOCK,
            BlockState.REMOTE,
            ACTOR,
            MOMENT,
        )

    def test_the_payload_defaults_to_empty(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        assert _bodies(ledger_path)[0]["payload"] == {}

    def test_a_given_size_is_recorded(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE, size_bytes=2_000_000_000)
        assert _bodies(ledger_path)[0]["size_bytes"] == 2_000_000_000

    def test_an_illegal_transition_raises(self, ledger):
        ledger.append(BLOCK, BlockState.REMOTE)
        with pytest.raises(IllegalTransition):
            ledger.append(BLOCK, BlockState.READY)

    def test_an_illegal_transition_writes_nothing(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        before = ledger_path.stat().st_size
        with pytest.raises(IllegalTransition):
            ledger.append(BLOCK, BlockState.READY)
        assert ledger_path.stat().st_size == before

    def test_a_self_transition_is_recorded_not_refused(self, ledger, ledger_path):
        """Idempotency (I5): re-running a stage records a fact, it does not raise."""
        ledger.append(BLOCK, BlockState.REMOTE)
        ledger.append(BLOCK, BlockState.REMOTE)
        assert len(_raw_lines(ledger_path)) == 2

    def test_records_are_returned_in_the_order_they_were_appended(self, ledger):
        ledger.append(BLOCK, BlockState.REMOTE)
        ledger.append(BLOCK, BlockState.DOWNLOADING)
        ledger.append(BLOCK, BlockState.READY)
        states = tuple(record.state for record in ledger.records())
        assert states == (BlockState.REMOTE, BlockState.DOWNLOADING, BlockState.READY)


class TestLedgerReplay:
    """Reading the file back, including after a kill mid-append."""

    def test_an_absent_file_replays_to_an_empty_mapping(self, tmp_path):
        assert dict(_open(tmp_path / "never-written.jsonl").replay()) == {}

    def test_an_empty_file_replays_to_an_empty_mapping(self, ledger, ledger_path):
        ledger_path.write_bytes(b"")
        assert dict(ledger.replay()) == {}

    def test_absence_is_not_remote(self, ledger):
        """The ledger asserts only states it witnessed; "not started" is the caller's read."""
        ledger.append(BLOCK, BlockState.REMOTE)
        replayed = ledger.replay()
        assert OTHER not in replayed and replayed.get(OTHER) is None

    def test_the_last_state_wins(self, ledger):
        for state in (
            BlockState.REMOTE,
            BlockState.DOWNLOADING,
            BlockState.READY,
            BlockState.CONSUMED,
        ):
            ledger.append(BLOCK, state)
        assert dict(ledger.replay()) == {BLOCK: BlockState.CONSUMED}

    def test_every_block_the_file_mentions_is_keyed(self, ledger):
        ledger.append(BLOCK, BlockState.REMOTE)
        ledger.append(OTHER, BlockState.REMOTE)
        ledger.append(BLOCK, BlockState.DOWNLOADING)
        ledger.append(BLOCK, BlockState.READY)
        assert dict(ledger.replay()) == {BLOCK: BlockState.READY, OTHER: BlockState.REMOTE}

    def test_a_torn_final_line_replays_to_the_pre_crash_mapping(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        ledger.append(BLOCK, BlockState.DOWNLOADING)
        good_bytes = ledger_path.stat().st_size
        ledger.append(BLOCK, BlockState.READY)
        data = ledger_path.read_bytes()
        assert good_bytes + 20 < len(data), "the fragment must be shorter than a whole line"
        ledger_path.write_bytes(data[: good_bytes + 20])

        assert dict(_open(ledger_path).replay()) == {BLOCK: BlockState.DOWNLOADING}

    def test_the_next_append_leaves_no_fragment(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        ledger.append(BLOCK, BlockState.DOWNLOADING)
        good_bytes = ledger_path.stat().st_size
        ledger.append(BLOCK, BlockState.READY)
        ledger_path.write_bytes(ledger_path.read_bytes()[: good_bytes + 20])

        resumed = _open(ledger_path)
        resumed.append(BLOCK, BlockState.READY)
        data = ledger_path.read_bytes()
        assert data.endswith(b"\n")
        assert [json.loads(line)["state"] for line in _raw_lines(ledger_path)] == [
            BlockState.REMOTE.value,
            BlockState.DOWNLOADING.value,
            BlockState.READY.value,
        ]

    def test_the_repaired_file_replays_to_the_resumed_state(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        good_bytes = ledger_path.stat().st_size
        ledger.append(BLOCK, BlockState.DOWNLOADING)
        ledger_path.write_bytes(ledger_path.read_bytes()[: good_bytes + 20])

        resumed = _open(ledger_path)
        resumed.append(BLOCK, BlockState.DOWNLOADING)
        assert dict(_open(ledger_path).replay()) == {BLOCK: BlockState.DOWNLOADING}

    def test_a_mid_file_corrupt_line_raises(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        ledger.append(BLOCK, BlockState.DOWNLOADING)
        ledger.append(BLOCK, BlockState.READY)
        _rewrite_line(ledger_path, 2, "{not json")
        with pytest.raises(LedgerCorruption):
            _open(ledger_path).replay()

    def test_a_mid_file_corrupt_line_is_located(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        ledger.append(BLOCK, BlockState.DOWNLOADING)
        ledger.append(BLOCK, BlockState.READY)
        _rewrite_line(ledger_path, 2, "{not json")
        with pytest.raises(LedgerCorruption) as excinfo:
            _open(ledger_path).replay()
        message = str(excinfo.value)
        assert ":2:" in message and str(ledger_path) in message

    def test_a_flipped_hex_character_is_detected(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        ledger.append(BLOCK, BlockState.DOWNLOADING)
        ledger.append(BLOCK, BlockState.READY)
        line = _raw_lines(ledger_path)[1]
        _rewrite_line(ledger_path, 2, _flip_one_hex_character(line))
        with pytest.raises(LedgerCorruption, match=":2:"):
            _open(ledger_path).replay()

    def test_a_tampered_body_value_is_detected(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        ledger.append(BLOCK, BlockState.DOWNLOADING)
        ledger.append(BLOCK, BlockState.READY)
        line = _raw_lines(ledger_path)[1]
        _rewrite_line(ledger_path, 2, _tamper_with_the_body(line))
        with pytest.raises(LedgerCorruption, match=":2:"):
            _open(ledger_path).replay()

    def test_a_terminated_but_corrupt_final_line_is_not_a_torn_tail(self, ledger, ledger_path):
        """A complete-but-corrupt last record is bit rot, not a crash artifact."""
        ledger.append(BLOCK, BlockState.REMOTE)
        ledger.append(BLOCK, BlockState.DOWNLOADING)
        line = _raw_lines(ledger_path)[1]
        _rewrite_line(ledger_path, 2, _flip_one_hex_character(line))
        assert ledger_path.read_bytes().endswith(b"\n")
        with pytest.raises(LedgerCorruption):
            _open(ledger_path).replay()

    def test_an_unterminated_tail_is_the_only_silent_discard(self, ledger, ledger_path):
        ledger.append(BLOCK, BlockState.REMOTE)
        good_bytes = ledger_path.stat().st_size
        ledger.append(BLOCK, BlockState.DOWNLOADING)
        ledger_path.write_bytes(ledger_path.read_bytes()[: good_bytes + 20])
        assert dict(_open(ledger_path).replay()) == {BLOCK: BlockState.REMOTE}

    def test_a_recorded_impossible_history_raises_on_read(self, tmp_path):
        forged = _hand_written_remote_then_ready(tmp_path)
        with pytest.raises(IllegalTransition) as excinfo:
            _open(forged).replay()
        message = str(excinfo.value).lower()
        assert BlockState.REMOTE.value in message and BlockState.READY.value in message

    def test_the_refused_history_names_the_line(self, tmp_path):
        forged = _hand_written_remote_then_ready(tmp_path)
        with pytest.raises(IllegalTransition) as excinfo:
            _open(forged).replay()
        # Either locator spelling is accepted; what is pinned is that the
        # offending line is identified rather than left for a bisect.
        assert re.search(r"(:2:|line 2)", str(excinfo.value))


class TestLedgerLeases:
    """TTL records, not ``fcntl`` locks: expiry and release share one rule."""

    def test_lease_returns_one_record_per_block(self, ledger):
        records = ledger.lease([BLOCK, OTHER], ttl=TTL)
        assert len(records) == 2 and all(isinstance(r, LeaseRecord) for r in records)

    def test_a_lease_record_carries_the_holder_and_the_deadline(self, ledger):
        (record,) = ledger.lease([BLOCK], ttl=TTL)
        assert (record.block, record.holder, record.expires_at) == (BLOCK, ACTOR, EXPIRES)

    def test_a_lease_is_active_strictly_before_it_expires(self, ledger):
        ledger.lease([BLOCK], ttl=TTL)
        assert ledger.active_leases(now=EXPIRES - timedelta(seconds=1))[BLOCK] == (ACTOR,)

    def test_a_lease_is_gone_at_exactly_its_deadline(self, ledger):
        """Strict ``expires_at > now``: at the deadline the grip is already lost."""
        ledger.lease([BLOCK], ttl=TTL)
        assert BLOCK not in ledger.active_leases(now=EXPIRES)

    def test_a_lease_is_gone_after_its_deadline(self, ledger):
        ledger.lease([BLOCK], ttl=TTL)
        assert BLOCK not in ledger.active_leases(now=EXPIRES + timedelta(seconds=1))

    def test_the_default_now_comes_from_the_injected_clock(self, ledger):
        ledger.lease([BLOCK], ttl=TTL)
        assert BLOCK in ledger.active_leases()

    def test_a_lease_needs_no_transition_history(self, ledger):
        """Pre-registration ("next I need these") composes with the state machine."""
        ledger.lease([BLOCK], ttl=TTL)
        assert BLOCK in ledger.active_leases() and BLOCK not in ledger.replay()

    def test_leases_are_not_transition_records(self, ledger):
        ledger.lease([BLOCK], ttl=TTL)
        assert ledger.records() == ()

    def test_two_holders_on_one_block_both_appear(self, ledger_path):
        _open(ledger_path, actor=ACTOR).lease([BLOCK], ttl=TTL)
        _open(ledger_path, actor=OTHER_ACTOR).lease([BLOCK], ttl=TTL)
        holders = _open(ledger_path).active_leases(now=MOMENT)[BLOCK]
        assert set(holders) == {ACTOR, OTHER_ACTOR}

    def test_releasing_one_holder_leaves_the_other(self, ledger_path):
        first = _open(ledger_path, actor=ACTOR)
        second = _open(ledger_path, actor=OTHER_ACTOR)
        first.lease([BLOCK], ttl=TTL)
        second.lease([BLOCK], ttl=TTL)
        first.release([BLOCK])
        assert second.active_leases(now=MOMENT)[BLOCK] == (OTHER_ACTOR,)

    def test_a_released_lease_is_immediately_inactive(self, ledger):
        ledger.lease([BLOCK], ttl=TTL)
        ledger.release([BLOCK])
        assert BLOCK not in ledger.active_leases(now=MOMENT)

    def test_release_returns_exactly_the_blocks_it_released(self, ledger):
        ledger.lease([BLOCK], ttl=TTL)
        assert ledger.release([BLOCK, OTHER]) == frozenset({BLOCK})

    def test_releasing_an_unheld_block_returns_an_empty_set(self, ledger):
        ledger.lease([BLOCK], ttl=TTL)
        assert ledger.release([OTHER]) == frozenset()

    def test_re_releasing_returns_an_empty_set(self, ledger):
        ledger.lease([BLOCK], ttl=TTL)
        ledger.release([BLOCK])
        assert ledger.release([BLOCK]) == frozenset()

    def test_re_releasing_writes_no_new_line(self, ledger, ledger_path):
        ledger.lease([BLOCK], ttl=TTL)
        ledger.release([BLOCK])
        before = ledger_path.stat().st_size
        ledger.release([BLOCK])
        assert ledger_path.stat().st_size == before

    def test_leases_survive_a_fresh_instance_over_the_same_path(self, ledger, ledger_path):
        ledger.lease([BLOCK], ttl=TTL)
        assert _open(ledger_path).active_leases(now=MOMENT)[BLOCK] == (ACTOR,)

    def test_two_plan_scoped_instances_hold_independent_leases(self, ledger_path):
        """I9 refcounts by actor: one ``Ledger`` per plan, all on one path."""
        _open(ledger_path, actor="plan:a").lease([BLOCK], ttl=TTL)
        _open(ledger_path, actor="plan:b").lease([BLOCK], ttl=TTL)
        holders = _open(ledger_path).active_leases(now=MOMENT)[BLOCK]
        assert set(holders) == {"plan:a", "plan:b"}

    def test_one_plans_release_does_not_drop_the_other_plans_grip(self, ledger_path):
        plan_a = _open(ledger_path, actor="plan:a")
        plan_b = _open(ledger_path, actor="plan:b")
        plan_a.lease([BLOCK], ttl=TTL)
        plan_b.lease([BLOCK], ttl=TTL)
        assert plan_a.release([BLOCK]) == frozenset({BLOCK})
        assert plan_b.active_leases(now=MOMENT)[BLOCK] == ("plan:b",)
