"""Tests for what the run has seen and what it can consume right now.

Mirrors ``src/molhub/conveyor/coverage.py``. Two surfaces, one module: a fold
over ``-01``'s record stream (over time) and a torch-free read of sealed
``manifest.json`` files (right now). Nothing here imports ``molix``: the fixture
manifests are written by hand in exactly the shape
``molnex:src/molix/store/block.py:1083`` writes, which is the whole point of the
handoff — molhub reads that file as JSON and molnex keeps the reader.

Shapes the spec leaves implicit, decided here because a test cannot avoid
picking one:

* ``blocks_seen`` / ``blocks_consumed`` are tuples of
  :class:`~molhub.conveyor.block.BlockId` in first-occurrence order, not strings:
  a block is addressed by its identity everywhere else in the chain.
* ``units_seen`` sums ``units_by_block`` over ``blocks_seen`` (everything that
  reached READY), while the timeline accumulates only what was **consumed** —
  which is why the two disagree in the fixture, deliberately.
* ``column_digests`` is read from the manifest's ``digests`` field, the name
  molnex writes; the molhub-side field is named for what it holds.
* The fixture's column file deliberately does **not** hash to the digest the
  fixture manifest declares, so a recomputation anywhere in
  ``src/molhub/conveyor/`` fails these tests rather than passing them by luck.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from molhub.conveyor.block import BlockId, BlockState
from molhub.conveyor.coverage import (
    BlockMetadata,
    BlockNotSealed,
    CoveragePoint,
    CoverageReport,
    ReadyBlocks,
    UnsupportedBlockFormat,
)
from molhub.conveyor.ledger import LedgerRecord
from molhub.conveyor.tier import TierStore

SOURCE = "dataset:themol/mbis@1"
TASK = "electrostatic"
ACTOR = "plan:test"

BLOCKS_SUBDIR = "conveyor/blocks"
BUDGET = 1_000_000

# A raw published shard (split unknown until its bytes are opened) and three
# derived, split-pure blocks. The split discriminates `bytes_evicted` from
# `bytes_raw_released`, so the fixture needs both kinds.
RAW = BlockId(SOURCE, TASK, None, "shard-000")
TRAIN = BlockId(SOURCE, TASK, "train", "block-000")
VAL = BlockId(SOURCE, TASK, "val", "block-001")
TEST = BlockId(SOURCE, TASK, "test", "block-002")

# Supplied by the caller from `-02`'s roster; a plain mapping, no protocol.
UNITS_BY_BLOCK: Mapping[BlockId, int] = {RAW: 6, TRAIN: 3, VAL: 2, TEST: 1}

_START = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def _at(minute: int) -> datetime:
    """A fixed instant. Stamped, never read from a clock — nothing here waits."""
    return _START + timedelta(minutes=minute)


def _record(
    block: BlockId, state: BlockState, minute: int, *, size_bytes: int | None = None
) -> LedgerRecord:
    return LedgerRecord(
        block=block, state=state, actor=ACTOR, at=_at(minute), size_bytes=size_bytes
    )


def _stream() -> tuple[LedgerRecord, ...]:
    """One shard fetched twice, prepared into three blocks, one of each reclaimed.

    Row 0 is the roster registration — a REMOTE that is *not* a deletion. Row 2
    is a dropped partial: also not a deletion, because nothing reached READY yet.
    Rows 11 and 12 are the two real reclaims, one raw (I3) and one derived (I4).
    """
    return (
        _record(RAW, BlockState.REMOTE, 0),
        _record(RAW, BlockState.DOWNLOADING, 1, size_bytes=700),
        _record(RAW, BlockState.REMOTE, 2),
        _record(RAW, BlockState.DOWNLOADING, 3, size_bytes=700),
        _record(RAW, BlockState.READY, 4, size_bytes=700),
        _record(TRAIN, BlockState.READY, 5, size_bytes=500),
        _record(VAL, BlockState.READY, 6, size_bytes=300),
        _record(TEST, BlockState.READY, 7, size_bytes=200),
        _record(TRAIN, BlockState.CONSUMED, 8),
        _record(VAL, BlockState.CONSUMED, 9),
        _record(RAW, BlockState.CONSUMED, 10),
        _record(RAW, BlockState.REMOTE, 11, size_bytes=700),
        _record(TRAIN, BlockState.REMOTE, 12, size_bytes=500),
    )


def _report(records: Iterable[LedgerRecord] | None = None) -> CoverageReport:
    return CoverageReport.replay(
        tuple(_stream() if records is None else records), units_by_block=UNITS_BY_BLOCK
    )


class TestCoverageReport:
    """Partial coverage is legitimate; unreported coverage is not (I10)."""

    def test_downloaded_bytes_count_a_retried_fetch_twice(self):
        """It measures network bytes honestly, not the size of what arrived."""
        assert _report().bytes_downloaded == 1400

    def test_prepared_bytes_sum_the_ready_records(self):
        assert _report().bytes_prepared == 1700

    def test_evicted_bytes_count_only_derived_blocks(self):
        """``split is not None`` is what separates an eviction from an I3 reclaim."""
        assert _report().bytes_evicted == 500

    def test_released_raw_bytes_count_only_published_shards(self):
        assert _report().bytes_raw_released == 700

    def test_a_remote_registration_is_not_a_deletion(self):
        """The first REMOTE for a block is where it starts, not where it went."""
        report = _report([_record(RAW, BlockState.REMOTE, 0, size_bytes=700)])
        assert report.bytes_evicted == 0
        assert report.bytes_raw_released == 0

    def test_a_dropped_partial_is_not_a_deletion(self):
        report = _report(
            [
                _record(RAW, BlockState.DOWNLOADING, 0, size_bytes=700),
                _record(RAW, BlockState.REMOTE, 1, size_bytes=700),
            ]
        )
        assert report.bytes_raw_released == 0

    def test_blocks_seen_are_the_blocks_that_reached_ready(self):
        assert _report().blocks_seen == (RAW, TRAIN, VAL, TEST)

    def test_blocks_consumed_are_in_the_order_they_were_consumed(self):
        assert _report().blocks_consumed == (TRAIN, VAL, RAW)

    def test_a_block_can_be_seen_without_being_consumed(self):
        report = _report()
        assert TEST in report.blocks_seen
        assert TEST not in report.blocks_consumed

    def test_units_seen_sum_the_units_of_every_block_seen(self):
        assert _report().units_seen == 12

    def test_the_timeline_has_one_point_per_consumed_record(self):
        assert len(_report().timeline) == 3

    def test_the_timeline_is_cumulative(self):
        assert tuple((point.blocks, point.units) for point in _report().timeline) == (
            (1, 3),
            (2, 5),
            (3, 11),
        )

    def test_a_timeline_point_carries_the_instant_it_was_reached(self):
        assert _report().timeline[0].at == _at(8)

    def test_the_timeline_is_monotone_in_time(self):
        stamps = [point.at for point in _report().timeline]
        assert stamps == sorted(stamps)

    def test_the_fraction_is_consumed_over_the_corpus(self):
        assert _report().fraction(8) == 0.375

    def test_an_empty_stream_reports_nothing_rather_than_failing(self):
        report = _report([])
        assert report.blocks_seen == ()
        assert report.blocks_consumed == ()
        assert report.units_seen == 0
        assert report.timeline == ()

    def test_the_report_is_frozen(self):
        report = _report()
        with pytest.raises(dataclasses.FrozenInstanceError):
            report.units_seen = 0  # type: ignore[misc]

    def test_a_timeline_point_is_frozen(self):
        point = _report().timeline[0]
        assert isinstance(point, CoveragePoint)
        with pytest.raises(dataclasses.FrozenInstanceError):
            point.blocks = 0  # type: ignore[misc]


# The digests the fixture manifest declares. They are not the sha256 of anything
# in the fixture directory — that is deliberate, and it is what makes
# "copied, never computed" a checkable claim rather than a promise.
BLOCK_DIGEST = "1f2e3d4c5b6a79887766554433221100" * 2
COLUMN_DIGESTS = {
    "frame.pos": "a1" * 32,
    "topology.z": "b2" * 32,
}

# The shape `molnex:src/molix/store/block.py:1083` writes. molhub reads eight of
# these fields and validates two; the rest ride along untouched.
MANIFEST_DOCUMENT: Mapping[str, object] = {
    "format": "molix.block/1",
    "schema_version": 1,
    "columns": {
        "frame.pos": {"dtype": "float32", "shape": [3], "space": "frame"},
        "topology.z": {"dtype": "int8", "shape": [], "space": "topology"},
    },
    "split": "train",
    "task_names": ["equilibrium", "torsion"],
    "units": 2,
    "rows": {"frame": 8, "topology": 24, "molecule": 2},
    "provenance": {
        "source": SOURCE,
        "generator": "molhub.conveyor.prepare.PrepareJob",
        "created_at": "2026-08-14T12:00:00+00:00",
        "units": "molecule",
    },
    "digests": dict(COLUMN_DIGESTS),
    "sealed": True,
    "block_digest": BLOCK_DIGEST,
}


def _document(**overrides: object) -> dict[str, object]:
    """The fixture manifest, with named fields replaced."""
    return {**MANIFEST_DOCUMENT, **overrides}


class FakeLedger:
    """The three verbs a tier needs, so this module never opens a real ledger file."""

    def replay(self) -> Mapping[BlockId, BlockState]:
        """No block has a recorded state; nothing here evicts."""
        return {}

    def active_leases(self, *, now: datetime | None = None) -> Mapping[BlockId, tuple[str, ...]]:
        """Nobody holds anything; nothing here evicts."""
        return {}

    def append(
        self,
        block: BlockId,
        state: BlockState,
        *,
        size_bytes: int | None = None,
        payload: Mapping[str, str] | None = None,
    ) -> None:
        """Never called: reading manifests writes no transition."""
        raise AssertionError("ReadyBlocks must not write to the ledger")


def _ready(root: Path, blocks: Mapping[BlockId, Mapping[str, object]]) -> ReadyBlocks:
    """A blocks tier holding *blocks*, each with a hand-written manifest.

    The column file's bytes are arbitrary and short: nothing in molhub opens a
    column, and if anything ever hashed one, ``BLOCK_DIGEST`` would stop matching.
    """
    store = TierStore(root, subdir=BLOCKS_SUBDIR, budget_bytes=BUDGET, ledger=FakeLedger())
    for block, document in blocks.items():
        directory = store.admit(block, nbytes=1_000)
        (directory / "frame.pos").write_bytes(b"column bytes that hash to something else")
        (directory / "manifest.json").write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )
    return ReadyBlocks(store)


class TestReadyBlocks:
    """The sampler handoff: everything molnex needs, without opening one column."""

    def test_it_names_the_block(self, tmp_path):
        (metadata,) = _ready(tmp_path, {TRAIN: MANIFEST_DOCUMENT}).metadata()
        assert metadata.block_id == TRAIN

    def test_it_carries_the_block_root(self, tmp_path):
        ready = _ready(tmp_path, {TRAIN: MANIFEST_DOCUMENT})
        (metadata,) = ready.metadata()
        assert (metadata.root / "manifest.json").is_file()

    def test_it_carries_the_split(self, tmp_path):
        (metadata,) = _ready(tmp_path, {TRAIN: MANIFEST_DOCUMENT}).metadata()
        assert metadata.split == "train"

    def test_it_carries_the_unit_count(self, tmp_path):
        (metadata,) = _ready(tmp_path, {TRAIN: MANIFEST_DOCUMENT}).metadata()
        assert metadata.units == 2

    def test_frames_come_from_the_frame_row_count(self, tmp_path):
        """The block format counts units; the sampler plans in frames."""
        (metadata,) = _ready(tmp_path, {TRAIN: MANIFEST_DOCUMENT}).metadata()
        assert metadata.frames == 8

    def test_it_carries_the_task_dictionary(self, tmp_path):
        (metadata,) = _ready(tmp_path, {TRAIN: MANIFEST_DOCUMENT}).metadata()
        assert metadata.task_names == ("equilibrium", "torsion")

    def test_the_column_digests_are_the_manifests_own(self, tmp_path):
        (metadata,) = _ready(tmp_path, {TRAIN: MANIFEST_DOCUMENT}).metadata()
        assert dict(metadata.column_digests) == COLUMN_DIGESTS

    def test_the_block_digest_is_copied_never_computed(self, tmp_path):
        """molhub never computes a digest of its own; verification is molnex's."""
        (metadata,) = _ready(tmp_path, {TRAIN: MANIFEST_DOCUMENT}).metadata()
        assert metadata.block_digest == BLOCK_DIGEST

    def test_every_sealed_block_in_the_tier_is_reported(self, tmp_path):
        ready = _ready(
            tmp_path,
            {TRAIN: MANIFEST_DOCUMENT, VAL: _document(split="val", units=1, rows={"frame": 4})},
        )
        assert {metadata.block_id: metadata.split for metadata in ready.metadata()} == {
            TRAIN: "train",
            VAL: "val",
        }

    def test_an_unsealed_block_is_refused(self, tmp_path):
        """READY is conjunctive: there is no half-ready state a consumer may read."""
        ready = _ready(tmp_path, {TRAIN: _document(sealed=False)})
        with pytest.raises(BlockNotSealed):
            ready.metadata()

    def test_an_unsupported_schema_version_is_refused(self, tmp_path):
        ready = _ready(tmp_path, {TRAIN: _document(schema_version=2)})
        with pytest.raises(UnsupportedBlockFormat):
            ready.metadata()

    def test_an_unsupported_format_is_refused(self, tmp_path):
        ready = _ready(tmp_path, {TRAIN: _document(format="molix.block/2")})
        with pytest.raises(UnsupportedBlockFormat):
            ready.metadata()

    def test_the_metadata_is_frozen(self, tmp_path):
        (metadata,) = _ready(tmp_path, {TRAIN: MANIFEST_DOCUMENT}).metadata()
        assert isinstance(metadata, BlockMetadata)
        with pytest.raises(dataclasses.FrozenInstanceError):
            metadata.units = 0  # type: ignore[misc]
