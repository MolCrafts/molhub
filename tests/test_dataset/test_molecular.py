"""Tests for the force-field molecular dataset contract helpers."""

from __future__ import annotations

import numpy as np
import pytest
from molpy import Block, Frame

from molhub.dataset import (
    CONFORMER_ID,
    KNOWN_SPLIT_SCHEMES,
    MOLECULE_ID,
    MolecularFrame,
    MolecularUnits,
    MoleculeSplit,
)
from molhub.dataset.meta import Targets
from molhub.dataset.protocol import InMemoryDataset, SubsetDataset


def _frame(
    z: list[int],
    *,
    molecule_id: str | None = None,
    conformer_id: str | None = None,
    with_bonds: bool = False,
) -> Frame:
    n = len(z)
    atoms = Block()
    atoms["element"] = np.array(["C"] * n, dtype="U3")
    atoms["x"] = np.zeros(n, dtype=np.float64)
    atoms["y"] = np.zeros(n, dtype=np.float64)
    atoms["z"] = np.zeros(n, dtype=np.float64)
    atoms["number"] = np.array(z, dtype=np.int64)
    frame = Frame()
    frame["atoms"] = atoms
    if with_bonds and n >= 2:
        bonds = Block()
        bonds["atomi"] = np.array([0], dtype=np.int64)
        bonds["atomj"] = np.array([1], dtype=np.int64)
        frame["bonds"] = bonds
    meta: dict[str, str] = {}
    if molecule_id is not None:
        meta[MOLECULE_ID] = molecule_id
    if conformer_id is not None:
        meta[CONFORMER_ID] = conformer_id
    if meta:
        Targets(frame).write(meta)
    return frame


class TestMolecularUnits:
    def test_tokens(self):
        assert MolecularUnits.DISTANCE == "angstrom"
        assert MolecularUnits.ENERGY == "kcal/mol"
        assert MolecularUnits.FORCE == "kcal_per_mol_angstrom"
        assert MolecularUnits.ANGLE == "radian"

    def test_describe(self):
        d = MolecularUnits.describe()
        assert d["distance"] == "angstrom"
        assert d["energy"] == "kcal/mol"
        assert d["force"] == "kcal_per_mol_angstrom"
        assert d["angle"] == "radian"


class TestMolecularFrame:
    def test_require_identity(self):
        frame = _frame([6], molecule_id="mol-a", conformer_id="c0")
        view = MolecularFrame(frame)
        assert view.molecule_id == "mol-a"
        assert view.conformer_id == "c0"
        assert view.require_identity() == "mol-a"

    def test_missing_identity_raises(self):
        frame = _frame([6])
        view = MolecularFrame(frame)
        assert view.molecule_id is None
        with pytest.raises(KeyError):
            view.require_identity()

    def test_conformer_optional(self):
        frame = _frame([6], molecule_id="mol-a")
        view = MolecularFrame(frame)
        assert view.conformer_id is None
        assert view.require_identity() == "mol-a"

    def test_has_connectivity(self):
        assert MolecularFrame(_frame([6, 1], with_bonds=True)).has_connectivity()
        assert not MolecularFrame(_frame([6, 1])).has_connectivity()


class TestMoleculeSplit:
    def _multi_conf_source(self, n_mol: int = 10, n_conf: int = 2) -> InMemoryDataset:
        frames: list[Frame] = []
        for m in range(n_mol):
            for c in range(n_conf):
                frames.append(
                    _frame(
                        [6, 1],
                        molecule_id=f"m{m:02d}",
                        conformer_id=f"c{c}",
                        with_bonds=True,
                    )
                )
        return InMemoryDataset(frames, name="mc")

    def test_random_molecule_801010_seed0(self):
        source = self._multi_conf_source(10, 2)
        mol_ids = [MolecularFrame(source[i]).require_identity() for i in range(len(source))]
        split = MoleculeSplit.random_molecule(mol_ids, ratios=(0.8, 0.1, 0.1), seed=0)

        def unique_mols(indices: tuple[int, ...]) -> set[str]:
            return {mol_ids[i] for i in indices}

        assert len(unique_mols(split.train)) == 8
        assert len(unique_mols(split.val)) == 1
        assert len(unique_mols(split.test)) == 1
        # All confs of a molecule stay together: 8*2 + 1*2 + 1*2 = 20
        assert len(split.train) == 16
        assert len(split.val) == 2
        assert len(split.test) == 2
        split.assert_molecule_disjoint(source)

    def test_apply_named_subsets(self):
        source = self._multi_conf_source(10, 2)
        mol_ids = [MolecularFrame(source[i]).require_identity() for i in range(len(source))]
        split = MoleculeSplit.random_molecule(mol_ids, seed=0)
        train, val, test = split.apply(source)
        assert isinstance(train, SubsetDataset)
        assert train.source_id == f"{source.source_id}#split=molhub-random-molecule:train"
        assert val.source_id == f"{source.source_id}#split=molhub-random-molecule:val"
        assert test.source_id == f"{source.source_id}#split=molhub-random-molecule:test"

    def test_from_index_lists_disjoint(self):
        split = MoleculeSplit.from_index_lists([0, 1], [2], [3], scheme="espaloma-original")
        assert split.train == (0, 1)
        assert split.val == (2,)
        assert split.test == (3,)
        assert split.scheme == "espaloma-original"

    def test_from_index_lists_overlap_raises(self):
        with pytest.raises(ValueError, match="overlap"):
            MoleculeSplit.from_index_lists([0, 1], [1], [2], scheme="x")

    def test_from_index_files(self, tmp_path):
        train_p = tmp_path / "train.txt"
        val_p = tmp_path / "val.txt"
        test_p = tmp_path / "test.txt"
        train_p.write_text("# train\n0\n1\n\n")
        val_p.write_text("2\n# comment\n")
        test_p.write_text("3\n")
        split = MoleculeSplit.from_index_files(train_p, val_p, test_p, scheme="espaloma-original")
        assert split.train == (0, 1)
        assert split.val == (2,)
        assert split.test == (3,)

    def test_assert_molecule_disjoint_detects_leak(self):
        # Two confs of m0 placed in train and val deliberately.
        frames = [
            _frame([6], molecule_id="m0", conformer_id="c0"),
            _frame([6], molecule_id="m0", conformer_id="c1"),
            _frame([6], molecule_id="m1", conformer_id="c0"),
        ]
        source = InMemoryDataset(frames, name="leak")
        split = MoleculeSplit.from_index_lists([0], [1], [2], scheme="x")
        with pytest.raises(ValueError, match="molecule_id"):
            split.assert_molecule_disjoint(source)


class TestPublicReExports:
    def test_known_schemes(self):
        assert "espaloma-original" in KNOWN_SPLIT_SCHEMES
        assert "molhub-random-molecule" in KNOWN_SPLIT_SCHEMES

    def test_import_from_package(self):
        import molhub.dataset as ds

        assert ds.MOLECULE_ID == "molecule_id"
        assert ds.CONFORMER_ID == "conformer_id"
        assert ds.MolecularUnits.ENERGY == "kcal/mol"
        assert ds.MolecularFrame is MolecularFrame
        assert ds.MoleculeSplit is MoleculeSplit
        assert "espaloma-original" in ds.KNOWN_SPLIT_SCHEMES
