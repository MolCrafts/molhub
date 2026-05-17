"""Tests for dataset protocols and built-in concrete helpers."""

from __future__ import annotations

import numpy as np
import pytest
from molpy.core.frame import Block, Frame

from molhub.dataset.protocol import (
    InMemoryDataset,
    IterableDataset,
    MapDataset,
    SubsetDataset,
    TargetSchema,
)


def _make_frame(z: list[int]) -> Frame:
    """Create a minimal Frame with an atoms block for testing."""
    n = len(z)
    atoms = Block()
    atoms["element"] = np.array(["H"] * n, dtype="U3")
    atoms["x"] = np.zeros(n, dtype=np.float64)
    atoms["y"] = np.zeros(n, dtype=np.float64)
    atoms["z"] = np.zeros(n, dtype=np.float64)
    atoms["number"] = np.array(z, dtype=np.int64)
    frame = Frame()
    frame["atoms"] = atoms
    return frame


# ---------------------------------------------------------------------------
# TargetSchema
# ---------------------------------------------------------------------------


class TestTargetSchema:
    def test_defaults(self):
        ts = TargetSchema()
        assert "energy" in ts.graph_level
        assert "forces" in ts.atom_level

    def test_custom(self):
        ts = TargetSchema(
            graph_level=frozenset({"energy", "homo"}),
            atom_level=frozenset({"forces", "charges"}),
        )
        assert ts.graph_level == frozenset({"energy", "homo"})
        assert ts.atom_level == frozenset({"forces", "charges"})

    def test_frozen(self):
        ts = TargetSchema(graph_level=frozenset({"energy"}))
        with pytest.raises(Exception):
            ts.graph_level = frozenset({"other"})  # type: ignore[misc]


# ---------------------------------------------------------------------------
# InMemoryDataset
# ---------------------------------------------------------------------------


class TestInMemoryDataset:
    def test_len_and_getitem(self):
        f0 = _make_frame([1])
        f1 = _make_frame([8])
        ds = InMemoryDataset([f0, f1])
        assert len(ds) == 2
        assert isinstance(ds[0], Frame)
        assert ds[0]["atoms"]["number"][0] == 1
        assert ds[1]["atoms"]["number"][0] == 8

    def test_source_id(self):
        ds = InMemoryDataset([], name="test")
        assert ds.source_id.startswith("memory:test")

    def test_is_map_dataset(self):
        ds = InMemoryDataset([])
        assert isinstance(ds, MapDataset)


# ---------------------------------------------------------------------------
# SubsetDataset
# ---------------------------------------------------------------------------


class TestSubsetDataset:
    def test_subset(self):
        base = InMemoryDataset(
            [_make_frame([1]), _make_frame([6]), _make_frame([8])],
            name="base",
        )
        sub = SubsetDataset(base, [0, 2])
        assert len(sub) == 2
        assert sub[0]["atoms"]["number"][0] == 1
        assert sub[1]["atoms"]["number"][0] == 8

    def test_source_id_contains_subset(self):
        base = InMemoryDataset([_make_frame([1])], name="base")
        sub = SubsetDataset(base, [0])
        assert ":subset=" in sub.source_id

    def test_is_map_dataset(self):
        base = InMemoryDataset([_make_frame([1])])
        sub = SubsetDataset(base, [0])
        assert isinstance(sub, MapDataset)

    def test_out_of_range(self):
        base = InMemoryDataset([_make_frame([1])], name="base")
        sub = SubsetDataset(base, [0])
        with pytest.raises(IndexError):
            sub[1]


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class TestMapDatasetProtocol:
    def test_runtime_checkable(self):
        assert isinstance(InMemoryDataset([]), MapDataset)

    def test_fails_on_iterable_only(self):
        class Streaming:
            @property
            def source_id(self):
                return "stream:1"

            def __iter__(self):
                yield from []

        assert not isinstance(Streaming(), MapDataset)


class TestIterableDatasetProtocol:
    def test_runtime_checkable(self):
        class Stream:
            source_id = "s:1"

            def __iter__(self):
                yield from []

        assert isinstance(Stream(), IterableDataset)

    def test_fails_on_map_only(self):
        assert not isinstance(InMemoryDataset([]), IterableDataset)
