"""Offline tests for PhalkethohMMDataset — synthetic 2 mol × 2 conf fixture."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

import molhub
from molhub.dataset import ArtifactHub, Dataset, PhalkethohMMDataset
from molhub.dataset.phalkethoh_mm import COORDINATE, MANIFEST
from tests.test_dataset.conftest import FakeHub


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


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    return write_fixture(tmp_path / "pha")


class TestPhalkethohManifest:
    def test_catalog_manifest(self):
        assert MANIFEST.coordinate.canonical == COORDINATE
        assert MANIFEST.coordinate.namespace == "espaloma"
        assert MANIFEST.coordinate.name == "phalkethoh-mm-small"
        assert "mm_energy" in MANIFEST.targets.graph_level
        assert MANIFEST.artifact("main").digest is not None
        assert MANIFEST.artifact("main").locators


class TestPhalkethohMMDataset:
    def test_coordinate_and_schema(self):
        assert COORDINATE == "dataset:espaloma/phalkethoh-mm-small@1"
        assert PhalkethohMMDataset.TARGET_SCHEMA.graph_level == frozenset({"mm_energy"})
        assert PhalkethohMMDataset.TARGET_SCHEMA.atom_level == frozenset({"forces"})

    def test_max_frames_stops_early(self, fixture_root: Path):
        ds = PhalkethohMMDataset(fixture_root, download=False, split=None, max_frames=1)
        assert len(ds) == 1

    # -- what those two numbers mean -----------------------------------------
    #
    # ``PhalkethohMMDataset`` carries no ``@dataset`` declaration at all, so
    # ``DatasetBuilder._declared_manifest`` falls back to an empty
    # ``DatasetManifest`` and ``molhub info espaloma/phalkethoh-mm-small``
    # prints an empty unit column for both targets — while two in-repo
    # declarations state the units outright:
    #
    #   src/molhub/dataset/phalkethoh_mm.py:6-11 (module docstring)
    #       "Boundary units match the published Espaloma toy experiment
    #        exactly: coordinates — Å; ``mm_energy`` — kcal/mol; forces
    #        (optional) — kcal/(mol·Å)"
    #   src/molhub/dataset/phalkethoh_mm.py (MANIFEST.description)
    #       "Reference MM energies stored as graph-level u_ref in
    #        Hartree in the native DGL payload; after conversion they are
    #        mm_energy in kcal/mol (×627.5094740631). Coordinates in Å."
    #
    # The Hartree in that second quote is the *payload's* unit before the
    # conversion script runs; what this reader hands back is post-conversion
    # kcal/mol, which is what the declaration must say.
    #
    # Spelling: ASCII and solidus-composed, so ``kcal/mol/angstrom`` rather
    # than the docstring's ``kcal/(mol·Å)`` — the identical string
    # ``THEMOL_UNITS["forces"]`` already declares for the other kcal/mol dataset
    # in this repo, and the form the molpy unit registry parses for
    # ``molhub.dataset.transforms.UnitConvert``. Coordinates are in Å but are
    # not a declared target name, so the mapping carries no key for them.
    #
    # Forces are optional in the payload (``confs.npz`` may omit them); the unit
    # says what the number means when it is there, which is what
    # ``TARGET_SCHEMA`` already promises by declaring the name.

    def test_the_declaration_says_the_mm_energy_is_in_kcal_per_mole(self):
        assert PhalkethohMMDataset.manifest.units["mm_energy"] == "kcal/mol"

    def test_the_declaration_says_the_forces_are_in_kcal_per_mole_per_angstrom(self):
        assert PhalkethohMMDataset.manifest.units["forces"] == "kcal/mol/angstrom"

    def test_the_units_mapping_names_exactly_the_declared_targets(self):
        """No stray key: a unit for a name no record carries never renders."""
        schema = PhalkethohMMDataset.TARGET_SCHEMA
        assert set(PhalkethohMMDataset.manifest.units) == set(schema.graph_level) | set(
            schema.atom_level
        )

    def test_the_declaration_carries_this_modules_coordinate(self):
        """One identity: the manifest on the class names the artifact it reads."""
        assert PhalkethohMMDataset.manifest.canonical == COORDINATE

    def test_locators_live_on_the_catalog_entry(self):
        locator = MANIFEST.artifact("main").locators[0]
        assert str(locator).startswith("https://")
        assert (
            "BASE_URL"
            not in Path(molhub.__file__).parent.joinpath("dataset", "phalkethoh_mm.py").read_text()
        )

    def test_full_dataset(self, fixture_root: Path):
        ds = PhalkethohMMDataset(fixture_root, download=False, split=None)
        assert len(ds) == 4  # 2 mol × 2 conf
        assert ds.source_id == COORDINATE
        assert isinstance(ds, Dataset)

    def test_frame_contract(self, fixture_root: Path):
        ds = PhalkethohMMDataset(fixture_root, download=False, split="train")
        assert len(ds) == 2
        assert ds.source_id == f"{COORDINATE}#split=train"
        f0, f1 = ds[0][0], ds[1][0]
        assert f0.meta["molecule_id"] == "molA"
        assert f1.meta["molecule_id"] == "molA"
        assert f0.meta["mm_energy"] == pytest.approx(-1.0)
        assert f1.meta["mm_energy"] == pytest.approx(-1.5)
        assert f0.meta["conf_index"] == 0
        assert f1.meta["conformer_id"] == "1"
        # Å coords hard-coded
        assert float(f0["atoms"]["x"][1]) == pytest.approx(1.0)
        assert float(f1["atoms"]["x"][1]) == pytest.approx(1.1)
        # forces present
        assert float(f0["atoms"]["fx"][0]) == pytest.approx(0.1)
        # bonds
        assert list(f0["bonds"]["atomi"]) == [0]
        assert list(f0["bonds"]["atomj"]) == [1]
        assert "legacy_params_json" in f0.meta

    def test_split_keeps_all_confs(self, fixture_root: Path):
        val = PhalkethohMMDataset(fixture_root, download=False, split="val")
        assert len(val) == 2
        ids = {val[i][0].meta["molecule_id"] for i in range(len(val))}
        assert ids == {"molB"}
        energies = [val[i][0].meta["mm_energy"] for i in range(len(val))]
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
