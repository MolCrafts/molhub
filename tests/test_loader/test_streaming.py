"""Tests for the bounded-disk streaming walk — ``load_dataset(streaming=True)``.

Mirrors ``src/molhub/loader/streaming.py``. Everything runs over the synthetic
two-shard ``dataset:themol/mbis@1`` of ``tests/test_loader/conftest.py``, served
by a :class:`~tests.test_loader.conftest.LandingHub` that **lands real bytes at
the real cache paths** and watches what was on disk and in the ledger at the
instant of each fetch. That is what makes ac-002 measurable at all: "the
previous shard's bytes are gone before the next one is asked for" is a claim
about order, and order is only observable from something that was there.

Shapes picked here, because a test cannot call them otherwise:

* ``molhub.load_dataset(name, split=..., streaming=True, disk_budget=...)`` —
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

**ac-003, as read here.** The criterion covers *the value ``load_dataset`` /
``prepare`` returns* and *the message of an exception they raise*. It does not
cover a record's own provenance: ``hf-facade-02``/``03`` pinned
``frame.meta["source_id"] == "dataset:themol/mbis@1#role=shard-000"``, so the
literal ``shard-`` does appear **inside a yielded record's meta**, on purpose —
that is where a record says which published file it came from, and deleting it
would cost traceability to buy a word. What must stay clean is the iterable
itself and every message a user can be shown. Both readings of "the
missing-split-key failure" are covered below: a split the table does not record,
and a record key the table does not record.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import pytest
from molpy import Frame

import molhub
from molhub.conveyor import DEFAULT_BUDGET_BYTES, default_ledger_path
from molhub.dataset.protocol import IterableDataset
from molhub.dataset.themol import THEMolShardDataset
from molhub.loader.streaming import StreamingSplitDataset

from .conftest import (
    LEDGER_SEGMENTS,
    TRAIN_KEYS,
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

#: The 40 GB rolling working set, promoted out of ``src/molhub/cli.py``'s
#: private ``_DEFAULT_BUDGET_BYTES``. Restated as a literal so that moving it is
#: a decision here rather than a number that tracks whatever the CLI now says.
FORTY_GIGABYTES = 40_000_000_000


def _ids(records: Iterable[Frame]) -> tuple[str, ...]:
    """The ``source_record_id`` of every record of an iterable, in walk order."""
    return tuple(str(record.meta["source_record_id"]) for record in records)


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
    return molhub.load_dataset(
        "themol/mbis",
        split="train",
        streaming=True,
        disk_budget=budget,
        registry=verified_registry,
        hub=landing_hub,
    )


@pytest.fixture
def overflow_stream(verified_registry, landing_hub, smallest_shard):
    """The same walk under a budget no single shard can fit inside."""
    return molhub.load_dataset(
        "themol/mbis",
        split="train",
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


class TestStreamingSplitDataset:
    """One split, walked shard by shard, inside a byte budget, conveyor invisible."""

    # -- ac-001: an iterable dataset in HuggingFace spelling ----------------

    def test_it_satisfies_the_iterable_dataset_protocol(self, stream) -> None:
        assert isinstance(stream, IterableDataset)

    def test_it_is_the_streaming_split_dataset(self, stream) -> None:
        assert isinstance(stream, StreamingSplitDataset)

    def test_every_record_is_a_molpy_object(self, stream) -> None:
        """02's ruling holds on the streaming path too: no wrapper on ``Frame``."""
        assert all(isinstance(record, Frame) for record in stream)

    def test_it_yields_the_train_records_in_shard_order(self, stream) -> None:
        assert _ids(stream) == TRAIN_KEYS == ("mbis-a", "mbis-c", "mbis-d")

    def test_it_yields_no_record_of_another_split(self, stream) -> None:
        """The val and test rows sit in the same two shards and must not appear."""
        assert set(_ids(stream)).isdisjoint({"mbis-b", "mbis-e", "mbis-f"})

    def test_take_returns_an_iterable_dataset(self, stream) -> None:
        assert isinstance(stream.take(3), IterableDataset)

    def test_take_yields_that_many_records(self, stream) -> None:
        assert _ids(stream.take(3)) == TRAIN_KEYS

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

    def test_a_split_the_table_does_not_record_is_refused_cleanly(
        self, verified_registry, landing_hub
    ) -> None:
        """One reading of "missing split key": no such split.

        The refusal may come from the call or from the first step of the walk;
        both are inside the ``raises`` block, because *when* it is refused is the
        implementation's call and *what it says* is not.
        """
        with pytest.raises(KeyError) as raised:
            list(
                molhub.load_dataset(
                    "themol/mbis",
                    split="validation",
                    streaming=True,
                    registry=verified_registry,
                    hub=landing_hub,
                )
            )
        assert leaks(str(raised.value)) == []

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
        dataset = molhub.load_dataset(
            "themol/mbis", split="train", streaming=True, registry=registry, hub=hub
        )
        with pytest.raises(KeyError) as raised:
            list(dataset)
        assert leaks(str(raised.value)) == []

    def test_a_record_still_carries_the_file_it_came_from(self, stream) -> None:
        """The interpretation above, pinned: provenance is a record's, not the walk's.

        ``shard-`` appears here and only here — inside one record's ``meta`` — and
        it is the same string ``hf-facade-02``/``03`` pinned for the map-style
        path, so the two doors hand back the same record.
        """
        first = next(iter(stream))
        assert first.meta["source_id"] == "dataset:themol/mbis@1#role=shard-000"


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
