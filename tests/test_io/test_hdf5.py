"""mrec collections on HDF5 — synthetic files."""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

import h5py
import numpy as np
import pytest

from molhub.io.hdf5 import Hdf5
from molhub.io.mrec import FORMAT, MrecRecords, MrecWriter


def _frame(**columns: np.ndarray) -> object:
    from molpy import Block, Frame

    frame = Frame()
    frame["atoms"] = Block(columns)
    return frame


def _water_record(n_frames: int) -> tuple[object, list[object]]:
    from molpy import Block, Frame

    system = Frame()
    system["atoms"] = Block(
        {"element": np.array(["O", "H", "H"]), "atomic_number": np.array([8, 1, 1], np.uint64)}
    )
    system["bonds"] = Block(
        {"atomi": np.array([0, 0], np.uint64), "atomj": np.array([1, 2], np.uint64)}
    )
    system.meta = {"molecule_id": "water", "total_charge": 0}
    frames = []
    for i in range(n_frames):
        frame = _frame(x=np.arange(3.0) + i, fx=np.full(3, float(i)))
        frame.meta = {"pe": -1.0 - i}
        frames.append(frame)
    return system, frames


class TestMrecHdf5Writer:
    def test_frames_hold_only_state_and_read_back_whole(self, tmp_path: Path) -> None:
        path = tmp_path / "c.mrec.h5"
        system, frames = _water_record(3)
        with MrecWriter(path, backend=Hdf5, units={"length": "angstrom"}) as out:
            out.write_record(frames, system=system, steps=[0, 5, 9], index={"molecule": 4})
        reader = MrecRecords(Hdf5(path))
        record = reader.read_record(0)
        assert len(record) == 3
        assert sorted(record[2]["atoms"].keys()) == ["atomic_number", "element", "fx", "x"]
        assert record[2].meta == {"molecule_id": "water", "total_charge": 0, "pe": -3.0, "step": 9}
        assert "bonds" in record[1].keys()
        assert reader.index["molecule"].tolist() == [4]
        assert reader.index["n_atoms"].tolist() == [3]
        assert reader.header["format"] == FORMAT
        assert reader.header["format_version"] == 1
        assert "layout" not in reader.header

    def test_a_second_declaration_is_refused(self, tmp_path: Path) -> None:
        system, frames = _water_record(2)
        other = _frame(x=np.arange(3.0))
        other.meta = {"pe": 1}
        with MrecWriter(tmp_path / "c.mrec.h5", backend=Hdf5, units={}) as out:
            out.write_record(frames, system=system)
            with pytest.raises(ValueError, match="one declaration"):
                out.write_record([other], system=system)

    def test_nothing_is_at_the_path_until_close(self, tmp_path: Path) -> None:
        path = tmp_path / "c.mrec.h5"
        system, frames = _water_record(1)
        out = MrecWriter(path, backend=Hdf5, units={})
        out.write_record(frames, system=system)
        assert not path.exists()
        out.close()
        assert path.is_file() and sorted(p.name for p in tmp_path.iterdir()) == [path.name]

    def test_a_second_record_reads_back(self, tmp_path: Path) -> None:
        path = tmp_path / "c.mrec.h5"
        system, frames = _water_record(2)
        with MrecWriter(path, backend=Hdf5, units={"length": "angstrom"}) as out:
            out.write_record(frames, system=system, steps=[0, 4], index={"molecule": 1})
        record = MrecRecords(Hdf5(path)).read_record(0)
        assert len(record) == 2
        assert record[1].meta["pe"] == -2.0
        assert record[1].meta["step"] == 4


class TestMrecHdf5Records:
    def test_it_pickles_and_reopens_in_a_worker(self, tmp_path: Path) -> None:
        path = tmp_path / "c.mrec.h5"
        system, frames = _water_record(2)
        with MrecWriter(path, backend=Hdf5, units={}) as out:
            out.write_record(frames, system=system)
        reader = MrecRecords(Hdf5(path))
        with mp.get_context("spawn").Pool(1) as pool:
            assert pool.apply(len, (reader,)) == 1

    def test_an_uncommitted_file_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "c.mrec.h5"
        with h5py.File(path, "w") as handle:
            handle.create_dataset("frame_bytes", data=np.zeros(4, dtype=np.uint8))
        with pytest.raises(ValueError, match="not a committed collection"):
            MrecRecords(Hdf5(path))
