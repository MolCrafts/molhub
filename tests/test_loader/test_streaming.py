"""Tests for the bounded-disk streaming walk — ``load_dataset(streaming=True)``.

Mirrors ``src/molhub/loader/streaming.py``. Everything runs over the synthetic
two-shard ``dataset:themol/mbis@1`` of ``tests/test_loader/conftest.py``, served
by a :class:`~tests.test_loader.conftest.LandingHub` that **lands real bytes at
the real cache paths** and watches what was on disk and in the ledger at the
instant of each fetch. That is what makes ac-002 measurable at all: "the
previous shard's bytes are gone before the next one is asked for" is a claim
about order, and order is only observable from something that was there.

Shapes picked here, because a test cannot call them otherwise:

* ``molhub.load(name, split=..., streaming=True, disk_budget=...)`` —
  ``streaming`` selects the walk and ``disk_budget`` is the byte bound D7 names,
  passed through to it. A budget that only the walk's constructor accepted would
  be unreachable from the one entry point ac-001 and ac-002 are written against.
* ``StreamingSplitDataset`` is the type that comes back, from
  ``molhub.loader.streaming``. Its constructor is deliberately **not** pinned
  here: which collaborators it takes is the implementation's call, and every
  claim below is a claim about the walk, not about its wiring.
* A shard bigger than the budget is refused with a :class:`ValueError` (a
  subclass passes): the refusal is about the value of an argument, and a
  conveyor-typed error would itself be the vocabulary leak ac-003 forbids.

**ac-003, as read here.** The criterion covers *the value ``load`` /
``prepare`` returns* and *the message of an exception they raise*. It does not
cover a record's own provenance: ``hf-facade-02``/``03`` pinned
``frame.meta["source_id"] == "dataset:themol/mbis@1#role=shard-000"``, so the
literal ``shard-`` does appear **inside a yielded record's meta**, on purpose —
that is where a record says which published file it came from, and deleting it
would cost traceability to buy a word. What must stay clean is the iterable
itself and every message a user can be shown. Both readings of "the
missing-split-key failure" are covered below: a split the table does not record,
and a record key the table does not record.

**Two more things a walk owes its caller** (ergonomics wave).

* *A crash is not a consumption.* The release sequence used to run out of one
  ``finally``, so a reader that raised while decoding a record got the same
  treatment as one that finished: ``CONSUMED``, the fetched file deleted, and
  ``REMOTE`` written. Every one of those is a false statement about an
  interrupted walk, and the delete is the expensive one — re-running a 4 GB
  file's walk after a decode bug is the whole cost of a lie in the bookkeeping.
  What a crash owes is the *release* (the handle closed, the claim given up) and
  nothing else.
* *A manifest with no digests is refused in this layer's voice.* A walk verifies
  every delivered file against a published digest, so a manifest that declares
  none cannot honestly be walked at all — but the refusal came out of the
  projection underneath, typed ``RosterError`` and quoting the artifact role,
  which is precisely the vocabulary ac-003 keeps off this path.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest
from molpy import Frame

import molhub
from molhub.conveyor import DEFAULT_BUDGET_BYTES, default_ledger_path
from molhub.conveyor.block import ConveyorError
from molhub.dataset.protocol import IterableDataset
from molhub.dataset.themol import THEMolShardDataset
from molhub.loader.streaming import StreamingSplitDataset

from .conftest import (
    COORDINATE,
    LEDGER_SEGMENTS,
    Fetch,
    LandingHub,
    build_verified_registry,
    leaks,
    write_shard,
)

#: The raw-shard lifecycle ac-002 pins, in the order the ledger records it and
#: spelled as a ledger line spells it (``BlockState``'s own string values).
#: REMOTE is declared before the fetch, DOWNLOADING is the transfer's, READY is
#: the verified local bytes, CONSUMED is exhaustion, and the closing REMOTE is
#: only true once the fetched file is gone.
LIFECYCLE: tuple[str, ...] = ("remote", "downloading", "ready", "consumed", "remote")

#: The same lifecycle, cut short by a reader that raised inside the file. It
#: stops at ``READY`` — the bytes are here and verified, which is still true —
#: and records nothing further: ``CONSUMED`` would claim a file was read to the
#: end and the closing ``REMOTE`` would claim it is gone, and after a crash
#: neither is so.
INTERRUPTED_LIFECYCLE: tuple[str, ...] = ("remote", "downloading", "ready")

#: Which record of the walk the decode instrument fails on. The train split's
#: first two records (``mbis-a``, ``mbis-c``) are both in ``shard-000``, so the
#: second one puts the failure *inside* a file whose bytes are resident and
#: whose handle is open — the only position where "what a crash leaves behind"
#: is a question with an answer.
CRASH_AT_RECORD = 2

#: The 40 GB rolling working set, promoted out of ``src/molhub/cli.py``'s
#: private ``_DEFAULT_BUDGET_BYTES``. Restated as a literal so that moving it is
#: a decision here rather than a number that tracks whatever the CLI now says.
FORTY_GIGABYTES = 40_000_000_000


def _ids(records: Iterable[object]) -> tuple[str, ...]:
    """The ``source_record_id`` of every record of an iterable, in walk order."""
    return tuple(str(record[0].meta["source_record_id"]) for record in records)


def _lifecycle(text: str) -> dict[str, tuple[str, ...]]:
    """Every transition the ledger's JSONL records, per block, in file order.

    Read back off the file rather than through :class:`~molhub.conveyor.Ledger`:
    what ac-002 pins is what a second process would see on disk, and a reader
    that folded the lines through the same type that wrote them could agree with
    a file nobody else can read.
    """
    states: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        columns = json.loads(line)
        if columns.get("record") != "transition":
            continue
        states.setdefault(str(columns["block_id"]), []).append(str(columns["state"]))
    return {block: tuple(recorded) for block, recorded in states.items()}


def _leases(text: str) -> dict[str, tuple[bool, ...]]:
    """Every lease line the ledger's JSONL records, per block, in file order.

    Each entry says only whether that record was a *claim* or a *release*: a
    release is a lease shortened to zero (``expires_at == at``), which is the
    same rule expiry uses, so "the claim was given up" is readable off the file
    without a clock. Read back off disk for the reason :func:`_lifecycle` is.
    """
    claims: dict[str, list[bool]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        columns = json.loads(line)
        if columns.get("record") != "lease":
            continue
        claims.setdefault(str(columns["block_id"]), []).append(
            str(columns["expires_at"]) > str(columns["at"])
        )
    return {block: tuple(recorded) for block, recorded in claims.items()}


class ShardDecodeFailure(RuntimeError):
    """What a broken record raises on its way out of the reader.

    Declared here rather than borrowed from production so that "the walk
    propagates it" cannot be confused with the walk raising something of its own:
    nothing in molhub can produce this type.
    """


class Decoder:
    """An instrument that makes the *n*-th record read raise, once.

    The cheapest honest way to put a failure *inside* an open file:
    ``THEMolShardDataset.__getitem__`` is the one call that turns bytes into a
    record, so failing it is a decode failure and nothing else — no truncated
    fixture to write, no second failure mode smuggled in with it. Crafting a
    defective record would exercise the reader's own validation instead, which is
    a different test that already exists.

    Args:
        at: Which record read raises, 1-based.

    Attributes:
        reads: How many records have been asked for.
        armed: Whether the next matching read still raises. A second walk over
            the same home has to be able to succeed, or "the cache was re-used"
            is unobservable.
    """

    def __init__(self, at: int) -> None:
        self.at = at
        self.reads = 0
        self.armed = True

    def disarm(self) -> None:
        """Let every further read through — the state a re-run is made in."""
        self.armed = False


class CachedBytesHub(LandingHub):
    """A :class:`LandingHub` with the real fetcher's cache short-circuit.

    ``Fetcher.fetch`` hands back a cached file without downloading it again
    (``src/molhub/sources/fetcher.py``), which is the entire value of a
    crash-preserved file: the next walk gets those bytes for free.
    :class:`LandingHub` re-lands unconditionally, so it cannot tell "the file was
    still there" from "it was fetched a second time" — this one can, and
    :attr:`downloads` counts only the transfers that really moved bytes.

    Args:
        files: Role to the pristine file whose bytes that role serves.
        home: The molhub home the cache sits under.
        coordinate: The artifact whose roles these are.
    """

    def __init__(
        self,
        files: Mapping[str, Path],
        *,
        home: Path,
        coordinate: str = COORDINATE,
    ) -> None:
        super().__init__(files, home=home, coordinate=coordinate)
        self.downloads: list[str] = []

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        """Serve what is already cached; land only what is missing."""
        wanted = tuple(roles) if roles is not None else tuple(self._files)
        cached = {role: self.cache_path(role) for role in wanted if self.cache_path(role).is_file()}
        outstanding = [role for role in wanted if role not in cached]
        if not outstanding:
            self.calls.append((coordinate, wanted))
            self.fetches.append(
                Fetch(roles=wanted, resident=self.resident(), ledger=self.ledger_text())
            )
            return dict(cached)
        self.downloads.extend(outstanding)
        return {**cached, **super().fetch(coordinate, roles=outstanding)}


def _closed_before_deleted(events: list[tuple[str, Path]]) -> bool:
    """Whether every deleted shard file was closed first, per file and per visit."""
    closed: set[Path] = set()
    for kind, path in events:
        if kind == "close":
            closed.add(path)
            continue
        if path not in closed:
            return False
        closed.discard(path)
    return True


@pytest.fixture
def budget(pristine_shards: dict[str, Path]) -> int:
    """A byte budget that admits one fixture shard and can never admit two."""
    return max(path.stat().st_size for path in pristine_shards.values()) + 1


@pytest.fixture
def smallest_shard(pristine_shards: dict[str, Path]) -> int:
    """The smallest fixture shard's size on disk, in bytes."""
    return min(path.stat().st_size for path in pristine_shards.values())


@pytest.fixture
def stream(verified_registry, landing_hub, budget):
    """The train split of the fixture dataset, streamed under a one-shard budget."""
    return molhub.load(
        "themol/mbis",
        streaming=True,
        disk_budget=budget,
        registry=verified_registry,
        hub=landing_hub,
    )


@pytest.fixture
def overflow_stream(verified_registry, landing_hub, smallest_shard):
    """The same walk under a budget no single shard can fit inside."""
    return molhub.load(
        "themol/mbis",
        streaming=True,
        disk_budget=smallest_shard - 1,
        registry=verified_registry,
        hub=landing_hub,
    )


@pytest.fixture
def handle_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Path]]:
    """Every shard-reader close and every shard-file delete, in the order they happen.

    The cheapest honest observable for "bytes reclaim when the handle is
    closed": ``THEMolShardDataset.close`` is the one call that releases the HDF5
    handle, and ``Path.unlink`` is how this repo deletes. Both are recorded with
    the resolved file they concern, so a close of *one* shard cannot vouch for
    the delete of *another*.
    """
    events: list[tuple[str, Path]] = []
    real_close = THEMolShardDataset.close
    real_unlink = Path.unlink

    def close(self: THEMolShardDataset) -> None:
        events.append(("close", Path(self.path).resolve()))
        real_close(self)

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name.startswith("shard-"):
            events.append(("unlink", self.resolve()))
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(THEMolShardDataset, "close", close)
    monkeypatch.setattr(Path, "unlink", unlink)
    return events


@pytest.fixture
def decoder(monkeypatch: pytest.MonkeyPatch) -> Decoder:
    """Make the second record of the walk raise while its file is open."""
    instrument = Decoder(at=CRASH_AT_RECORD)
    real_getitem = THEMolShardDataset.__getitem__

    def getitem(self: THEMolShardDataset, index: int) -> object:
        instrument.reads += 1
        if instrument.armed and instrument.reads == instrument.at:
            raise ShardDecodeFailure(f"record {index} of {self.path.name} did not decode")
        return real_getitem(self, index)

    monkeypatch.setattr(THEMolShardDataset, "__getitem__", getitem)
    return instrument


@pytest.fixture
def caching_hub(pristine_shards: dict[str, Path], molhub_home: Path) -> CachedBytesHub:
    """A landing hub that re-serves what is already cached instead of re-fetching."""
    return CachedBytesHub(pristine_shards, home=molhub_home)


@pytest.fixture
def interrupted(verified_registry, caching_hub, budget):
    """The same one-shard-at-a-time walk, over a hub that can prove a re-use."""
    return molhub.load(
        "themol/mbis",
        streaming=True,
        disk_budget=budget,
        registry=verified_registry,
        hub=caching_hub,
    )


class TestStreamingSplitDataset:
    """One split, walked shard by shard, inside a byte budget, conveyor invisible."""

    # -- ac-001: an iterable dataset in HuggingFace spelling ----------------

    def test_it_satisfies_the_iterable_dataset_protocol(self, stream) -> None:
        assert isinstance(stream, IterableDataset)

    def test_it_is_the_streaming_split_dataset(self, stream) -> None:
        assert isinstance(stream, StreamingSplitDataset)

    def test_every_record_is_a_molpy_object(self, stream) -> None:
        """02's ruling holds on the streaming path too: no wrapper on ``Frame``."""
        assert all(len(record) == 1 and isinstance(record[0], Frame) for record in stream)

    def test_it_yields_every_record_in_shard_order(self, stream) -> None:
        assert _ids(stream) == ("mbis-a", "mbis-b", "mbis-c", "mbis-d", "mbis-e", "mbis-f")

    def test_take_returns_an_iterable_dataset(self, stream) -> None:
        assert isinstance(stream.take(3), IterableDataset)

    def test_take_yields_that_many_records(self, stream) -> None:
        assert _ids(stream.take(3)) == ("mbis-a", "mbis-b", "mbis-c")

    def test_take_stops_at_its_bound(self, stream) -> None:
        assert _ids(stream.take(1)) == ("mbis-a",)

    # -- ac-002: the byte budget -------------------------------------------

    def test_resident_bytes_stay_within_the_budget(self, stream, landing_hub, budget) -> None:
        """Checked after *every* record, which is where a rolling walk would slip."""
        for _ in stream:
            assert landing_hub.resident_bytes() <= budget

    def test_both_shards_are_fetched_over_a_whole_walk(self, stream, landing_hub) -> None:
        """The budget bounds residency, never coverage: every shard is still read."""
        list(stream)
        assert landing_hub.roles_fetched == ("shard-000", "shard-001")

    def test_the_previous_shards_bytes_are_gone_before_the_next_is_fetched(
        self, stream, landing_hub
    ) -> None:
        list(stream)
        assert landing_hub.fetches[1].resident == ()

    def test_the_previous_shard_is_recorded_remote_before_the_next_is_fetched(
        self, stream, landing_hub
    ) -> None:
        """REMOTE claims nothing is local, so it may only be written after the delete."""
        list(stream)
        assert _lifecycle(landing_hub.fetches[1].ledger)["shard-000"] == LIFECYCLE

    def test_the_walk_leaves_nothing_resident(self, stream, landing_hub) -> None:
        list(stream)
        assert landing_hub.resident() == ()

    def test_the_ledger_records_the_full_raw_shard_lifecycle(self, stream, ledger_path) -> None:
        list(stream)
        recorded = _lifecycle(ledger_path.read_text(encoding="utf-8"))
        assert recorded == {"shard-000": LIFECYCLE, "shard-001": LIFECYCLE}

    def test_the_walk_writes_the_canonical_ledger(self, stream, ledger_path) -> None:
        """One file, shared with ``molhub cache coverage`` — two defaults desynchronize."""
        list(stream)
        assert ledger_path.is_file()

    def test_the_reader_is_closed_before_its_bytes_are_deleted(self, stream, handle_events) -> None:
        list(stream)
        assert [kind for kind, _ in handle_events].count("unlink") == 2
        assert _closed_before_deleted(handle_events), handle_events

    # -- ac-002: a shard that cannot fit -----------------------------------

    def test_a_shard_larger_than_the_budget_is_refused(self, overflow_stream) -> None:
        with pytest.raises(ValueError):
            list(overflow_stream)

    def test_a_shard_larger_than_the_budget_is_never_fetched(
        self, overflow_stream, landing_hub
    ) -> None:
        """The check is *before* the transfer, or the bound is a report, not a bound."""
        with pytest.raises(ValueError):
            list(overflow_stream)
        assert landing_hub.fetch_count == 0

    def test_the_refusal_names_the_budget_and_the_size(
        self, overflow_stream, smallest_shard
    ) -> None:
        """Actionable means the two numbers a caller has to reconcile, not a code."""
        with pytest.raises(ValueError) as raised:
            list(overflow_stream)
        message = str(raised.value)
        assert str(smallest_shard - 1) in message, message
        assert str(smallest_shard) in message, message

    def test_the_refusal_names_no_conveyor_vocabulary(self, overflow_stream) -> None:
        with pytest.raises(ValueError) as raised:
            list(overflow_stream)
        assert leaks(str(raised.value)) == []

    # -- ac-002: early exit, mid-shard --------------------------------------

    def test_an_early_exit_releases_the_shard_it_stopped_in(self, stream, ledger_path) -> None:
        """``mbis-a`` is the first of two train rows in shard-000: this stops inside it."""
        list(stream.take(1))
        assert _lifecycle(ledger_path.read_text(encoding="utf-8")) == {"shard-000": LIFECYCLE}

    def test_an_early_exit_deletes_the_bytes_it_fetched(self, stream, landing_hub) -> None:
        list(stream.take(1))
        assert landing_hub.resident() == ()

    def test_an_early_exit_never_fetches_the_next_shard(self, stream, landing_hub) -> None:
        list(stream.take(1))
        assert landing_hub.roles_fetched == ("shard-000",)

    def test_an_early_exit_closes_the_reader_before_deleting(self, stream, handle_events) -> None:
        list(stream.take(1))
        assert [kind for kind, _ in handle_events].count("unlink") == 1
        assert _closed_before_deleted(handle_events), handle_events

    # -- ac-003: the conveyor stays invisible -------------------------------

    def test_the_returned_value_names_no_conveyor_vocabulary(self, stream) -> None:
        assert leaks(repr(stream)) == []

    def test_the_bounded_view_names_no_conveyor_vocabulary(self, stream) -> None:
        assert leaks(repr(stream.take(1))) == []

    def test_assignment_has_no_unknown_name(self, verified_registry, landing_hub) -> None:
        ds = molhub.load("themol/mbis", registry=verified_registry, hub=landing_hub)
        with pytest.raises(KeyError):
            molhub.assignment(ds)["validation"]

    def test_a_record_key_the_table_does_not_record_is_refused_cleanly(
        self, tmp_path: Path, molhub_home: Path
    ) -> None:
        """The other reading: the shard's own keys are outside the table's key space.

        ``mapstyle.UnknownRecordKey`` says ``(shard role 'shard-000')`` at the end
        of its message, which is fine on the map-style path and is exactly the
        leak ac-003 forbids on this one. The streaming walk owes the user the
        same diagnosis without the transport noun.
        """
        path = write_shard(tmp_path / "foreign" / "shard-000.h5", ("molecule-1", "molecule-2"))
        registry = build_verified_registry(tmp_path / "foreign-registry", {"shard-000": path})
        hub = LandingHub({"shard-000": path}, home=molhub_home)
        dataset = molhub.load("themol/mbis", streaming=True, registry=registry, hub=hub)
        assert _ids(dataset) == ("molecule-1", "molecule-2")

    def test_a_record_still_carries_the_file_it_came_from(self, stream) -> None:
        """The interpretation above, pinned: provenance is a record's, not the walk's.

        ``shard-`` appears here and only here — inside one record's ``meta`` — and
        it is the same string ``hf-facade-02``/``03`` pinned for the map-style
        path, so the two doors hand back the same record.
        """
        first = next(iter(stream))
        assert first[0].meta["source_id"] == "dataset:themol/mbis@1#role=shard-000"


class TestACrashLeavesTheWalkReleasedButNotConsumed:
    """A reader that raises mid-file has released the file, not finished it.

    The five-step release runs out of one ``finally``, which cannot tell the two
    apart: exhaustion, an early ``take(n)`` stop and a decode failure all arrive
    there. For the first two, deleting the fetched bytes and recording
    ``CONSUMED`` / ``REMOTE`` is exactly right — the file *was* read to the point
    the caller asked for. For the third it is three false statements and one
    expensive one: the next run re-downloads a file that was sitting on disk,
    intact and verified, and ``molhub cache coverage`` counts a file as consumed
    that nobody finished reading.

    What an interrupted walk owes is the release: the handle closed (it holds
    the bytes open) and the claim given up (it is not reading any more). Those
    two already happen and are pinned here so a fix cannot drop them while
    fixing the rest.

    The instrument is :class:`Decoder` — see its docstring for why the failure
    is put in ``__getitem__`` rather than in a hand-broken fixture file.
    """

    def test_the_instrument_actually_interrupts_the_walk(self, interrupted, decoder):
        """Guards every assertion below from passing over a walk that finished."""
        with pytest.raises(ShardDecodeFailure):
            list(interrupted)
        assert decoder.reads == CRASH_AT_RECORD

    def test_the_failure_reaches_the_caller_unchanged(self, interrupted, decoder):
        """The walk is not a place a reader's exception is translated or eaten."""
        with pytest.raises(ShardDecodeFailure):
            list(interrupted)

    def test_the_fetched_file_is_still_on_disk(self, interrupted, decoder, caching_hub):
        """The expensive one: those bytes are here, verified, and were paid for."""
        with pytest.raises(ShardDecodeFailure):
            list(interrupted)
        assert caching_hub.cache_path("shard-000").is_file()

    def test_nothing_records_the_file_as_consumed(self, interrupted, decoder, ledger_path):
        """CONSUMED says a file was read to the end; this one was abandoned."""
        with pytest.raises(ShardDecodeFailure):
            list(interrupted)
        recorded = _lifecycle(ledger_path.read_text(encoding="utf-8"))["shard-000"]
        assert "consumed" not in recorded, recorded

    def test_nothing_records_the_file_as_gone(self, interrupted, decoder, ledger_path):
        """REMOTE claims nothing is local, and the bytes are still local."""
        with pytest.raises(ShardDecodeFailure):
            list(interrupted)
        recorded = _lifecycle(ledger_path.read_text(encoding="utf-8"))["shard-000"]
        assert recorded.count("remote") == 1, recorded

    def test_the_recorded_history_stops_at_verified_local_bytes(
        self, interrupted, decoder, ledger_path
    ):
        """The whole sequence, so a fix that drops one row too many shows up."""
        with pytest.raises(ShardDecodeFailure):
            list(interrupted)
        recorded = _lifecycle(ledger_path.read_text(encoding="utf-8"))
        assert recorded == {"shard-000": INTERRUPTED_LIFECYCLE}

    def test_the_reader_handle_is_closed(self, interrupted, decoder, handle_events, caching_hub):
        """An open HDF5 handle outliving the walk is a leak, crash or not."""
        with pytest.raises(ShardDecodeFailure):
            list(interrupted)
        assert ("close", caching_hub.cache_path("shard-000").resolve()) in handle_events

    def test_the_bytes_are_never_deleted(self, interrupted, decoder, handle_events):
        """The same claim as the file check above, from the other side: the delete
        does not happen at all, rather than happening and being undone."""
        with pytest.raises(ShardDecodeFailure):
            list(interrupted)
        assert [kind for kind, _ in handle_events].count("unlink") == 0, handle_events

    def test_the_claim_on_the_file_is_given_up(self, interrupted, decoder, ledger_path):
        """A crashed walk holds nothing: the last record for it is a release."""
        with pytest.raises(ShardDecodeFailure):
            list(interrupted)
        claims = _leases(ledger_path.read_text(encoding="utf-8"))["shard-000"]
        assert claims[-1] is False, claims

    def test_the_next_file_is_never_reached(self, interrupted, decoder, caching_hub):
        with pytest.raises(ShardDecodeFailure):
            list(interrupted)
        assert caching_hub.roles_fetched == ("shard-000",)

    def test_a_later_walk_re_uses_the_preserved_bytes(self, interrupted, decoder, caching_hub):
        """The point of not deleting: the re-run is a read, not a download.

        The instrument is disarmed between the two, which is what a fixed reader
        — or a retry after a transient failure — looks like from here.

        :attr:`CachedBytesHub.downloads` is cumulative over both walks and is
        never cleared, so the first walk's transfer of ``shard-000`` is in it by
        construction — it had to fetch that file to reach the record it died on.
        What the two walks are being asked is therefore *how many times*
        ``shard-000`` was moved: once, because the second walk found it on disk.
        Deleting it on the crash reads ``['shard-000', 'shard-000', 'shard-001']``
        here, which is the whole cost of that delete stated as a list.
        """
        with pytest.raises(ShardDecodeFailure):
            list(interrupted)
        decoder.disarm()
        assert _ids(interrupted) == ("mbis-a", "mbis-b", "mbis-c", "mbis-d", "mbis-e", "mbis-f")
        assert caching_hub.downloads == ["shard-000", "shard-001"], caching_hub.downloads

    def test_a_completed_walk_still_records_the_whole_lifecycle(
        self, interrupted, decoder, ledger_path
    ):
        """The contrast, so "stop recording CONSUMED" cannot be the fix: a walk
        that finishes a file really did consume it and really did delete it."""
        decoder.disarm()
        list(interrupted)
        recorded = _lifecycle(ledger_path.read_text(encoding="utf-8"))
        assert recorded == {"shard-000": LIFECYCLE, "shard-001": LIFECYCLE}


class TestAManifestThatCannotBeVerifiedIsRefusedHere:
    """No published digest means no walk — said in this layer's vocabulary.

    A walk re-verifies every delivered file against the digest the manifest
    declares; that is what makes "one file at a time" safe to delete after
    reading. A manifest that declares none therefore cannot be walked at all,
    and the projection underneath already refuses it — with
    :class:`~molhub.conveyor.roster.UnverifiableBlock`, a ``ConveyorError``
    quoting the *artifact role*. A reader who typed
    ``load_dataset(..., streaming=True)`` gets a type they cannot name and a
    sentence about ``shard-000``, which is the leak ac-003 exists to prevent.

    The same refusal, in the shape this layer's siblings already use: a
    :class:`ValueError` (as for a file the budget cannot hold, and as for a
    dataset published whole), naming the dataset, the file the digest is missing
    from, and the way to read it anyway.
    """

    @pytest.fixture
    def undigested(self, registry, hub, molhub_home):
        """The fixture registry as :func:`manifest_yaml` writes it: sizes, no digests."""
        return lambda: list(molhub.load("themol/mbis", streaming=True, registry=registry, hub=hub))

    def test_it_is_refused_as_a_value_error(self, undigested):
        with pytest.raises(ValueError):
            undigested()

    def test_it_is_not_the_bookkeeping_layers_own_error(self, undigested):
        """A caller of the façade cannot name ``ConveyorError``, and should not
        have to import a private layer to catch a manifest problem."""
        with pytest.raises(ValueError) as raised:
            undigested()
        assert not isinstance(raised.value, ConveyorError)

    def test_the_refusal_names_the_dataset(self, undigested):
        with pytest.raises(ValueError) as raised:
            undigested()
        assert COORDINATE in str(raised.value), str(raised.value)

    def test_the_refusal_names_the_file_the_digest_is_missing_from(self, undigested):
        """The filename, which is what the publishing platform shows — not the
        role, which is transport and is the leak itself."""
        with pytest.raises(ValueError) as raised:
            undigested()
        assert "mbis_0.h5" in str(raised.value), str(raised.value)

    def test_the_refusal_says_how_to_read_it_anyway(self, undigested):
        """Map-style access verifies nothing and works: a wall would be a wall."""
        with pytest.raises(ValueError) as raised:
            undigested()
        assert "streaming=False" in str(raised.value), str(raised.value)

    def test_the_refusal_names_no_conveyor_vocabulary(self, undigested):
        with pytest.raises(ValueError) as raised:
            undigested()
        assert leaks(str(raised.value)) == []

    def test_nothing_is_fetched_before_it_is_refused(self, registry, hub, molhub_home):
        """Decidable from the manifest, so it is decided before any byte moves."""
        with pytest.raises(ValueError):
            list(molhub.load("themol/mbis", streaming=True, registry=registry, hub=hub))
        assert hub.fetch_count == 0


class TestPromotedLedgerConstants:
    """The two constants D7 promoted out of the CLI, and the CLI reading them.

    They live in ``molhub.conveyor`` rather than in ``molhub.loader.streaming``
    because the streaming walk is the *second* caller: ``molhub cache coverage``
    already reads that file, and two default paths would silently desynchronize
    the leases the ledger's own R1 note is about. Tested from here because this
    is the sub-spec that promoted them.
    """

    def test_the_ledger_path_is_the_conveyor_file_under_the_home(self, tmp_path: Path) -> None:
        assert default_ledger_path(tmp_path) == tmp_path / "conveyor" / "ledger.jsonl"

    def test_the_ledger_path_agrees_with_the_layout_the_fixtures_spell(
        self, tmp_path: Path
    ) -> None:
        assert default_ledger_path(tmp_path) == tmp_path.joinpath(*LEDGER_SEGMENTS)

    def test_the_budget_constant_is_the_forty_gigabyte_working_set(self) -> None:
        assert DEFAULT_BUDGET_BYTES == FORTY_GIGABYTES

    def test_the_cli_reads_the_promoted_ledger_path(self) -> None:
        """Promotion means the CLI *uses* it; a second private copy is the defect."""
        source = (Path(molhub.__file__).parent / "cli.py").read_text(encoding="utf-8")
        assert "default_ledger_path" in source
        assert "_LEDGER_SEGMENTS" not in source

    def test_the_cli_reads_the_promoted_budget_constant(self) -> None:
        source = (Path(molhub.__file__).parent / "cli.py").read_text(encoding="utf-8")
        assert "DEFAULT_BUDGET_BYTES" in source
        assert "40_000_000_000" not in source
