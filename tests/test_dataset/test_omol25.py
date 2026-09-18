"""OMol25 packed reader and small-molecule filter — synthetic NPZ, no network."""

from __future__ import annotations

import base64
import gzip
import hashlib
import importlib.util
import inspect
import sys
import types
from pathlib import Path

# molhub.dataset.__init__ imports MolRecDataset; this venv's molpy 0.14
# does not ship molpy.io.mrec. Stub only so this module can collect.
if importlib.util.find_spec("molpy.io.mrec") is None:
    import molpy.io as _molpy_io

    _mrec_stub = types.ModuleType("molpy.io.mrec")
    sys.modules["molpy.io.mrec"] = _mrec_stub
    _molpy_io.mrec = _mrec_stub

import numpy as np
import pytest

from molhub.cache import CountSidecar
from molhub.dataset.omol25 import (
    COORDINATE,
    MANIFEST,
    SMALL_COORDINATE,
    OMol25,
    OMol25Dataset,
    OMol25Lmdb,
    OMol25Small,
    OMol25SmallFilter,
    infer_bonds,
    write_packed,
)
from molhub.dataset.protocol import assignment
from tests.test_dataset.conftest import FakeHub, rows_of

# sha256sum of configs/allscaip/element_refs/uma_v1_hof_lin_refs.yaml at FAIR
# commit 41d36dc6bf8ced6348dc73e6aaf54d0527ebd8c9, 2026-09-11.
_ELEM_REFS_SHA256 = "e89e1abbcc000a810eb4aed62540389712e0c335bb960c85ff985920cd42f640"
_ELEM_REFS_YAML_GZ_B64 = (
    "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"
)
_FAIR_COMMIT = "41d36dc6bf8ced6348dc73e6aaf54d0527ebd8c9"
_VAL_TARBALL_URL = "https://dl.fbaipublicfiles.com/opencatalystproject/data/omol/250514/val.tar.gz"
_TARBALL_ROLES = ("4m", "val", "val-neutral")
_ASSIGNMENT_NAMES = (
    "val_metal_complexes",
    "val_electrolytes",
    "val_biomolecules",
    "val_spice",
    "val_neutralorganics",
)
# Incompressible pad so an equal-row replacement changes the aselmdb file size.
_SHARD_NOISE = bytes(range(256)) * 40


def _elem_refs_yaml_bytes() -> bytes:
    return gzip.decompress(base64.b64decode(_ELEM_REFS_YAML_GZ_B64))


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


# ---------------------------------------------------------------------------
# Record and dataset builders
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Builders
#
# Each one says what the data *is*, so a test reads as a statement about rows
# rather than about a fixture's name.
# ---------------------------------------------------------------------------


def _meta_mapping(frame) -> dict[str, object]:
    """``frame.meta`` with molpy ``MetaValue`` wrappers unwrapped.

    The ``getattr`` default is the value itself; a constant default would
    silently substitute itself for every already-plain scalar.
    """
    return {key: getattr(value, "value", value) for key, value in (frame.meta or {}).items()}


def _molecule(n_atoms: int, *, energy: float = -76.4, data_id: str = "") -> dict:
    """One molecule of *n_atoms*, as a packed-style record.

    Sizes are what the count tests are about, so the builder takes a size and
    nothing pretends to be a real chemistry.
    """
    return {
        "Z": np.concatenate([[8], np.ones(n_atoms - 1, dtype=np.int64)])[:n_atoms].astype(np.int64),
        "pos": np.arange(n_atoms * 3, dtype=np.float64).reshape(n_atoms, 3) * 0.5,
        "energy": energy,
        "forces": np.zeros((n_atoms, 3), dtype=np.float64),
        "charge": 0,
        "spin": 1,
        "domain": data_id,
    }


def _as_lmdb_record(molecule: dict, *, data_id: str = "") -> dict:
    """A packed-style molecule in the published ASE-LMDB record schema.

    Top-level ``numbers`` / ``positions`` / ``energy`` / ``forces``, and the
    per-record extras under ``data`` — which is what the reader looks for.
    """
    return {
        "numbers": np.asarray(molecule["Z"], dtype=np.int64),
        "positions": np.asarray(molecule["pos"], dtype=np.float64),
        "energy": float(molecule["energy"]),
        "forces": np.asarray(molecule["forces"], dtype=np.float64),
        "data": {
            "charge": int(molecule["charge"]),
            "spin": int(molecule["spin"]),
            "data_id": data_id or molecule["domain"],
            "domain": molecule["domain"],
        },
    }


def _packed_dataset(tmp_path, sizes: list[int]) -> OMol25Dataset:
    """A packed dataset whose rows hold exactly *sizes* atoms."""
    path = write_packed(tmp_path / "omol.npz", [_molecule(n) for n in sizes])
    return OMol25Dataset(path)


def _lmdb_shard(tmp_path, records: list[dict]) -> Path:
    """Write *records* as one ASE-LMDB shard and return its directory."""
    from tests.test_io.conftest import write_aselmdb

    numbered = {i + 1: record for i, record in enumerate(records)}
    write_aselmdb(tmp_path / "data0000.aselmdb", numbered, nextid=len(records) + 1)
    return tmp_path


def _lmdb_dataset(tmp_path, sizes: list[int]) -> OMol25Lmdb:
    """An LMDB view whose rows hold exactly *sizes* atoms."""
    return OMol25Lmdb(_lmdb_shard(tmp_path, [_as_lmdb_record(_molecule(n)) for n in sizes]))


def _lmdb_dataset_of(tmp_path, data_ids: list[str], *, sizes: list[int] | None = None):
    """An LMDB view carrying *data_ids* in order — the assignment predicates read these."""
    sizes = sizes or [3] * len(data_ids)
    records = [
        _as_lmdb_record(_molecule(n, data_id=d), data_id=d)
        for n, d in zip(sizes, data_ids, strict=True)
    ]
    return OMol25Lmdb(_lmdb_shard(tmp_path, records))


def _opened(tmp_path, *, role: str, view: OMol25Lmdb, max_rows: int | None = None) -> OMol25:
    """An :class:`OMol25` of *role* already opened on a local view.

    The view is handed over rather than fetched: these tests are about what
    the dataset does with rows, and none of them may reach the network.
    """
    dataset = OMol25(role=role, max_rows=max_rows)
    dataset._view = view
    return dataset


_VAL_DATA_IDS = [
    "spice",
    "ani2x",
    "metal_complexes",
    "orbnet_denali",
    "elytes",
    "biomolecules",
    "geom_orca6",
    "trans1x",
    "rgd",
    "spice",
]
#: Row 9 carries five atoms so a count over the spice view reads ``[3, 5]``
#: rather than two equal numbers any bug would also produce.
_VAL_SIZES = [3, 3, 3, 3, 3, 3, 3, 3, 3, 5]


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


class TestOMol25Lmdb:
    def test_reads_directory_of_aselmdb_files(self, tmp_path):
        _lmdb_shard(tmp_path, [_as_lmdb_record(_molecule(3))])
        ds = OMol25Lmdb(tmp_path)
        frame = ds[0][0]
        assert len(ds) == 1
        assert frame.meta["energy"] == pytest.approx(-76.4)
        assert "fx" in frame["atoms"]
        assert COORDINATE in ds.source_id

    def test_record_returns_raw_row_without_frame(self, tmp_path):
        _lmdb_shard(tmp_path, [_as_lmdb_record(_molecule(3))])
        ds = OMol25Lmdb(tmp_path)
        record = ds.record(0)
        assert record["energy"] == pytest.approx(-76.4)
        assert np.asarray(record["numbers"]).tolist() == [8, 1, 1]
        assert record["id"] == 1

    def test_record_out_of_range_raises(self, tmp_path):
        _lmdb_shard(tmp_path, [_as_lmdb_record(_molecule(3))])
        with pytest.raises(IndexError):
            OMol25Lmdb(tmp_path).record(5)

    def test_pickled_view_reopens_tables_lazily(self, tmp_path):
        import pickle

        _lmdb_shard(tmp_path, [_as_lmdb_record(_molecule(3))])
        ds = OMol25Lmdb(tmp_path)
        payload = pickle.dumps(ds)
        ds.close()
        clone = pickle.loads(payload)
        assert clone[0][0].meta["energy"] == pytest.approx(-76.4)

    def test_close_then_read_reopens(self, tmp_path):
        _lmdb_shard(tmp_path, [_as_lmdb_record(_molecule(3))])
        ds = OMol25Lmdb(tmp_path)
        ds.close()
        assert ds.record(0)["energy"] == pytest.approx(-76.4)

    def test_adapter_schema_version_is_a_positive_int(self):
        assert isinstance(OMol25Lmdb.ADAPTER_SCHEMA_VERSION, int)
        assert OMol25Lmdb.ADAPTER_SCHEMA_VERSION >= 1

    def test_construction_rejects_revision(self, tmp_path):
        _lmdb_shard(tmp_path, [_as_lmdb_record(_molecule(3))])
        with pytest.raises(TypeError):
            OMol25Lmdb(tmp_path, revision="x")

    def test_water_frame_keeps_published_dft_total(self, tmp_path):
        _lmdb_shard(tmp_path, [_as_lmdb_record(_water())])
        frame = OMol25Lmdb(tmp_path)[0][0]
        meta = _meta_mapping(frame)
        assert meta["energy"] == -76.4
        atoms = frame["atoms"]
        assert np.allclose(np.asarray(atoms["fx"]), 0.0)
        assert np.allclose(np.asarray(atoms["fy"]), 0.0)
        assert np.allclose(np.asarray(atoms["fz"]), 0.0)
        assert float(atoms["x"][1]) == pytest.approx(0.96)
        assert "e0" not in meta
        assert "energy_residual" not in meta
        assert "n_atoms" not in meta


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

    def test_default_role_is_official_4m(self):
        assert OMol25().role == "4m"
        assert inspect.signature(OMol25.__init__).parameters["role"].default == "4m"

    def test_val_neutral_is_catalogued_but_not_the_default(self):
        assert "val-neutral" in MANIFEST.artifacts
        assert OMol25().role != "val-neutral"

    def test_manifest_catalogs_four_file_roles(self):
        assert set(MANIFEST.artifacts) == {"4m", "val", "val-neutral", "omol-elem-refs"}

    def test_manifest_val_is_the_official_tarball(self):
        artifact = MANIFEST.artifacts["val"]
        assert artifact.filename == "val.tar.gz"
        assert str(artifact.locators[0]) == _VAL_TARBALL_URL
        assert artifact.size == 21293980744

    def test_omol_elem_refs_digest_is_none_size_and_locator(self):
        artifact = MANIFEST.artifacts["omol-elem-refs"]
        assert artifact.filename == "uma_v1_hof_lin_refs.yaml"
        assert artifact.format == "yaml"
        assert artifact.digest is None
        assert artifact.size == 11549
        assert _FAIR_COMMIT in str(artifact.locators[0])

    def test_omol_elem_refs_as_role_raises(self):
        with pytest.raises(ValueError) as raised:
            OMol25(role="omol-elem-refs")
        message = str(raised.value)
        assert all(role in message for role in _TARBALL_ROLES), message
        assert all(name in message for name in _ASSIGNMENT_NAMES), message

    def test_assignment_name_as_role_raises(self):
        with pytest.raises(ValueError) as raised:
            OMol25(role="val_spice")
        message = str(raised.value)
        assert all(role in message for role in _TARBALL_ROLES), message
        assert all(name in message for name in _ASSIGNMENT_NAMES), message

    def test_unknown_role_lists_tarball_roles_and_assignment_names(self):
        with pytest.raises(ValueError) as raised:
            OMol25(role="not-a-role")
        message = str(raised.value)
        assert all(role in message for role in _TARBALL_ROLES), message
        assert all(name in message for name in _ASSIGNMENT_NAMES), message

    def test_assignment_after_val_load_uses_data_id_predicate(self, tmp_path):
        ds = _opened(
            tmp_path, role="val", view=_lmdb_dataset_of(tmp_path, _VAL_DATA_IDS, sizes=_VAL_SIZES)
        )
        views = assignment(ds)
        assert set(views) == set(_ASSIGNMENT_NAMES)
        assert views["val_spice"] == [0, 9]
        assert views["val_metal_complexes"] == [2]
        assert views["val_electrolytes"] == [4]
        assert views["val_biomolecules"] == [5]
        assert ds.record(0)["data"]["data_id"] == "spice"
        assert ds.record(9)["data"]["data_id"] == "spice"
        assert ds.record(4)["data"]["data_id"] == "elytes"

    def test_assignment_preserves_parent_order_for_neutralorganics(self, tmp_path):
        ds = _opened(
            tmp_path, role="val", view=_lmdb_dataset_of(tmp_path, _VAL_DATA_IDS, sizes=_VAL_SIZES)
        )
        views = assignment(ds)
        assert views["val_neutralorganics"] == [1, 3, 6, 7, 8]
        assert [ds.record(i)["data"]["data_id"] for i in views["val_neutralorganics"]] == [
            "ani2x",
            "orbnet_denali",
            "geom_orca6",
            "trans1x",
            "rgd",
        ]

    def test_assignment_on_4m_raises_type_error(self, tmp_path):
        ds = _opened(tmp_path, role="4m", view=_lmdb_dataset(tmp_path, [3]))
        with pytest.raises(TypeError):
            assignment(ds)

    def test_assignment_when_max_rows_is_set_raises_type_error(self, tmp_path):
        ds = _opened(
            tmp_path,
            role="val",
            view=_lmdb_dataset_of(tmp_path, _VAL_DATA_IDS, sizes=_VAL_SIZES),
            max_rows=4,
        )
        with pytest.raises(TypeError):
            assignment(ds)

    def test_elem_refs_fetch_returns_path_with_pinned_yaml_digest(self, tmp_path):
        yaml_path = tmp_path / "uma_v1_hof_lin_refs.yaml"
        yaml_path.write_bytes(_elem_refs_yaml_bytes())
        hub = FakeHub({"omol-elem-refs": yaml_path})
        fetched = hub.fetch(COORDINATE, roles=["omol-elem-refs"])["omol-elem-refs"]
        assert isinstance(fetched, Path)
        digest = hashlib.sha256(fetched.read_bytes()).hexdigest()
        assert digest == _ELEM_REFS_SHA256
        assert hub.calls == [(COORDINATE, ["omol-elem-refs"])]

    def test_loaded_val_water_has_no_residual_columns(self, tmp_path):
        ds = _opened(
            tmp_path,
            role="val",
            view=OMol25Lmdb(_lmdb_shard(tmp_path, [_as_lmdb_record(_water())])),
        )
        meta = _meta_mapping(ds[0][0])
        assert meta["energy"] == -76.4
        assert "e0" not in meta
        assert "energy_residual" not in meta


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


class TestOMol25SmallFilter:
    def test_reason_unwraps_meta_value_charge_and_spin(self) -> None:
        """molpy 0.14 wraps frame.meta as MetaValue; int(wrapper) raises."""

        class _Meta:
            def __init__(self, value: object) -> None:
                self.value = value

        class _Frame:
            meta = {"charge": _Meta(0), "spin": _Meta(1), "domain": _Meta("")}

            def __getitem__(self, name: str) -> dict[str, np.ndarray]:
                assert name == "atoms"
                return {"number": np.array([8, 1, 1], dtype=np.int64)}

        assert OMol25SmallFilter().reason(_Frame()) is None  # type: ignore[arg-type]

    def test_reason_still_drops_a_wrapped_charged_frame(self) -> None:
        class _Meta:
            def __init__(self, value: object) -> None:
                self.value = value

        class _Frame:
            meta = {"charge": _Meta(1), "spin": _Meta(1), "domain": _Meta("")}

            def __getitem__(self, name: str) -> dict[str, np.ndarray]:
                return {"number": np.array([8, 1, 1], dtype=np.int64)}

        assert OMol25SmallFilter().reason(_Frame()) == "charge"  # type: ignore[arg-type]


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


class TestNrows:
    """``nrows(table)`` — the per-row table lengths a packing budget reads.

    One contract; three containers meet it, at very different cost. The cost
    is :class:`TestNrowsCost`'s subject, not this one's — here the three must
    be indistinguishable.
    """

    SIZES = [3, 5, 2]

    @pytest.fixture(params=["packed", "lmdb", "wrapped"])
    def counted(self, request, tmp_path):
        if request.param == "packed":
            return _packed_dataset(tmp_path, self.SIZES)
        view = _lmdb_dataset(tmp_path, self.SIZES)
        if request.param == "lmdb":
            return view
        return _opened(tmp_path, role="4m", view=view)

    def test_answers_one_length_per_row(self, counted):
        assert rows_of(counted, "atoms").tolist() == self.SIZES

    def test_agrees_with_materialising_the_row(self, counted):
        # The vector is a shortcut past `__getitem__`, so the two must not be
        # allowed to drift: that is the whole reason a budget may trust it.
        counts = rows_of(counted, "atoms")
        for index in range(len(counted)):
            assert int(counted[index][0]["atoms"].nrows) == int(counts[index])

    def test_is_integral(self, counted):
        assert rows_of(counted, "atoms").dtype == np.dtype(np.int64)

    @pytest.mark.parametrize("table", ["bonds", "graphs", "n_atoms", "graph.natoms"])
    def test_counts_only_the_table_it_declares(self, counted, table):
        # An undeclared table is not an error — `nrows_of` falls back to
        # materialising each sample, which is correct and slow. What this
        # container owns is the *declaration*: it must not claim a table it
        # cannot answer cheaply, and a field spelling such as `graph.natoms`
        # is not a block name at all.
        declared = getattr(type(counted), "counted_tables", None) or {}
        assert table not in declared
        measure = getattr(counted, "count_rows", None)
        if measure is not None:
            with pytest.raises(ValueError):
                measure(table)


class TestNrowsCost:
    """What each container pays to answer — the reason a cache exists at all."""

    def test_packed_reads_a_column_and_caches_nothing(self, tmp_path, monkeypatch):
        # A packed NPZ holds the count outright. Decoding a record to
        # rediscover it, or writing a sidecar for it, would both be work
        # spent on a number already in hand.
        dataset = _packed_dataset(tmp_path, [3, 5])
        monkeypatch.setattr(
            CountSidecar,
            "save",
            lambda self, counts: pytest.fail("a column read must not write a sidecar"),
        )
        assert rows_of(dataset, "atoms").tolist() == [3, 5]

    def test_lmdb_measures_once_and_reuses_the_vector(self, tmp_path, monkeypatch):
        # This is the case the cache exists for: an ASE-LMDB has to decode a
        # record to learn its length, which over four million rows is a
        # quarter of an hour to rediscover a number that never changes.
        root = _lmdb_shard(tmp_path, [_as_lmdb_record(_molecule(n)) for n in (3, 5)])
        first = OMol25Lmdb(root).count_rows("atoms")
        monkeypatch.setattr(
            OMol25Lmdb,
            "record",
            lambda self, idx: pytest.fail("a cached vector must not re-decode"),
        )
        assert OMol25Lmdb(root).count_rows("atoms").tolist() == first.tolist()

    def test_lmdb_measures_again_once_the_shard_changes(self, tmp_path):
        # Staleness is not a case analysis. The file's own name, size and
        # modification time key the vector, so a rewritten shard keys
        # elsewhere and is simply measured.
        assert _lmdb_dataset(tmp_path, [3]).count_rows("atoms").tolist() == [3]
        assert _lmdb_dataset(tmp_path, [7]).count_rows("atoms").tolist() == [7]

    def test_lmdb_parallel_agrees_with_sequential(self, tmp_path):
        sequential = _lmdb_dataset(tmp_path, [3, 5, 2]).count_rows("atoms").tolist()
        other = tmp_path / "again"
        other.mkdir()
        assert _lmdb_dataset(other, [3, 5, 2]).count_rows("atoms", workers=2).tolist() == sequential
