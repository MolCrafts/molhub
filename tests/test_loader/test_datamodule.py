"""molhub DataModule packing reads ``get_distrib``."""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest


def _require_molix() -> None:
    """Import molix, honouring ``MOLNEX_SRC`` like the neighbor tests."""
    src = os.environ.get("MOLNEX_SRC")
    if src and src not in sys.path:
        sys.path.insert(0, src)
    pytest.importorskip("molix")


class _CountedSource:
    def __init__(self, counts: list[int]) -> None:
        self._counts = np.asarray(counts, dtype=np.int64)
        self.calls: list[str] = []

    def __len__(self) -> int:
        return int(self._counts.shape[0])

    def __getitem__(self, idx: int) -> int:
        return idx

    def get_distrib(self, field: str):
        from molhub.dataset.statistic import Distrib

        self.calls.append(field)
        if field != "graph.natoms":
            raise ValueError(f"unknown field {field!r}")
        return Distrib(field=field, raw=self._counts.copy())


class TestDataModule:
    def test_fixed_batch_size_does_not_scan_distrib(self) -> None:
        _require_molix()
        from molhub.loader import DataModule

        source = _CountedSource([2, 3, 4])
        DataModule(
            source,
            source,
            batch_size=2,
            num_workers=0,
            pin_memory=False,
            persistent_workers=False,
        )
        assert source.calls == []

    def test_atom_budget_reads_graph_natoms_distrib(self) -> None:
        _require_molix()
        from molhub.loader import DataModule

        source = _CountedSource([2, 3, 4])
        dm = DataModule(
            source,
            source,
            batch_size=8,
            max_atoms_per_batch=6,
            num_workers=0,
            pin_memory=False,
            persistent_workers=False,
        )
        assert source.calls == ["graph.natoms"]
        assert dm.atom_counts.tolist() == [2, 3, 4]

    def test_atom_counts_kw_does_not_scan_distrib(self) -> None:
        _require_molix()
        import torch

        from molhub.loader import DataModule

        source = _CountedSource([2, 3, 4])
        dm = DataModule(
            source,
            source,
            batch_size=8,
            max_atoms_per_batch=6,
            atom_counts=torch.tensor([2, 3, 4]),
            num_workers=0,
            pin_memory=False,
            persistent_workers=False,
        )
        assert source.calls == []
        assert dm.atom_counts.tolist() == [2, 3, 4]

    def test_cache_kw_is_rejected(self) -> None:
        _require_molix()
        from molhub.loader import DataModule

        source = _CountedSource([2, 3])
        try:
            DataModule(
                source,
                source,
                max_atoms_per_batch=8,
                cache=object(),
                num_workers=0,
                pin_memory=False,
                persistent_workers=False,
            )
        except TypeError as exc:
            assert "cache" in str(exc)
        else:
            raise AssertionError("expected TypeError")
