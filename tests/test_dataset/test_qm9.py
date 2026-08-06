"""Tests for the QM9 source — parsing, caching, and download guards.

Every test here is offline: network helpers are exercised through fakes so the
suite never touches Figshare.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from molpy import Frame

from molhub.dataset import Targets
from molhub.dataset.qm9 import (
    QM9Source,
    _filter_targets,
    _is_cached,
    _load_exclusion_list,
    _parse_xyz,
)

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
        assert set(Targets(frame).read()) == set(QM9Source.ALL_TARGETS)

    def test_tag_and_index_are_not_targets(self):
        frame = _parse_xyz(_SAMPLE_XYZ)
        assert "tag" not in Targets(frame).read()
        assert "index" not in Targets(frame).read()

    def test_target_values(self):
        meta = Targets(_parse_xyz(_SAMPLE_XYZ)).read()
        assert meta["A"] == pytest.approx(157.7118)
        assert meta["U0"] == pytest.approx(-40.47893)
        assert meta["Cv"] == pytest.approx(6.469)

    def test_star_caret_exponent_is_rewritten(self):
        meta = Targets(_parse_xyz(_STARCARET_XYZ)).read()
        assert meta["A"] == pytest.approx(1e-3)


class TestFilterTargets:
    def test_keeps_only_requested(self):
        frame = _parse_xyz(_SAMPLE_XYZ)
        _filter_targets(frame, frozenset({"U0", "gap"}))
        assert set(Targets(frame).read()) == {"U0", "gap"}

    def test_kept_values_survive(self):
        frame = _parse_xyz(_SAMPLE_XYZ)
        _filter_targets(frame, frozenset({"U0"}))
        assert Targets(frame).read()["U0"] == pytest.approx(-40.47893)

    def test_empty_keep_set_drops_everything(self):
        frame = _parse_xyz(_SAMPLE_XYZ)
        _filter_targets(frame, frozenset())
        assert Targets(frame).read() == {}

    def test_atoms_block_untouched(self):
        frame = _parse_xyz(_SAMPLE_XYZ)
        _filter_targets(frame, frozenset({"U0"}))
        assert list(frame["atoms"]["number"]) == [6, 1, 1, 1, 1]


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


class TestQM9SourceConstruction:
    def test_offline_missing_tarball_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="tarball not found"):
            QM9Source(tmp_path, download=False)

    def test_offline_zero_byte_tarball_is_rejected(self, tmp_path):
        (tmp_path / "qm9.tar.bz2").write_bytes(b"")
        with pytest.raises(FileNotFoundError, match="tarball not found"):
            QM9Source(tmp_path, download=False)

    def test_offline_missing_exclusion_list_raises(self, tmp_path):
        (tmp_path / "qm9.tar.bz2").write_bytes(b"not really a tarball")
        with pytest.raises(FileNotFoundError, match="exclusion list"):
            QM9Source(tmp_path, download=False)

    def test_unknown_target_raises(self, tmp_path):
        (tmp_path / "qm9.tar.bz2").write_bytes(b"x")
        (tmp_path / "qm9_exclude.txt").write_bytes(b"x")
        with pytest.raises(ValueError, match="Unknown QM9 targets"):
            QM9Source(tmp_path, targets=["U0", "not_a_property"], download=False)

    def test_source_id_is_stable_and_descriptive(self, tmp_path):
        (tmp_path / "qm9.tar.bz2").write_bytes(b"x")
        (tmp_path / "qm9_exclude.txt").write_bytes(b"x")
        src = QM9Source(tmp_path, total=100, targets=["U0", "gap"], download=False)
        assert src.source_id == "qm9:v2:total=100:targets=U0+gap"

    def test_source_id_without_options(self, tmp_path):
        (tmp_path / "qm9.tar.bz2").write_bytes(b"x")
        (tmp_path / "qm9_exclude.txt").write_bytes(b"x")
        assert QM9Source(tmp_path, download=False).source_id == "qm9:v2"

    def test_root_is_expanded_to_absolute(self, tmp_path):
        (tmp_path / "qm9.tar.bz2").write_bytes(b"x")
        (tmp_path / "qm9_exclude.txt").write_bytes(b"x")
        src = QM9Source(tmp_path, download=False)
        assert src.root.is_absolute()
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


class TestQM9EndToEnd:
    """Exercises the full index -> filter -> parse pipeline from a real tarball."""

    def test_loads_every_molecule(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1, 2, 3, 4])
        assert len(QM9Source(tmp_path, download=False)) == 4

    def test_excluded_molecules_are_dropped(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1, 2, 3, 4], excluded=[2, 4])
        src = QM9Source(tmp_path, download=False)
        assert len(src) == 2
        assert sorted(Targets(src[i]).read()["U0"] for i in range(len(src))) == [-3.0, -1.0]

    def test_empty_exclusion_list_keeps_everything(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1, 2, 3], excluded=[])
        assert len(QM9Source(tmp_path, download=False)) == 3

    def test_non_xyz_members_are_skipped(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1, 2])
        assert len(QM9Source(tmp_path, download=False)) == 2

    def test_getitem_returns_a_frame_with_atoms(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1])
        frame = QM9Source(tmp_path, download=False)[0]
        assert isinstance(frame, Frame)
        assert list(frame["atoms"]["element"]) == ["C"]

    def test_total_subsamples_reproducibly(self, tmp_path):
        _build_qm9_root(tmp_path, indices=list(range(1, 21)))

        def _sample() -> list[float]:
            src = QM9Source(tmp_path, total=5, download=False)
            return [Targets(src[i]).read()["U0"] for i in range(len(src))]

        first, second = _sample(), _sample()
        assert len(first) == 5
        assert first == second

    def test_total_larger_than_corpus_is_a_no_op(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1, 2])
        assert len(QM9Source(tmp_path, total=999, download=False)) == 2

    def test_targets_filter_applies_to_every_sample(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1, 2])
        src = QM9Source(tmp_path, targets=["U0"], download=False)
        for i in range(len(src)):
            assert set(Targets(src[i]).read()) == {"U0"}

    def test_is_map_dataset(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1])
        from molhub.dataset import MapDataset

        assert isinstance(QM9Source(tmp_path, download=False), MapDataset)

    def test_index_out_of_range(self, tmp_path):
        _build_qm9_root(tmp_path, indices=[1])
        with pytest.raises(IndexError):
            QM9Source(tmp_path, download=False)[5]


class TestQM9TargetSchema:
    def test_all_targets_are_graph_level(self):
        assert QM9Source.TARGET_SCHEMA.graph_level == QM9Source.ALL_TARGETS

    def test_no_atom_level_targets(self):
        assert QM9Source.TARGET_SCHEMA.atom_level == frozenset()
