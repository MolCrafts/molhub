"""Tests for dataset protocols and built-in concrete helpers."""

from __future__ import annotations

import numpy as np
import pytest
from molpy import Block, Frame

from molhub.coordinate import Coordinate
from molhub.dataset.definition import DatasetManifest
from molhub.dataset.protocol import (
    Dataset,
    InMemoryDataset,
    IterableDataset,
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

    def test_semantic_families_default_empty(self):
        ts = TargetSchema()
        assert ts.chemical_perception == frozenset()
        assert ts.mm == frozenset()
        assert ts.qm == frozenset()

    def test_custom(self):
        ts = TargetSchema(
            graph_level=frozenset({"energy", "homo"}),
            atom_level=frozenset({"forces", "charges"}),
        )
        assert ts.graph_level == frozenset({"energy", "homo"})
        assert ts.atom_level == frozenset({"forces", "charges"})

    def test_named_semantic_families(self):
        ts = TargetSchema(
            chemical_perception=frozenset({"atom_type"}),
            mm=frozenset({"energy", "forces"}),
            qm=frozenset({"U0"}),
        )
        assert ts.chemical_perception == frozenset({"atom_type"})
        assert ts.mm == frozenset({"energy", "forces"})
        assert ts.qm == frozenset({"U0"})

    def test_frozen(self):
        ts = TargetSchema(graph_level=frozenset({"energy"}))
        with pytest.raises(Exception):
            ts.graph_level = frozenset({"other"})  # ty: ignore[invalid-assignment]

    def test_semantic_families_frozen(self):
        ts = TargetSchema(mm=frozenset({"energy"}))
        with pytest.raises(Exception):
            ts.mm = frozenset({"other"})  # ty: ignore[invalid-assignment]


# ---------------------------------------------------------------------------
# InMemoryDataset
# ---------------------------------------------------------------------------


class TestInMemoryDataset:
    def test_len_and_getitem(self):
        f0 = _make_frame([1])
        f1 = _make_frame([8])
        ds = InMemoryDataset([f0, f1])
        assert len(ds) == 2
        assert len(ds[0]) == 1
        assert isinstance(ds[0][0], Frame)
        assert ds[0][0]["atoms"]["number"][0] == 1
        assert ds[1][0]["atoms"]["number"][0] == 8

    def test_source_id(self):
        ds = InMemoryDataset([], name="test")
        assert ds.source_id.startswith("memory:test")

    def test_is_dataset(self):
        ds = InMemoryDataset([])
        assert isinstance(ds, Dataset)


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
        assert sub[0][0]["atoms"]["number"][0] == 1
        assert sub[1][0]["atoms"]["number"][0] == 8

    def test_source_id_contains_subset(self):
        base = InMemoryDataset([_make_frame([1])], name="base")
        sub = SubsetDataset(base, [0])
        assert ":subset=" in sub.source_id
        # unnamed keeps the 12-hex digest form
        digest = sub.source_id.rsplit("=", 1)[-1]
        assert len(digest) == 12
        assert all(c in "0123456789abcdef" for c in digest)

    def test_named_source_id_uses_split_qualifier(self):
        base = InMemoryDataset([_make_frame([1])], name="base")
        sub = SubsetDataset(base, [0], name="molhub-random-molecule:train")
        assert sub.source_id == f"{base.source_id}#split=molhub-random-molecule:train"
        assert ":subset=" not in sub.source_id

    def test_is_dataset(self):
        base = InMemoryDataset([_make_frame([1])])
        sub = SubsetDataset(base, [0])
        assert isinstance(sub, Dataset)

    def test_out_of_range(self):
        base = InMemoryDataset([_make_frame([1])], name="base")
        sub = SubsetDataset(base, [0])
        with pytest.raises(IndexError):
            sub[1]

    def test_manifest_reads_through_to_the_parent(self):
        """A subset publishes the parent's data, so it declares the parent's units.

        Read through rather than copied, for the same reason ``source_id`` is
        derived: a consumer that cannot ask a dataset what its numbers mean ends
        up restating the unit at the call site, and a restated unit drifts.
        """
        base = InMemoryDataset([_make_frame([1])], name="base")
        declared = DatasetManifest(
            coordinate=Coordinate(kind="dataset", namespace="t", name="d", version="1"),
            units={"energy": "kcal/mol"},
        )
        base.manifest = declared
        assert SubsetDataset(base, [0]).manifest is declared

    def test_manifest_refuses_when_the_parent_declares_nothing(self):
        """A hand-built dataset of Frames declares nothing; there is none to invent."""
        base = InMemoryDataset([_make_frame([1])], name="base")
        with pytest.raises(AttributeError):
            SubsetDataset(base, [0]).manifest


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class TestDatasetProtocol:
    def test_runtime_checkable(self):
        assert isinstance(InMemoryDataset([]), Dataset)

    def test_len_and_getitem_suffice(self):
        class MapShaped:
            def __len__(self) -> int:
                return 0

            def __getitem__(self, index: int) -> Frame:
                raise IndexError(index)

        assert isinstance(MapShaped(), Dataset)

    def test_fails_on_iterable_only(self):
        class Streaming:
            def __iter__(self):
                yield from []

        assert not isinstance(Streaming(), Dataset)


class TestIterableDatasetProtocol:
    def test_runtime_checkable(self):
        class Stream:
            def __iter__(self):
                yield from []

        assert isinstance(Stream(), IterableDataset)

    def test_fails_on_map_only(self):
        class MapOnly:
            def __len__(self) -> int:
                return 0

            def __getitem__(self, index: int) -> Frame:
                raise IndexError(index)

        assert not isinstance(MapOnly(), IterableDataset)
