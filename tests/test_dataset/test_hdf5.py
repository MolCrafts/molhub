"""HDF5 collection datasets — mirrors ``src/molhub/dataset/hdf5.py``."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from molpy import Block, Frame

from molhub.dataset import Hdf5Dataset
from molhub.io.hdf5 import Hdf5
from molhub.io.mrec import MrecWriter


def _collection(path: Path) -> Hdf5Dataset:
    with MrecWriter(
        path, backend=Hdf5, units={"energy": "kcal/mol"}, meta={"source_id": "test:set"}
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
                frames,
                system=system,
                index={"molecule": molecule, "element_mask": 0b100000010},
            )
    return Hdf5Dataset(path)


class TestHdf5Dataset:
    def test_a_record_is_its_frames(self, tmp_path: Path) -> None:
        ds = _collection(tmp_path / "c.mrec.h5")
        assert len(ds) == 2 and len(ds[1]) == 3 and ds[-1][2].meta["pe"] == 2.0
        assert ds.source_id == "test:set"

    def test_sizes_and_groups_come_from_the_index(self, tmp_path: Path) -> None:
        ds = _collection(tmp_path / "c.mrec.h5")
        assert ds.atoms_per_record.tolist() == [6, 9]
        assert ds.molecule_index().tolist() == [0, 1]
        assert ds.element_mask().tolist() == [0b100000010] * 2
        assert type(ds).counted_tables == {"atoms": "atoms_per_record"}
