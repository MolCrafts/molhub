"""Tests for the map-style split view and its lazy shard index.

Mirrors ``src/molhub/loader/mapstyle.py``. Everything runs over the synthetic
two-shard dataset written by ``tests/test_loader/conftest.py`` into
``tmp_path``, a fake :class:`~molhub.dataset.hub.ArtifactHub` that counts every
call, and a ``tmp_path`` :class:`~molhub.conveyor.tier.DerivedLayout` — so the
two claims these tests exist to charge honestly (ac-004: length is free;
ac-005: indexing is lazy, memoized and loud on a key-space mismatch) are
measured, not asserted from a docstring.

Constructor shapes picked here, because a test cannot call them otherwise:

* ``ShardIndex(shards, coordinate=..., roles=..., layout=...)`` — *shards* is
  the dataset definition (anything with ``load(role)``, which is what
  ``THEMolMBIS`` is); the coordinate is the **resolved** one, because that is
  what the memo is filed under; ``roles`` is the shard order the registry
  manifest declares. ``index.keys(role)`` is the memoized group-key list.
* ``SplitDataset(shards, split=..., table=..., index=...)`` — three narrow
  collaborators plus the split name, and no fourth. ``len`` reads the table;
  ``__getitem__`` walks the index. The index owns *which keys a shard holds*;
  the dataset owns *which of them are in this split*, which is why the
  key-space refusal is raised on the dataset's walk (it is the half holding the
  table) and not inside the index.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from molhub.loader.mapstyle import ShardIndex, SplitDataset, UnknownRecordKey
from molpy import Frame

from molhub.conveyor.splits import _SplitTable
from molhub.coordinate import Coordinate
from molhub.dataset import THEMolMBIS
from molhub.dataset.protocol import Dataset

from .conftest import COORDINATE, SHARD_KEYS, SPLIT_COUNTS, TRAIN_KEYS, FakeHub, write_shard


@pytest.fixture
def shards(hub) -> THEMolMBIS:
    """The THEMol MBIS definition, bound to the counting fake hub."""
    return THEMolMBIS(hub=hub)


@pytest.fixture
def table(splits_root) -> _SplitTable:
    """The uuid-keyed split table of the miniature derivation."""
    return _SplitTable.from_derived(splits_root, source="mbis")


@pytest.fixture
def index(shards, layout) -> ShardIndex:
    """A shard index over both fixture shards, memoizing under ``tmp_path``."""
    return ShardIndex(
        shards,
        coordinate=Coordinate.parse(COORDINATE),
        roles=tuple(SHARD_KEYS),
        layout=layout,
    )


@pytest.fixture
def train(shards, index, table) -> SplitDataset:
    """The train split of the fixture dataset, map-style."""
    return SplitDataset(shards, split="train", table=table, index=index)


def _files_under(directory: Path) -> dict[str, bytes]:
    """Every file below *directory*, by relative path, with its bytes."""
    if not directory.is_dir():
        return {}
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


class TestSplitDataset:
    """The i-th record of split X, and what asking for it costs."""

    def test_len_is_the_tables_count_and_fetches_nothing(self, train, hub):
        """ac-004, verbatim: one gz CSV already loaded, zero shard bytes."""
        assert len(train) == SPLIT_COUNTS["train"] == 3
        assert hub.fetch_count == 0

    def test_it_satisfies_the_map_style_dataset_protocol(self, train):
        assert isinstance(train, Dataset)

    def test_the_first_row_is_the_first_train_record(self, train):
        record = train[0]
        assert isinstance(record, Frame)
        assert record.meta["source_record_id"] == "mbis-a"

    def test_a_record_is_the_molpy_object_the_shard_reader_builds(self, train):
        """02's ruling holds through the façade: no wrapper on top of ``Frame``."""
        record = train[0]
        assert list(record["atoms"]["number"]) == [1, 8, 1]
        assert record.meta["source_id"] == "dataset:themol/mbis@1#role=shard-000"

    def test_reading_the_first_row_fetches_exactly_one_shard(self, train, hub):
        train[0]
        assert hub.fetch_count == 1
        assert hub.roles_fetched == ("shard-000",)

    def test_a_second_row_in_the_same_shard_fetches_nothing_new(self, train, hub):
        """Sequential access pays once per shard, not once per row."""
        train[0]
        assert train[1].meta["source_record_id"] == "mbis-c"
        assert hub.fetch_count == 1

    def test_a_row_in_a_later_shard_walks_the_shards_in_order(self, train, hub):
        """The cost the info states out loud: earlier shards get indexed too."""
        assert train[2].meta["source_record_id"] == "mbis-d"
        assert hub.roles_fetched == ("shard-000", "shard-001")

    def test_the_rows_are_the_split_in_shard_order(self, train):
        assert tuple(train[i].meta["source_record_id"] for i in range(len(train))) == TRAIN_KEYS

    def test_an_index_past_the_end_raises_index_error(self, train):
        with pytest.raises(IndexError):
            train[len(train)]

    def test_a_key_outside_the_tables_key_space_is_refused(self, tmp_path, table, layout):
        """ac-005: no runtime fallback, no guessing — name both key spaces and stop."""
        path = write_shard(tmp_path / "other" / "shard-000.h5", ("molecule-1", "molecule-2"))
        hub = FakeHub({"shard-000": path})
        shards = THEMolMBIS(hub=hub)
        index = ShardIndex(
            shards,
            coordinate=Coordinate.parse(COORDINATE),
            roles=("shard-000",),
            layout=layout,
        )
        dataset = SplitDataset(shards, split="train", table=table, index=index)
        with pytest.raises(UnknownRecordKey) as raised:
            dataset[0]
        message = str(raised.value)
        assert "uuid" in message, message
        assert "identity" in message, message


class TestShardIndex:
    """Lazy, per shard, memoized on disk — and never eager over the dataset."""

    def test_construction_indexes_nothing(self, index, hub):
        """An eager index would want every shard local: 6.5 TB for THEMol."""
        assert index.roles == tuple(SHARD_KEYS)
        assert hub.fetch_count == 0

    def test_keys_are_the_shards_group_keys_in_order(self, index):
        assert index.keys("shard-000") == ("mbis-a", "mbis-b", "mbis-c")

    def test_only_the_shard_that_was_asked_for_is_indexed(self, index, hub):
        index.keys("shard-000")
        assert hub.roles_fetched == ("shard-000",)

    def test_the_index_is_written_under_the_derived_layout(self, index, layout):
        """``DerivedLayout`` is reused, not re-invented: the memo is an artifact."""
        before = _files_under(layout.directory)
        index.keys("shard-000")
        assert _files_under(layout.directory) != before

    def test_index_written_once_and_reused(self, shards, index, layout, hub, shard_paths):
        """ac-005: a second construction answers without reopening the shard.

        The shard file is deleted and the hub sealed between the two, so a
        reader that quietly re-derived the index fails loudly instead of
        passing a little more slowly.
        """
        first = index.keys("shard-000")
        written = _files_under(layout.directory)
        assert written != {}

        shard_paths["shard-000"].unlink()
        hub.seal()
        reopened = ShardIndex(
            shards,
            coordinate=Coordinate.parse(COORDINATE),
            roles=tuple(SHARD_KEYS),
            layout=layout,
        )
        assert reopened.keys("shard-000") == first
        assert _files_under(layout.directory) == written
