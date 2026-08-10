"""Offline tests for PhalkethohMMDataset — synthetic 2 mol × 2 conf fixture."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

import molhub
from molhub.coordinate import Coordinate
from molhub.dataset import ArtifactHub, MapDataset, PhalkethohMMDataset, Targets
from molhub.dataset.molecular import CONFORMER_ID, MOLECULE_ID
from molhub.dataset.phalkethoh_mm import COORDINATE
from molhub.manifest import Manifest

_MANIFEST_BUNDLED = (
    Path(molhub.__file__).parent / "registry_data" / Coordinate.parse(COORDINATE).relative_path()
)
_MANIFEST_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / ".."
    / "molhub-registry"
    / "artifacts"
    / Coordinate.parse(COORDINATE).relative_path()
).resolve()


def write_fixture(root: Path, *, with_forces: bool = True) -> Path:
    """2 molecules × 2 conformers with hard-coded mm_energy and Å coords."""
    mols = root / "mols"
    # molA: C-H, energies -1.0, -1.5
    # molB: O-H, energies -2.0, -2.5
    configs = {
        "molA": {
            "number": [6, 1],
            "element": ["C", "H"],
            "bonds": ([0], [1]),
            "coords": np.array(
                [
                    [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
                    [[0.0, 0.0, 0.0], [1.1, 0.0, 0.0]],
                ],
                dtype=np.float64,
            ),
            "mm_energy": np.array([-1.0, -1.5], dtype=np.float64),
            "forces": np.array(
                [
                    [[0.1, 0.0, 0.0], [-0.1, 0.0, 0.0]],
                    [[0.2, 0.0, 0.0], [-0.2, 0.0, 0.0]],
                ],
                dtype=np.float64,
            ),
        },
        "molB": {
            "number": [8, 1],
            "element": ["O", "H"],
            "bonds": ([0], [1]),
            "coords": np.array(
                [
                    [[0.0, 0.0, 0.0], [0.96, 0.0, 0.0]],
                    [[0.0, 0.0, 0.0], [0.97, 0.0, 0.0]],
                ],
                dtype=np.float64,
            ),
            "mm_energy": np.array([-2.0, -2.5], dtype=np.float64),
            "forces": np.array(
                [
                    [[0.0, 0.1, 0.0], [0.0, -0.1, 0.0]],
                    [[0.0, 0.2, 0.0], [0.0, -0.2, 0.0]],
                ],
                dtype=np.float64,
            ),
        },
    }
    for mid, cfg in configs.items():
        d = mols / mid
        d.mkdir(parents=True, exist_ok=True)
        np.savez(
            d / "atoms.npz",
            number=np.array(cfg["number"], dtype=np.int64),
            element=np.array(cfg["element"], dtype="U3"),
            atomi=np.array(cfg["bonds"][0], dtype=np.int64),
            atomj=np.array(cfg["bonds"][1], dtype=np.int64),
        )
        conf_payload = {
            "coords": cfg["coords"],
            "mm_energy": cfg["mm_energy"],
        }
        if with_forces:
            conf_payload["forces"] = cfg["forces"]
        np.savez(d / "confs.npz", **conf_payload)
        (d / "legacy_params.json").write_text(json.dumps({"bond_k": 300.0}))
    (root / "splits.json").write_text(json.dumps({"train": ["molA"], "val": ["molB"], "test": []}))
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
    return write_fixture(tmp_path / "pha")


class TestPhalkethohManifest:
    def test_dual_write(self):
        assert _MANIFEST_BUNDLED.is_file()
        assert _MANIFEST_REGISTRY.is_file()
        assert _MANIFEST_BUNDLED.read_text() == _MANIFEST_REGISTRY.read_text()
        Manifest.from_path(_MANIFEST_BUNDLED)
        text = _MANIFEST_BUNDLED.read_text()
        assert "namespace: espaloma" in text
        assert "name: phalkethoh-mm-small" in text
        assert "mm_energy" in text
        assert "digest:" in text
        assert "locators:" in text


class TestPhalkethohMMDataset:
    def test_coordinate_and_schema(self):
        assert COORDINATE == "dataset:espaloma/phalkethoh-mm-small@1"
        assert PhalkethohMMDataset.TARGET_SCHEMA.graph_level == frozenset({"mm_energy"})
        assert PhalkethohMMDataset.TARGET_SCHEMA.atom_level == frozenset({"forces"})

    def test_no_url_literals(self):
        src = Path(molhub.__file__).parent / "dataset" / "phalkethoh_mm.py"
        assert re.search(r"https?://|figshare://|zenodo://|hf://", src.read_text()) is None

    def test_full_dataset(self, fixture_root: Path):
        ds = PhalkethohMMDataset(fixture_root, download=False, split=None)
        assert len(ds) == 4  # 2 mol × 2 conf
        assert ds.source_id == COORDINATE
        assert isinstance(ds, MapDataset)

    def test_frame_contract(self, fixture_root: Path):
        ds = PhalkethohMMDataset(fixture_root, download=False, split="train")
        assert len(ds) == 2
        assert ds.source_id == f"{COORDINATE}#split=train"
        f0, f1 = ds[0], ds[1]
        assert Targets(f0)[MOLECULE_ID] == "molA"
        assert Targets(f1)[MOLECULE_ID] == "molA"
        assert Targets(f0)["mm_energy"] == pytest.approx(-1.0)
        assert Targets(f1)["mm_energy"] == pytest.approx(-1.5)
        assert Targets(f0)["conf_index"] == 0
        assert Targets(f1)[CONFORMER_ID] == "1"
        # Å coords hard-coded
        assert float(f0["atoms"]["x"][1]) == pytest.approx(1.0)
        assert float(f1["atoms"]["x"][1]) == pytest.approx(1.1)
        # forces present
        assert float(f0["atoms"]["fx"][0]) == pytest.approx(0.1)
        # bonds
        assert list(f0["bonds"]["atomi"]) == [0]
        assert list(f0["bonds"]["atomj"]) == [1]
        assert "legacy_params_json" in Targets(f0)

    def test_split_keeps_all_confs(self, fixture_root: Path):
        val = PhalkethohMMDataset(fixture_root, download=False, split="val")
        assert len(val) == 2
        ids = {Targets(val[i])[MOLECULE_ID] for i in range(len(val))}
        assert ids == {"molB"}
        energies = [Targets(val[i])["mm_energy"] for i in range(len(val))]
        assert energies == pytest.approx([-2.0, -2.5])

    def test_download_zip_via_hub(self, tmp_path: Path):
        tree = write_fixture(tmp_path / "tree")
        zpath = tmp_path / "main.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            for p in tree.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(tree).as_posix())
        hub = FakeHub(paths={"main": zpath})
        ds = PhalkethohMMDataset(tmp_path / "cache", download=True, hub=hub, split="train")
        assert hub.calls == [(COORDINATE, ["main"])]
        assert len(ds) == 2

    def test_export(self):
        from molhub.dataset import PhalkethohMMDataset as P
        from molhub.dataset import __all__ as names

        assert P is PhalkethohMMDataset
        assert "PhalkethohMMDataset" in names

    def test_fake_hub_protocol(self):
        assert isinstance(FakeHub({}), ArtifactHub)
