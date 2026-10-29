"""mrec collections on LMDB — synthetic files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from molhub.io.lmdb import Lmdb
from molhub.io.mrec import FORMAT, MOLREC_LAYOUT, MrecRecords, MrecWriter


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


class TestMrecWriter:
    def test_frames_hold_only_state_and_read_back_whole(self, tmp_path: Path) -> None:
        path = tmp_path / "c.mrec.lmdb"
        system, frames = _water_record(3)
        with MrecWriter(path, backend=Lmdb, units={"length": "angstrom"}) as out:
            out.write_record(frames, system=system, steps=[0, 5, 9], index={"molecule": 4})
        reader = MrecRecords(Lmdb(path))
        record = reader.read_record(0)
        assert len(record) == 3
        assert sorted(record[2]["atoms"].keys()) == ["atomic_number", "element", "fx", "x"]
        assert record[2].meta == {"molecule_id": "water", "total_charge": 0, "pe": -3.0, "step": 9}
        assert "bonds" in record[1].keys()
        assert reader.index["molecule"].tolist() == [4]
        assert reader.index["n_atoms"].tolist() == [3]
        assert reader.header["format"] == FORMAT
        assert reader.header["layout"] == MOLREC_LAYOUT

    def test_a_second_declaration_is_refused(self, tmp_path: Path) -> None:
        system, frames = _water_record(2)
        other = _frame(x=np.arange(3.0))
        other.meta = {"pe": 1}
        with MrecWriter(tmp_path / "c.mrec.lmdb", backend=Lmdb, units={}) as out:
            out.write_record(frames, system=system)
            with pytest.raises(ValueError, match="one declaration"):
                out.write_record([other], system=system)

    def test_nothing_is_at_the_path_until_close(self, tmp_path: Path) -> None:
        path = tmp_path / "c.mrec.lmdb"
        system, frames = _water_record(1)
        out = MrecWriter(path, backend=Lmdb, units={})
        out.write_record(frames, system=system)
        assert not path.exists()
        out.close()
        assert path.is_file() and sorted(p.name for p in tmp_path.iterdir()) == [path.name]

    def test_molrecs_official_codec_reads_what_molhub_wrote(self, tmp_path: Path) -> None:
        """The spec's arbiter, not molhub's own reader, judges the file."""
        import molrec.core.bindings.lmdb as molrec_lmdb

        path = tmp_path / "c.mrec.lmdb"
        system, frames = _water_record(3)
        with MrecWriter(path, backend=Lmdb, units={"length": "angstrom"}) as out:
            out.write_record(frames, system=system)
        collection = molrec_lmdb.LmdbCollectionCodec().read(molrec_lmdb.LmdbCollectionStorage(path))
        trajectory = collection.records[0].trajectory
        assert collection.meta.units == {"length": "angstrom"}
        assert trajectory.step == [0, 1, 2]
        assert [f.meta["pe"] for f in trajectory.frames] == [-1.0, -2.0, -3.0]
        assert collection.records[0].system.blocks["bonds"].count == 2


class TestMrecRecords:
    def test_it_pickles_and_reopens_in_a_worker(self, tmp_path: Path) -> None:
        import multiprocessing as mp

        path = tmp_path / "c.mrec.lmdb"
        system, frames = _water_record(2)
        with MrecWriter(path, backend=Lmdb, units={}) as out:
            out.write_record(frames, system=system)
        reader = MrecRecords(Lmdb(path))
        with mp.get_context("spawn").Pool(1) as pool:
            assert pool.apply(len, (reader,)) == 1

    def test_an_uncommitted_file_is_refused(self, tmp_path: Path) -> None:
        import lmdb

        path = tmp_path / "c.mrec.lmdb"
        system, frames = _water_record(1)
        with MrecWriter(path, backend=Lmdb, units={}) as out:
            out.write_record(frames, system=system)
        env = lmdb.open(str(path), subdir=False)
        with env.begin(write=True) as txn:
            txn.delete(b"meta")
        env.close()
        with pytest.raises(ValueError, match="not a committed collection"):
            MrecRecords(Lmdb(path))


def test_io_does_not_import_dataset_or_cache() -> None:
    import ast
    from pathlib import Path as FsPath

    root = FsPath(__file__).parents[2] / "src" / "molhub" / "io"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("molhub.dataset")
                assert not node.module.startswith("molhub.cache")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("molhub.dataset")
                    assert not alias.name.startswith("molhub.cache")
