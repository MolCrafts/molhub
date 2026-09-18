"""StatisticMixin scans Frames; Distrib is raw + basic stats."""

from __future__ import annotations

import numpy as np
from molpy import Block, Frame

from molhub.dataset.protocol import InMemoryDataset, SubsetDataset
from molhub.dataset.statistic import Distrib, Field


def _frame(*, n_atoms: int, energy: float) -> Frame:
    atoms = Block()
    atoms["number"] = np.ones(n_atoms, dtype=np.int64)
    frame = Frame()
    frame["atoms"] = atoms
    frame.meta = {"energy": energy}
    return frame


def test_inmemory_dataset_is_dataset_and_statistic_mixin() -> None:
    from molhub.dataset.protocol import Dataset
    from molhub.dataset.statistic import StatisticMixin

    ds = InMemoryDataset([_frame(n_atoms=2, energy=1.0)])
    assert isinstance(ds, Dataset)
    assert isinstance(ds, StatisticMixin)


def test_field_reads_natoms_and_energy_from_the_frame() -> None:
    frame = _frame(n_atoms=4, energy=-1.5)
    assert Field("graph.natoms").read(frame) == 4
    assert Field("graph.energy").read(frame) == -1.5


def test_field_missing_block_is_zero_rows() -> None:
    frame = _frame(n_atoms=3, energy=0.0)
    assert Field("bonds").read(frame) == 0
    assert Field("angles").read(frame) == 0


def test_get_distrib_graph_natoms_and_energy() -> None:
    ds = InMemoryDataset(
        [
            _frame(n_atoms=2, energy=1.5),
            _frame(n_atoms=5, energy=-0.5),
        ]
    )
    natoms = ds.get_distrib("graph.natoms")
    assert natoms.field == "graph.natoms"
    assert list(natoms.raw) == [2, 5]
    assert natoms.min == 2
    assert natoms.max == 5
    assert natoms.n == 2
    energy = ds.get_distrib("graph.energy")
    assert list(np.asarray(energy)) == [1.5, -0.5]


def test_get_distrib_two_fields_walks_getitem_once() -> None:
    class _Counted(InMemoryDataset):
        def __init__(self, frames: list[Frame]) -> None:
            super().__init__(frames)
            self.hits = 0

        def __getitem__(self, idx: int):
            self.hits += 1
            return super().__getitem__(idx)

    ds = _Counted(
        [
            _frame(n_atoms=2, energy=1.5),
            _frame(n_atoms=5, energy=-0.5),
        ]
    )
    natoms, energy = ds.get_distrib("graph.natoms", "graph.energy")
    assert ds.hits == 2
    assert list(natoms.raw) == [2, 5]
    assert list(np.asarray(energy)) == [1.5, -0.5]


def test_get_distrib_requires_a_field() -> None:
    ds = InMemoryDataset([_frame(n_atoms=1, energy=0.0)])
    try:
        ds.get_distrib()
    except TypeError:
        return
    raise AssertionError("expected TypeError")


def test_subset_get_distrib_reads_the_view_frames() -> None:
    base = InMemoryDataset(
        [
            _frame(n_atoms=2, energy=1.0),
            _frame(n_atoms=9, energy=2.0),
            _frame(n_atoms=3, energy=3.0),
        ]
    )
    view = SubsetDataset(base, [0, 2])
    natoms, energy = view.get_distrib("graph.natoms", "graph.energy")
    assert list(natoms.raw) == [2, 3]
    assert list(np.asarray(energy)) == [1.0, 3.0]


def test_distrib_is_numpy_array_for_matplotlib() -> None:
    raw = np.array([1.0, 2.0, 3.0])
    d = Distrib(field="graph.energy", raw=raw)
    assert np.array_equal(np.asarray(d), raw)
    assert np.histogram(d, bins=2)[0].sum() == 3


def test_get_distrib_reads_frames_and_does_not_infer_bonds() -> None:
    import inspect

    from molhub.dataset.statistic import Field, StatisticMixin

    assert "infer_bonds" not in inspect.getsource(Field.read)
    assert "infer_bonds" not in inspect.getsource(StatisticMixin.get_distrib)


def test_unknown_frame_field_raises() -> None:
    ds = InMemoryDataset([_frame(n_atoms=1, energy=0.0)])
    try:
        ds.get_distrib("graph.not_a_field")
    except ValueError as exc:
        assert "graph.not_a_field" in str(exc)
    else:
        raise AssertionError("expected ValueError")
