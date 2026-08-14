"""Tests for the leased, bounded, re-verifying shard transfer.

Mirrors ``src/molhub/conveyor/transfer.py``. Every collaborator is a fake from
``conftest``: no registry, no driver table, no ``Fetcher``, no clock and no
sleep. What is under test is a *sequence* — lease, one DOWNLOADING row, up to
``retries`` verified attempts, delete-then-regress on exhaustion, release in a
``finally`` — so most assertions are about call order and call counts rather
than return values.

Shapes the spec leaves implicit, decided here because a test cannot avoid
picking one:

* ``PersistentDigestMismatch.attempts`` is the aggregate the error carries,
  each attempt exposing a 1-based ``index`` and a ``reason`` of ``"size"`` or
  ``"digest"``; the expected and actual values are asserted through the
  message, so their field names stay the implementer's choice.
* ``retries < 1`` is refused at construction — the loud place, per the house
  rule that a projection is loud where it is built.
* Backing off happens *between* attempts, so three attempts wait twice: a wait
  after the final attempt buys nothing and would sleep on the failure path.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from molhub.conveyor.block import BlockId, BlockState
from molhub.conveyor.roster import RemoteBlock
from molhub.conveyor.transfer import (
    ExponentialBackoff,
    PersistentDigestMismatch,
    ShardTransfer,
)
from molhub.sources import Digest, Locator
from molhub.sources.errors import DigestMismatch

from .conftest import (
    COMMIT,
    COORDINATE,
    CORRUPT_BODY,
    ROLE_NAME,
    SHARD_0_BODY,
    SHARD_0_SHA,
    SHARD_0_SIZE,
    TRUNCATED_BODY,
    FakeHub,
    FakeLedger,
    RecordingBackoff,
)

# A timedelta, not a bare number: the unit of a lease is carried by the type,
# and `-01`'s Ledger.lease adds it to an instant directly.
LEASE_TTL = timedelta(seconds=1800)
BLOCK_ID = BlockId(COORDINATE, ROLE_NAME, None, "shard-000")


def _block() -> RemoteBlock:
    """The shard-000 block of the fixture manifest, without going through a roster."""
    return RemoteBlock(
        id=BLOCK_ID,
        filename="mbis_0.h5",
        size=SHARD_0_SIZE,
        digest=Digest.sha256(SHARD_0_SHA),
        locators=(Locator.parse(f"hf://ByteDance-Seed/THEMol@{COMMIT}/MBIS/mbis_0.h5"),),
    )


def _transfer(
    hub: FakeHub,
    ledger: FakeLedger,
    backoff: RecordingBackoff,
    *,
    retries: int = 3,
) -> ShardTransfer:
    return ShardTransfer(hub, ledger, retries=retries, backoff=backoff, lease_ttl=LEASE_TTL)


class TestShardTransfer:
    """One shard at a time, correctly: nothing here reaches READY."""

    def test_it_returns_the_verified_path(self, cache_root, journal):
        hub = FakeHub(cache_root, [SHARD_0_BODY], journal=journal)
        path = _transfer(hub, FakeLedger(journal=journal), RecordingBackoff()).transfer(_block())
        assert path == hub.path_for(COORDINATE, "shard-000")
        assert path.read_bytes() == SHARD_0_BODY

    def test_it_asks_the_hub_for_exactly_this_block(self, cache_root, journal):
        hub = FakeHub(cache_root, [SHARD_0_BODY], journal=journal)
        _transfer(hub, FakeLedger(journal=journal), RecordingBackoff()).transfer(_block())
        assert [(call.coordinate, call.roles) for call in hub.calls] == [
            (COORDINATE, ("shard-000",))
        ]

    def test_a_good_payload_is_fetched_once(self, cache_root, journal):
        hub = FakeHub(cache_root, [SHARD_0_BODY], journal=journal)
        _transfer(hub, FakeLedger(journal=journal), RecordingBackoff()).transfer(_block())
        assert len(hub.calls) == 1

    def test_the_block_is_leased_before_the_first_fetch(self, cache_root, journal):
        """The mitigation for BlobStore's one fixed ``.part`` path per key."""
        hub = FakeHub(cache_root, [SHARD_0_BODY], journal=journal)
        ledger = FakeLedger(journal=journal)
        _transfer(hub, ledger, RecordingBackoff()).transfer(_block())
        assert journal.index("lease") < journal.index("fetch")
        assert [call.blocks for call in ledger.leases] == [(BLOCK_ID,)]

    def test_the_lease_carries_the_configured_ttl(self, cache_root, journal):
        """``lease_ttl`` reaches ``lease`` unchanged — no unit conversion in between."""
        hub = FakeHub(cache_root, [SHARD_0_BODY], journal=journal)
        ledger = FakeLedger(journal=journal)
        _transfer(hub, ledger, RecordingBackoff()).transfer(_block())
        assert [call.ttl for call in ledger.leases] == [timedelta(seconds=1800)]

    def test_the_lease_is_released_on_success(self, cache_root, journal):
        hub = FakeHub(cache_root, [SHARD_0_BODY], journal=journal)
        ledger = FakeLedger(journal=journal)
        _transfer(hub, ledger, RecordingBackoff()).transfer(_block())
        assert [call.blocks for call in ledger.releases] == [(BLOCK_ID,)]

    def test_the_lease_is_released_after_a_persistent_failure(self, cache_root, journal):
        """``finally``, not a happy-path-only call."""
        hub = FakeHub(cache_root, [CORRUPT_BODY], journal=journal)
        ledger = FakeLedger(journal=journal)
        with pytest.raises(PersistentDigestMismatch):
            _transfer(hub, ledger, RecordingBackoff()).transfer(_block())
        assert [call.blocks for call in ledger.releases] == [(BLOCK_ID,)]
        assert journal[-1] == "release"

    def test_one_downloading_row_is_written_per_call(self, cache_root, journal):
        hub = FakeHub(cache_root, [SHARD_0_BODY], journal=journal)
        ledger = FakeLedger(journal=journal)
        _transfer(hub, ledger, RecordingBackoff()).transfer(_block())
        assert ledger.states == (BlockState.DOWNLOADING,)

    def test_success_never_records_ready(self, cache_root, journal):
        """READY is conjunctive; this layer does none of the middle steps."""
        hub = FakeHub(cache_root, [SHARD_0_BODY], journal=journal)
        ledger = FakeLedger(journal=journal)
        _transfer(hub, ledger, RecordingBackoff()).transfer(_block())
        assert BlockState.READY not in ledger.states

    def test_a_transient_mismatch_returns_the_good_payload(self, cache_root, journal):
        hub = FakeHub(cache_root, [CORRUPT_BODY, SHARD_0_BODY], journal=journal)
        path = _transfer(hub, FakeLedger(journal=journal), RecordingBackoff()).transfer(_block())
        assert path.read_bytes() == SHARD_0_BODY

    def test_a_transient_mismatch_fetches_exactly_twice(self, cache_root, journal):
        hub = FakeHub(cache_root, [CORRUPT_BODY, SHARD_0_BODY], journal=journal)
        _transfer(hub, FakeLedger(journal=journal), RecordingBackoff()).transfer(_block())
        assert len(hub.calls) == 2

    def test_a_transient_mismatch_still_writes_one_downloading_row(self, cache_root, journal):
        """The ledger is a state log, not a retry log."""
        hub = FakeHub(cache_root, [CORRUPT_BODY, SHARD_0_BODY], journal=journal)
        ledger = FakeLedger(journal=journal)
        _transfer(hub, ledger, RecordingBackoff()).transfer(_block())
        assert ledger.states == (BlockState.DOWNLOADING,)

    def test_the_corrupt_file_is_unlinked_before_the_refetch(self, cache_root, journal):
        """``Fetcher.fetch`` serves a cached file unchecked, so a retry must delete."""
        hub = FakeHub(cache_root, [CORRUPT_BODY, SHARD_0_BODY], journal=journal)
        _transfer(hub, FakeLedger(journal=journal), RecordingBackoff()).transfer(_block())
        assert [call.existed for call in hub.calls] == [False, False]

    def test_a_transient_mismatch_backs_off_once(self, cache_root, journal):
        hub = FakeHub(cache_root, [CORRUPT_BODY, SHARD_0_BODY], journal=journal)
        backoff = RecordingBackoff(journal=journal)
        _transfer(hub, FakeLedger(journal=journal), backoff).transfer(_block())
        assert len(backoff.waits) == 1

    def test_a_persistent_mismatch_carries_every_attempt(self, cache_root, journal):
        hub = FakeHub(cache_root, [CORRUPT_BODY], journal=journal)
        with pytest.raises(PersistentDigestMismatch) as raised:
            _transfer(hub, FakeLedger(journal=journal), RecordingBackoff()).transfer(_block())
        attempts = raised.value.attempts
        assert len(attempts) == 3
        assert tuple(attempt.index for attempt in attempts) == (1, 2, 3)
        assert {attempt.reason for attempt in attempts} == {"digest"}

    def test_a_persistent_mismatch_attempts_exactly_retries_times(self, cache_root, journal):
        """``retries=3`` means three attempts, not one plus three."""
        hub = FakeHub(cache_root, [CORRUPT_BODY], journal=journal)
        with pytest.raises(PersistentDigestMismatch):
            _transfer(hub, FakeLedger(journal=journal), RecordingBackoff()).transfer(_block())
        assert len(hub.calls) == 3

    def test_a_persistent_mismatch_backs_off_between_attempts_only(self, cache_root, journal):
        hub = FakeHub(cache_root, [CORRUPT_BODY], journal=journal)
        backoff = RecordingBackoff(journal=journal)
        with pytest.raises(PersistentDigestMismatch):
            _transfer(hub, FakeLedger(journal=journal), backoff).transfer(_block())
        assert len(backoff.waits) == 2

    def test_a_persistent_mismatch_leaves_no_bytes_behind(self, cache_root, journal):
        hub = FakeHub(cache_root, [CORRUPT_BODY], journal=journal)
        with pytest.raises(PersistentDigestMismatch):
            _transfer(hub, FakeLedger(journal=journal), RecordingBackoff()).transfer(_block())
        assert not hub.path_for(COORDINATE, "shard-000").exists()

    def test_a_persistent_mismatch_regresses_to_remote(self, cache_root, journal):
        hub = FakeHub(cache_root, [CORRUPT_BODY], journal=journal)
        ledger = FakeLedger(journal=journal)
        with pytest.raises(PersistentDigestMismatch):
            _transfer(hub, ledger, RecordingBackoff()).transfer(_block())
        assert ledger.states == (BlockState.DOWNLOADING, BlockState.REMOTE)

    def test_the_bytes_are_deleted_before_the_remote_row(self, cache_root, journal):
        """REMOTE means "nothing local", so regressing to it is honest only after."""
        hub = FakeHub(cache_root, [CORRUPT_BODY], journal=journal)
        watched = hub.path_for(COORDINATE, "shard-000")
        ledger = FakeLedger(journal=journal, watch=watched)
        with pytest.raises(PersistentDigestMismatch):
            _transfer(hub, ledger, RecordingBackoff()).transfer(_block())
        assert ledger.appends[-1].state is BlockState.REMOTE
        assert ledger.appends[-1].watched_exists is False

    def test_a_persistent_failure_never_records_ready(self, cache_root, journal):
        hub = FakeHub(cache_root, [CORRUPT_BODY], journal=journal)
        ledger = FakeLedger(journal=journal)
        with pytest.raises(PersistentDigestMismatch):
            _transfer(hub, ledger, RecordingBackoff()).transfer(_block())
        assert BlockState.READY not in ledger.states

    def test_a_truncated_file_fails_on_size(self, cache_root, journal):
        """One stat beats twenty seconds of hashing a file that cannot match."""
        hub = FakeHub(cache_root, [TRUNCATED_BODY], journal=journal)
        with pytest.raises(PersistentDigestMismatch) as raised:
            _transfer(hub, FakeLedger(journal=journal), RecordingBackoff(), retries=1).transfer(
                _block()
            )
        assert [attempt.reason for attempt in raised.value.attempts] == ["size"]

    def test_a_size_failure_reports_both_values(self, cache_root, journal):
        hub = FakeHub(cache_root, [TRUNCATED_BODY], journal=journal)
        with pytest.raises(PersistentDigestMismatch) as raised:
            _transfer(hub, FakeLedger(journal=journal), RecordingBackoff(), retries=1).transfer(
                _block()
            )
        message = str(raised.value)
        assert str(SHARD_0_SIZE) in message
        assert str(len(TRUNCATED_BODY)) in message

    def test_retries_of_one_performs_a_single_attempt(self, cache_root, journal):
        hub = FakeHub(cache_root, [CORRUPT_BODY], journal=journal)
        with pytest.raises(PersistentDigestMismatch):
            _transfer(hub, FakeLedger(journal=journal), RecordingBackoff(), retries=1).transfer(
                _block()
            )
        assert len(hub.calls) == 1

    def test_retries_below_one_is_refused(self, cache_root, journal):
        """A bounded retry of zero attempts is not a policy, it is a typo."""
        hub = FakeHub(cache_root, [SHARD_0_BODY], journal=journal)
        with pytest.raises(ValueError):
            _transfer(hub, FakeLedger(journal=journal), RecordingBackoff(), retries=0)

    def test_persistent_mismatch_is_not_a_transport_digest_mismatch(self):
        """``DigestMismatch`` means "update the manifest"; this one does not."""
        assert not issubclass(PersistentDigestMismatch, DigestMismatch)


class TestExponentialBackoff:
    """The pure schedule only — a test that sleeps is a test that gets skipped."""

    def test_the_first_attempt_waits_the_base(self):
        assert ExponentialBackoff(base=0.5).delay(1) == pytest.approx(0.5)

    def test_each_attempt_doubles_the_wait(self):
        backoff = ExponentialBackoff(base=0.5)
        assert [backoff.delay(attempt) for attempt in (1, 2, 3, 4)] == pytest.approx(
            [0.5, 1.0, 2.0, 4.0]
        )

    def test_the_delay_is_pure(self):
        """No clock, no state: the schedule is testable without waiting for it."""
        backoff = ExponentialBackoff(base=0.5)
        assert backoff.delay(3) == backoff.delay(3)

    def test_the_default_schedule_grows(self):
        backoff = ExponentialBackoff()
        assert backoff.delay(1) > 0.0
        assert backoff.delay(2) == pytest.approx(2 * backoff.delay(1))
