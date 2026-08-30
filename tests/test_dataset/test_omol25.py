"""OMol25 packed reader and small-molecule filter — synthetic NPZ, no network."""

from __future__ import annotations

import numpy as np
import pytest

from molhub.dataset.omol25 import (
    COORDINATE,
    SMALL_COORDINATE,
    OMol25,
    OMol25Dataset,
    OMol25Lmdb,
    OMol25Small,
    infer_bonds,
    write_packed,
)


def _water(*, energy: float = -76.4, charge: int = 0, spin: int = 1, domain: str = "") -> dict:
    return {
        "Z": np.array([8, 1, 1], dtype=np.int64),
        "pos": np.array(
            [[0.0, 0.0, 0.0], [0.96, 0.0, 0.0], [-0.24, 0.93, 0.0]],
            dtype=np.float64,
        ),
        "energy": energy,
        "forces": np.zeros((3, 3), dtype=np.float64),
        "charge": charge,
        "spin": spin,
        "domain": domain,
    }


def _iron() -> dict:
    rec = _water()
    rec["Z"] = np.array([26, 6, 6], dtype=np.int64)
    rec["pos"] = np.array(
        [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0]],
        dtype=np.float64,
    )
    return rec


def _far_atoms() -> dict:
    rec = _water()
    rec["pos"] = np.array(
        [[0.0, 0.0, 0.0], [5.0, 0.0, 0.0], [0.0, 5.0, 0.0]],
        dtype=np.float64,
    )
    return rec


class TestOMol25Dataset:
    def test_reads_energy_and_forces(self, tmp_path):
        path = write_packed(tmp_path / "omol.npz", [_water(energy=-10.0)])
        ds = OMol25Dataset(path)
        frame = ds[0][0]
        assert len(ds) == 1
        assert frame.meta["energy"] == pytest.approx(-10.0)
        assert "fx" in frame["atoms"]
        assert int(frame.meta["charge"]) == 0
        assert int(frame.meta["spin"]) == 1
        assert COORDINATE in ds.source_id

    def test_missing_energy_key_raises(self, tmp_path):
        path = write_packed(tmp_path / "omol.npz", [_water()])
        data = dict(np.load(path))
        del data["energy"]
        broken = tmp_path / "broken.npz"
        np.savez(broken, **data)
        with pytest.raises(KeyError, match="energy"):
            OMol25Dataset(broken)

    def test_empty_file_raises(self, tmp_path):
        empty = tmp_path / "empty.npz"
        empty.write_bytes(b"")
        with pytest.raises(FileNotFoundError):
            OMol25Dataset(empty)


def _write_lmdb_dir(tmp_path, records: dict[int, dict]) -> None:
    from tests.test_io.conftest import write_aselmdb

    write_aselmdb(tmp_path / "data0000.aselmdb", records, nextid=max(records) + 1)


def _water_record() -> dict:
    water = _water()
    return {
        "numbers": water["Z"],
        "positions": water["pos"],
        "energy": water["energy"],
        "forces": water["forces"],
        "data": {
            "charge": water["charge"],
            "spin": water["spin"],
            "data_id": water["domain"],
        },
    }


class TestOMol25Lmdb:
    def test_reads_directory_of_aselmdb_files(self, tmp_path):
        _write_lmdb_dir(tmp_path, {1: _water_record()})
        ds = OMol25Lmdb(tmp_path)
        frame = ds[0][0]
        assert len(ds) == 1
        assert frame.meta["energy"] == pytest.approx(-76.4)
        assert "fx" in frame["atoms"]
        assert COORDINATE in ds.source_id

    def test_record_returns_raw_row_without_frame(self, tmp_path):
        _write_lmdb_dir(tmp_path, {1: _water_record()})
        ds = OMol25Lmdb(tmp_path)
        record = ds.record(0)
        assert record["energy"] == pytest.approx(-76.4)
        assert np.asarray(record["numbers"]).tolist() == [8, 1, 1]
        assert record["id"] == 1

    def test_record_out_of_range_raises(self, tmp_path):
        _write_lmdb_dir(tmp_path, {1: _water_record()})
        with pytest.raises(IndexError):
            OMol25Lmdb(tmp_path).record(5)

    def test_atom_counts_matches_rows(self, tmp_path):
        _write_lmdb_dir(tmp_path, {1: _water_record(), 2: _water_record()})
        counts = OMol25Lmdb(tmp_path).atom_counts()
        assert counts.tolist() == [3, 3]

    def test_atom_counts_is_cached_on_disk(self, tmp_path, monkeypatch):
        _write_lmdb_dir(tmp_path, {1: _water_record()})
        ds = OMol25Lmdb(tmp_path)
        first = ds.atom_counts()
        assert len(list(tmp_path.glob(".molhub-n-atoms-*.npy"))) == 1
        monkeypatch.setattr(
            OMol25Lmdb, "record", lambda self, idx: pytest.fail("cache miss re-decoded a record")
        )
        assert ds.atom_counts().tolist() == first.tolist()

    def test_pickled_view_reopens_tables_lazily(self, tmp_path):
        import pickle

        _write_lmdb_dir(tmp_path, {1: _water_record()})
        ds = OMol25Lmdb(tmp_path)
        payload = pickle.dumps(ds)
        ds.close()
        clone = pickle.loads(payload)
        assert clone[0][0].meta["energy"] == pytest.approx(-76.4)

    def test_close_then_read_reopens(self, tmp_path):
        _write_lmdb_dir(tmp_path, {1: _water_record()})
        ds = OMol25Lmdb(tmp_path)
        ds.close()
        assert ds.record(0)["energy"] == pytest.approx(-76.4)

    def test_atom_counts_parallel_matches_sequential(self, tmp_path):
        _write_lmdb_dir(tmp_path, {1: _water_record(), 2: _water_record()})
        ds = OMol25Lmdb(tmp_path)
        sequential = ds.atom_counts().tolist()
        for stale in tmp_path.glob(".molhub-n-atoms-*.npy"):
            stale.unlink()
        assert ds.atom_counts(workers=2).tolist() == sequential

    def test_max_rows_changes_the_cache_identity(self, tmp_path):
        """A capped smoke view and the full extract must never share a cache
        entry — max_rows changes the content, so it must change the id.

        The environments are opened sequentially: LMDB refuses to open the
        same file twice in one process.
        """
        _write_lmdb_dir(tmp_path, {1: _water_record(), 2: _water_record()})
        full = OMol25Lmdb(tmp_path)
        full_id = full.source_id
        full.close()
        capped = OMol25Lmdb(tmp_path, max_rows=1)
        assert full_id != capped.source_id
        assert "max_rows=1" in capped.source_id


class TestOMol25:
    def test_construction_does_no_io(self):
        OMol25(role="val-neutral")

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError, match="Unknown OMol25 role"):
            OMol25(role="not-a-role")

    def test_indexing_before_load_raises(self):
        with pytest.raises(RuntimeError, match="load"):
            len(OMol25(role="val-neutral"))

    def test_source_id_is_coordinate_side(self):
        """Role and row cap, never a local path."""
        ds = OMol25(role="val-neutral", max_rows=8)
        assert ds.source_id == f"{COORDINATE}#role=val-neutral,max_rows=8"

    def test_source_id_without_cap_names_only_the_role(self):
        assert OMol25(role="4m").source_id == f"{COORDINATE}#role=4m"


class TestInferBonds:
    def test_water_has_two_bonds(self):
        water = _water()
        atomi, atomj = infer_bonds(water["Z"], water["pos"])
        assert atomi.tolist() == [0, 0]
        assert atomj.tolist() == [1, 2]

    def test_far_atoms_have_no_bonds(self):
        rec = _far_atoms()
        atomi, atomj = infer_bonds(rec["Z"], rec["pos"])
        assert atomi.shape == (0,)
        assert atomj.shape == (0,)

    def test_bad_atomic_number_raises(self):
        with pytest.raises(ValueError, match="atomic numbers"):
            infer_bonds(np.array([0, 1]), np.zeros((2, 3)))


class TestOMol25Small:
    def test_construction_does_no_scan(self, tmp_path):
        path = write_packed(tmp_path / "omol.npz", [_water()])
        small = OMol25Small(OMol25Dataset(path))
        assert small.scanned == 0

    def test_indexing_before_load_raises(self, tmp_path):
        path = write_packed(tmp_path / "omol.npz", [_water()])
        with pytest.raises(RuntimeError, match="load"):
            len(OMol25Small(OMol25Dataset(path)))

    def test_keeps_neutral_organic_water(self, tmp_path):
        path = write_packed(tmp_path / "omol.npz", [_water()])
        small = OMol25Small(OMol25Dataset(path)).load()
        assert small.kept == 1
        assert small.scanned == 1
        frame = small[0][0]
        assert "bonds" in frame
        assert int(frame["bonds"]["atomi"].shape[0]) >= 2
        assert frame.meta["energy"] == pytest.approx(-76.4)
        assert frame.meta["molecule_id"]
        assert frame.meta["source_record_id"]
        assert SMALL_COORDINATE in small.source_id

    def test_drops_metal(self, tmp_path):
        path = write_packed(tmp_path / "omol.npz", [_water(), _iron()])
        small = OMol25Small(OMol25Dataset(path)).load()
        assert small.kept == 1
        assert small.drop_counts["element"] == 1

    def test_drops_open_shell(self, tmp_path):
        path = write_packed(tmp_path / "omol.npz", [_water(spin=3)])
        small = OMol25Small(OMol25Dataset(path)).load()
        assert small.kept == 0
        assert small.drop_counts["spin"] == 1

    def test_drops_biomolecule_domain(self, tmp_path):
        path = write_packed(tmp_path / "omol.npz", [_water(domain="biomolecule")])
        small = OMol25Small(OMol25Dataset(path)).load()
        assert small.kept == 0
        assert small.drop_counts["domain"] == 1

    def test_drops_disconnected(self, tmp_path):
        path = write_packed(tmp_path / "omol.npz", [_far_atoms()])
        small = OMol25Small(OMol25Dataset(path)).load()
        assert small.kept == 0
        assert small.drop_counts["bonds"] == 1

    def test_limit_stops_after_kept_frames(self, tmp_path):
        path = write_packed(tmp_path / "omol.npz", [_water(), _water(), _water()])
        small = OMol25Small(OMol25Dataset(path), limit=1).load()
        assert small.kept == 1
        assert small.scanned == 1

    def test_refuses_over_size(self, tmp_path):
        big = _water()
        n = 33
        big["Z"] = np.full(n, 6, dtype=np.int64)
        big["pos"] = np.arange(n * 3, dtype=np.float64).reshape(n, 3) * 0.1
        big["forces"] = np.zeros((n, 3), dtype=np.float64)
        path = write_packed(tmp_path / "omol.npz", [big])
        small = OMol25Small(OMol25Dataset(path)).load()
        assert small.kept == 0
        assert small.drop_counts["n_atoms"] == 1
