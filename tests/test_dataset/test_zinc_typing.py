"""Offline tests for ZincTypingDataset — synthetic fixture + FakeHub only."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

import molhub
from molhub.coordinate import Coordinate
from molhub.dataset import ArtifactHub, MapDataset, Targets, ZincTypingDataset
from molhub.dataset.molecular import MOLECULE_ID
from molhub.dataset.zinc_typing import COORDINATE
from molhub.manifest import Manifest

_MANIFEST_BUNDLED = (
    Path(molhub.__file__).parent / "registry_data" / Coordinate.parse(COORDINATE).relative_path()
)
# tests/test_dataset/ → parents[2] is the molhub repo root.
_MANIFEST_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / ".."
    / "molhub-registry"
    / "artifacts"
    / Coordinate.parse(COORDINATE).relative_path()
).resolve()


def _write_molecule(
    mols_dir: Path,
    molecule_id: str,
    *,
    numbers: list[int],
    atom_types: list[str],
    bonds: list[tuple[int, int]],
    elements: list[str] | None = None,
) -> None:
    d = mols_dir / molecule_id
    d.mkdir(parents=True, exist_ok=True)
    payload: dict[str, np.ndarray] = {
        "number": np.array(numbers, dtype=np.int64),
        "atom_type": np.array(atom_types, dtype="U16"),
    }
    if elements is not None:
        payload["element"] = np.array(elements, dtype="U3")
    np.savez(d / "atoms.npz", **payload)
    atomi = np.array([a for a, _ in bonds], dtype=np.int64)
    atomj = np.array([b for _, b in bonds], dtype=np.int64)
    np.savez(d / "bonds.npz", atomi=atomi, atomj=atomj)


def write_fixture(root: Path) -> Path:
    """Author a tiny 5-molecule offline zinc-typing tree (3/1/1 split)."""
    mols = root / "mols"
    # train: m00, m01, m02  val: m03  test: m04
    specs = {
        "m00": ([6, 1], ["c3", "hc"], [(0, 1)], ["C", "H"]),
        "m01": ([8, 1], ["oh", "ho"], [(0, 1)], ["O", "H"]),
        "m02": ([6, 6, 1], ["c3", "c3", "hc"], [(0, 1), (1, 2)], ["C", "C", "H"]),
        "m03": ([7, 1], ["n3", "hn"], [(0, 1)], ["N", "H"]),
        "m04": ([6, 8], ["c3", "oh"], [(0, 1)], ["C", "O"]),
    }
    for mid, (nums, types, bonds, elems) in specs.items():
        _write_molecule(mols, mid, numbers=nums, atom_types=types, bonds=bonds, elements=elems)
    splits = {
        "train": ["m00", "m01", "m02"],
        "val": ["m03"],
        "test": ["m04"],
    }
    (root / "splits.json").write_text(json.dumps(splits))
    return root


@dataclass
class FakeHub:
    paths: dict[str, Path] = field(default_factory=dict)
    calls: list[tuple[str, list[str] | None]] = field(default_factory=list)

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        self.calls.append((coordinate, roles))
        wanted = list(self.paths) if roles is None else roles
        return {role: self.paths[role] for role in wanted}


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    return write_fixture(tmp_path / "zinc")


class TestZincTypingManifest:
    def test_bundled_manifest_loads(self):
        m = Manifest.from_path(_MANIFEST_BUNDLED)
        assert m is not None

    def test_registry_manifest_loads(self):
        assert _MANIFEST_REGISTRY.is_file(), _MANIFEST_REGISTRY
        m = Manifest.from_path(_MANIFEST_REGISTRY)
        assert m is not None

    def test_dual_write_content_identical(self):
        a = _MANIFEST_BUNDLED.read_text()
        b = _MANIFEST_REGISTRY.read_text()
        assert a == b

    def test_manifest_identity_fields(self):
        text = _MANIFEST_BUNDLED.read_text()
        assert "namespace: espaloma" in text
        assert "name: zinc-typing" in text
        assert 'version: "1"' in text or "version: 1" in text
        assert "digest:" in text
        assert "locators:" in text


class TestZincTypingDataset:
    def test_coordinate_constant(self):
        assert COORDINATE == "dataset:espaloma/zinc-typing@1"
        assert ZincTypingDataset.COORDINATE == COORDINATE

    def test_no_url_literals_in_adapter(self):
        src = Path(molhub.__file__).parent / "dataset" / "zinc_typing.py"
        text = src.read_text()
        assert re.search(r"https?://|figshare://|zenodo://|hf://", text) is None

    def test_offline_len_and_source_id(self, fixture_root: Path):
        ds = ZincTypingDataset(fixture_root, split="train", download=False)
        assert len(ds) == 3
        assert ds.source_id == f"{COORDINATE}#split=train"
        assert isinstance(ds, MapDataset)

    def test_target_schema(self):
        assert ZincTypingDataset.TARGET_SCHEMA.atom_level == frozenset({"atom_type"})
        assert ZincTypingDataset.TARGET_SCHEMA.graph_level == frozenset()
        assert ZincTypingDataset.TARGET_SCHEMA.chemical_perception == frozenset({"atom_type"})

    def test_frame_contract(self, fixture_root: Path):
        ds = ZincTypingDataset(fixture_root, split="train", download=False)
        frame = ds[0]
        assert Targets(frame)[MOLECULE_ID] == "m00"
        atoms = frame["atoms"]
        n = len(atoms["number"])
        assert len(atoms["element"]) == n
        assert len(atoms["atom_type"]) == n
        assert list(atoms["atom_type"]) == ["c3", "hc"]
        assert list(atoms["element"]) == ["C", "H"]
        bonds = frame["bonds"]
        assert list(bonds["atomi"]) == [0]
        assert list(bonds["atomj"]) == [1]

    def test_source_order_preserved(self, fixture_root: Path):
        ds = ZincTypingDataset(fixture_root, split="train", download=False)
        assert ds.molecule_ids == ["m00", "m01", "m02"]
        assert [Targets(ds[i])[MOLECULE_ID] for i in range(len(ds))] == [
            "m00",
            "m01",
            "m02",
        ]

    def test_splits_disjoint(self, fixture_root: Path):
        train = ZincTypingDataset(fixture_root, split="train", download=False)
        val = ZincTypingDataset(fixture_root, split="val", download=False)
        test = ZincTypingDataset(fixture_root, split="test", download=False)
        s_train, s_val, s_test = (
            set(train.molecule_ids),
            set(val.molecule_ids),
            set(test.molecule_ids),
        )
        assert s_train.isdisjoint(s_val)
        assert s_train.isdisjoint(s_test)
        assert s_val.isdisjoint(s_test)
        assert s_train | s_val | s_test == {"m00", "m01", "m02", "m03", "m04"}
        assert train.source_id.endswith("#split=train")
        assert val.source_id.endswith("#split=val")
        assert test.source_id.endswith("#split=test")

    def test_download_uses_coordinate(self, tmp_path: Path):
        served = write_fixture(tmp_path / "served")
        hub = FakeHub(paths={"main": served})
        ds = ZincTypingDataset(tmp_path / "empty", split="val", download=True, hub=hub)
        assert hub.calls == [(COORDINATE, ["main"])]
        assert len(ds) == 1
        assert Targets(ds[0])[MOLECULE_ID] == "m03"

    def test_unknown_split_raises(self, fixture_root: Path):
        with pytest.raises(ValueError, match="split"):
            ZincTypingDataset(fixture_root, split="dev", download=False)

    def test_fake_hub_is_artifact_hub(self):
        assert isinstance(FakeHub({}), ArtifactHub)

    def test_export(self):
        from molhub.dataset import ZincTypingDataset as Z
        from molhub.dataset import __all__ as all_names

        assert Z is ZincTypingDataset
        assert "ZincTypingDataset" in all_names
