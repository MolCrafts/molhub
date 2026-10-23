"""LMDB-backed datasets — mirrors ``src/molhub/dataset/lmdb.py``."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from molpy import Block, Frame

from molhub.dataset import AseDataset, LmdbDataset
from molhub.io.lmdb import Lmdb
from molhub.io.mrec import MrecWriter
from tests.test_io.conftest import write_aselmdb


def _collection(path: Path) -> LmdbDataset:
    with MrecWriter(
        path, backend=Lmdb, units={"energy": "kcal/mol"}, meta={"source_id": "test:set"}
    ) as out:
        for molecule, n_frames in ((0, 2), (1, 3)):
            system = Frame()
            system["atoms"] = Block({"atomic_number": np.array([8, 1, 1], np.uint64)})
            system.meta = {"molecule_id": str(molecule)}
            frames = []
            for i in range(n_frames):
                frame = Frame()
                frame["atoms"] = Block({"x": np.arange(3.0) * i})
                frame.meta = {"pe": float(i)}
                frames.append(frame)
            out.write_record(
                frames, system=system, index={"molecule": molecule, "element_mask": 0b100000010}
            )
    return LmdbDataset(path)


class TestLmdbDataset:
    def test_a_record_is_its_frames(self, tmp_path: Path) -> None:
        ds = _collection(tmp_path / "c.mrec.lmdb")
        assert len(ds) == 2 and len(ds[1]) == 3 and ds[-1][2].meta["pe"] == 2.0
        assert ds.source_id == "test:set"

    def test_sizes_and_groups_come_from_the_index(self, tmp_path: Path) -> None:
        ds = _collection(tmp_path / "c.mrec.lmdb")
        assert ds.atoms_per_record.tolist() == [6, 9]
        assert ds.molecule_index().tolist() == [0, 1]
        assert ds.element_mask().tolist() == [0b100000010] * 2
        assert type(ds).counted_tables == {"atoms": "atoms_per_record"}


class TestAseDataset:
    def test_ase_rows_land_on_molrec_conventions(self, tmp_path: Path) -> None:
        path = tmp_path / "rows.aselmdb"
        write_aselmdb(
            path,
            {
                1: {
                    "numbers": np.array([8, 1], dtype=np.int64),
                    "positions": np.zeros((2, 3)),
                    "energy": -2.5,
                    "forces": np.ones((2, 3)),
                    "data": {"charge": -1, "spin": 2},
                    "cell": np.array([[10.0, 0.0, 0.0], [1.0, 11.0, 0.0], [0.0, 0.0, 12.0]]),
                    "pbc": np.array([True, False, True]),
                }
            },
            nextid=2,
        )
        ds = AseDataset([path], source_id="ase:test")
        (frame,) = ds[0]
        assert sorted(frame["atoms"].keys()) == ["atomic_number", "fx", "fy", "fz", "x", "y", "z"]
        assert frame.meta["pe"] == -2.5 and frame.meta["total_charge"] == -1
        assert ds.units["energy"] == "eV"
        assert frame.box.pbc.tolist() == [True, False, True]
        assert frame.box.lengths.tolist() == pytest.approx([10.0, (1.0**2 + 11.0**2) ** 0.5, 12.0])
