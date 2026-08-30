"""Tests for the QM9 dataset — parsing, caching, and download guards.

Every test here is offline: network helpers are exercised through fakes so the
suite never touches Figshare.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from molpy import Frame, UnitsError, UnitSystem

from molhub.dataset import ArtifactHub, qm9
from molhub.dataset.qm9 import (
    COORDINATE,
    QM9,
    _is_cached,
    _load_exclusion_list,
    _parse_xyz,
)
from tests.test_dataset.conftest import FakeHub, dissolved_wrapper_names

# One real-shaped QM9 record: 5 atoms, tag + index + 15 scalar properties.
# The coordinate lines carry a trailing Mulliken charge column, which the
# parser ignores.
_SAMPLE_XYZ = """5
gdb 1 157.7118 157.70997 157.70699 0 13.21 -0.3877 0.1171 0.5048 35.3641 \
0.044749 -40.47893 -40.476062 -40.475117 -40.498597 6.469
C -0.0126981359 1.0858041578 0.0080009958 -0.535689
H 0.002150416 -0.0060313176 0.0019761204 0.133921
H 1.0117308433 1.4637511618 0.0002765748 0.133922
H -0.540815069 1.4475266138 -0.8766437152 0.133923
H -0.5238136345 1.4379326443 0.9063972942 0.133923
"""

# QM9 writes exponents as ``*^`` instead of ``E``; the parser rewrites them.
_STARCARET_XYZ = """1
gdb 2 1*^-3 2.0 3.0 0 1.0 -0.1 0.1 0.2 1.0 0.01 -1.0 -1.0 -1.0 -1.0 1.0
C 0.0 0.0 0.0 0.0
"""


class TestParseXyz:
    def test_atom_count_and_symbols(self):
        frame = _parse_xyz(_SAMPLE_XYZ)
        assert isinstance(frame, Frame)
        assert list(frame["atoms"]["element"]) == ["C", "H", "H", "H", "H"]

    def test_atomic_numbers(self):
        frame = _parse_xyz(_SAMPLE_XYZ)
        assert list(frame["atoms"]["number"]) == [6, 1, 1, 1, 1]

    def test_coordinates(self):
        frame = _parse_xyz(_SAMPLE_XYZ)
        assert frame["atoms"]["x"][0] == pytest.approx(-0.0126981359)
        assert frame["atoms"]["y"][0] == pytest.approx(1.0858041578)
        assert frame["atoms"]["z"][0] == pytest.approx(0.0080009958)

    def test_all_fifteen_targets_present(self):
        frame = _parse_xyz(_SAMPLE_XYZ)
        assert set(frame.meta) == set(QM9.ALL_TARGETS)

    def test_tag_and_index_are_not_targets(self):
        frame = _parse_xyz(_SAMPLE_XYZ)
        assert "tag" not in frame.meta
        assert "index" not in frame.meta

    def test_target_values(self):
        frame = _parse_xyz(_SAMPLE_XYZ)
        targets = frame.meta
        assert targets["A"] == pytest.approx(157.7118)
        assert targets["U0"] == pytest.approx(-40.47893)
        assert targets["Cv"] == pytest.approx(6.469)

    def test_star_caret_exponent_is_rewritten(self):
        assert _parse_xyz(_STARCARET_XYZ).meta["A"] == pytest.approx(1e-3)


class TestLoadExclusionList:
    def test_skips_nine_header_lines_and_trailer(self, tmp_path):
        p = tmp_path / "exclude.txt"
        header = "\n".join(f"header {i}" for i in range(9))
        body = "\n".join(f"{i} 0.0 0.0" for i in (21725, 87037, 59827))
        p.write_text(f"{header}\n{body}\ntrailer\n")
        assert _load_exclusion_list(p) == {21725, 87037, 59827}

    def test_empty_file_yields_empty_set(self, tmp_path):
        p = tmp_path / "exclude.txt"
        p.write_text("")
        assert _load_exclusion_list(p) == set()


class TestIsCached:
    def test_missing_file(self, tmp_path):
        assert _is_cached(tmp_path / "nope.bin") is False

    def test_zero_byte_file_counts_as_absent(self, tmp_path):
        """A 0-byte file is what an HTTP 202 used to leave behind."""
        p = tmp_path / "empty.bin"
        p.write_bytes(b"")
        assert p.exists()
        assert _is_cached(p) is False

    def test_non_empty_file(self, tmp_path):
        p = tmp_path / "ok.bin"
        p.write_bytes(b"x")
        assert _is_cached(p) is True


class TestQM9Construction:
    def test_construction_does_no_io(self, tmp_path):
        """Missing raw files must surface at load(), never at construction."""
        QM9(tmp_path, download=False)

    def test_offline_missing_tarball_raises_at_load(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="tarball not found"):
            QM9(tmp_path, download=False).load()

    def test_offline_zero_byte_tarball_is_rejected(self, tmp_path):
        (tmp_path / "qm9.tar.bz2").write_bytes(b"")
        with pytest.raises(FileNotFoundError, match="tarball not found"):
            QM9(tmp_path, download=False).load()

    def test_offline_missing_exclusion_list_raises(self, tmp_path):
        (tmp_path / "qm9.tar.bz2").write_bytes(b"not really a tarball")
        with pytest.raises(FileNotFoundError, match="exclusion list"):
            QM9(tmp_path, download=False).load()

    def test_indexing_before_load_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="load"):
            len(QM9(tmp_path, download=False))

    def test_source_id_is_the_coordinate(self, tmp_path):
        assert QM9(tmp_path, download=False).source_id == "dataset:molcrafts/qm9@v2"

    def test_source_id_parses_as_a_coordinate(self, tmp_path):
        from molhub.coordinate import Coordinate

        source_id = QM9(tmp_path, download=False).source_id
        assert Coordinate.parse(source_id).canonical == source_id

    def test_root_is_expanded(self, tmp_path):
        src = QM9(tmp_path, download=False)
        assert isinstance(src.root, Path)


def _xyz_record(index: int, u0: float) -> str:
    """One QM9 record whose ``U0`` encodes its index, for identification."""
    return (
        "1\n"
        f"gdb {index} 1.0 2.0 3.0 0 1.0 -0.1 0.1 0.2 1.0 0.01 "
        f"{u0} -1.0 -1.0 -1.0 1.0\n"
        "C 0.0 0.0 0.0 0.0\n"
    )


def _build_qm9_root(root: Path, indices: list[int], excluded: list[int] | None = None) -> None:
    """Write a miniature but structurally faithful QM9 cache into *root*.

    Member names follow the real ``dsgdb9nsd_%06d.xyz`` convention, because
    :func:`_load_raw` recovers the molecule index by slicing the filename.
    """
    import tarfile

    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(root / "qm9.tar.bz2", "w:bz2") as tar:
        for i in indices:
            payload = _xyz_record(i, u0=float(-i)).encode()
            info = tarfile.TarInfo(name=f"dsgdb9nsd_{i:06d}.xyz")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        # A non-.xyz member must be skipped rather than parsed.
        note = b"readme"
        info = tarfile.TarInfo(name="README.txt")
        info.size = len(note)
        tar.addfile(info, io.BytesIO(note))

    header = "\n".join(f"header {n}" for n in range(9))
    body = "\n".join(f"{n} 0.0" for n in (excluded or []))
    (root / "qm9_exclude.txt").write_text(f"{header}\n{body}\ntrailer\n")


class TestQM9Pipeline:
    """Exercises the full index -> filter -> parse pipeline from a real tarball."""

    def test_loads_every_molecule(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1, 2, 3, 4])
        assert len(QM9(tmp_path, download=False).load()) == 4

    def test_excluded_molecules_are_dropped(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1, 2, 3, 4], excluded=[2, 4])
        src = QM9(tmp_path, download=False).load()
        assert len(src) == 2
        assert sorted(src[i][0].meta["U0"] for i in range(len(src))) == [-3.0, -1.0]

    def test_empty_exclusion_list_keeps_everything(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1, 2, 3], excluded=[])
        assert len(QM9(tmp_path, download=False).load()) == 3

    def test_non_xyz_members_are_skipped(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1, 2])
        assert len(QM9(tmp_path, download=False).load()) == 2

    def test_frames_come_back_in_index_order(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[3, 1, 2])
        src = QM9(tmp_path, download=False).load()
        assert [src[i][0].meta["U0"] for i in range(len(src))] == [-1.0, -2.0, -3.0]

    def test_getitem_returns_a_frame_with_atoms(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1])
        frames = QM9(tmp_path, download=False).load()[0]
        assert len(frames) == 1
        assert isinstance(frames[0], Frame)
        assert list(frames[0]["atoms"]["element"]) == ["C"]

    def test_load_is_idempotent(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1])
        src = QM9(tmp_path, download=False).load()
        first = src[0][0]
        assert src.load()[0][0] is first

    def test_is_map_dataset(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1])
        from molhub.dataset import Dataset

        assert isinstance(QM9(tmp_path, download=False).load(), Dataset)

    def test_index_out_of_range(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1])
        with pytest.raises(IndexError):
            QM9(tmp_path, download=False).load()[5]


class TestQM9Download:
    """The ``download=True`` path, exercised through the dataset's one seam."""

    @pytest.fixture
    def hub(self, tmp_path) -> FakeHub:
        """A hub serving a miniature QM9 from outside *root*."""
        served = tmp_path / "served"
        _build_qm9_root(served, indices=[1, 2, 3])
        return FakeHub({"main": served / "qm9.tar.bz2", "exclude": served / "qm9_exclude.txt"})

    def test_the_fake_still_matches_the_seam_it_stands_in_for(self, hub):
        """A fake that drifts from the protocol proves nothing about the source."""
        assert isinstance(hub, ArtifactHub)

    def test_download_reads_what_the_hub_served(self, tmp_path, hub):
        assert len(QM9(tmp_path / "empty", download=True, hub=hub).load()) == 3

    def test_download_asks_for_the_pinned_coordinate(self, tmp_path, hub):
        QM9(tmp_path / "empty", download=True, hub=hub).load()[0]
        assert hub.calls == [(COORDINATE, None)]

    def test_construction_alone_fetches_nothing(self, tmp_path, hub):
        """load() is the IO boundary: constructing must not cost a download."""
        QM9(tmp_path / "empty", download=True, hub=hub)
        assert hub.calls == []

    def test_download_ignores_root(self, tmp_path, hub):
        """Fetched bytes land in the shared cache, not in *root*."""
        root = tmp_path / "empty"
        len(QM9(root, download=True, hub=hub).load())
        assert not root.exists()

    def test_offline_never_touches_the_hub(self, tmp_path, hub):
        _build_qm9_root(tmp_path, indices=[1])
        assert len(QM9(tmp_path, download=False, hub=hub).load()) == 1
        assert hub.calls == []


class TestQM9TargetSchema:
    def test_all_targets_are_graph_level(self):
        assert QM9.TARGET_SCHEMA.graph_level == QM9.ALL_TARGETS

    def test_no_atom_level_targets(self):
        assert QM9.TARGET_SCHEMA.atom_level == frozenset()


class TestQM9Units:
    """QM9 records native units verbatim and declares them on the manifest."""

    def test_every_target_declares_a_unit(self):
        assert set(QM9.manifest.units) == set(QM9.ALL_TARGETS)

    def test_energies_are_hartree_as_published(self):
        for key in ("homo", "lumo", "gap", "zpve", "U0", "U", "H", "G"):
            assert QM9.manifest.units[key] == "hartree"

    def test_rotational_constants_are_ghz(self):
        """Published in GHz (Ramakrishnan 2014, Table 3)."""
        for key in ("A", "B", "C"):
            assert QM9.manifest.units[key] == "GHz"

    def test_every_unit_parses_through_the_molpy_registry(self):
        """UnitConvert reads these strings back; a typo must fail here."""
        registry = UnitSystem()
        try:
            registry.Unit("GHz")
        except UnitsError:
            pytest.skip(
                "this molpy's unit registry predates GHz (added in 0.14; QM9 "
                "declares rotational constants in it) — drop this skip when "
                "the molcrafts-molpy pin reaches 0.14"
            )
        for unit in QM9.manifest.units.values():
            registry.Unit(unit)


class TestQM9MetaSurface:
    """QM9 writes targets through ``frame.meta`` directly."""

    def test_parsed_target_is_read_straight_off_frame_meta(self):
        assert float(_parse_xyz(_SAMPLE_XYZ).meta["U0"]) == pytest.approx(-40.47893, abs=1e-10)

    def test_module_namespace_holds_no_deleted_meta_wrapper(self):
        assert [name for name in ("Targets", "MetaCodec", "write_meta") if hasattr(qm9, name)] == []

    def test_module_source_names_no_deleted_meta_wrapper(self):
        assert dissolved_wrapper_names(qm9) == []
