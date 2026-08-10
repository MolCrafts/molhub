#!/usr/bin/env python
"""Regression: molhub force-field dataset contract hard-coded goldens.

No network. Asserts unit tokens, TargetSchema semantic families,
seed=0 8/1/1 molecule split, and named ``#split=`` source_ids.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from molpy import Block, Frame

# Allow running from repo root without install in some environments.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from molhub.dataset import (  # noqa: E402
    CONFORMER_ID,
    KNOWN_SPLIT_SCHEMES,
    MOLECULE_ID,
    MolecularFrame,
    MolecularUnits,
    MoleculeSplit,
    TargetSchema,
)
from molhub.dataset.meta import Targets  # noqa: E402
from molhub.dataset.protocol import InMemoryDataset  # noqa: E402


def _frame(molecule_id: str, conformer_id: str) -> Frame:
    atoms = Block()
    atoms["element"] = np.array(["C", "H"], dtype="U3")
    atoms["x"] = np.zeros(2, dtype=np.float64)
    atoms["y"] = np.zeros(2, dtype=np.float64)
    atoms["z"] = np.zeros(2, dtype=np.float64)
    atoms["number"] = np.array([6, 1], dtype=np.int64)
    frame = Frame()
    frame["atoms"] = atoms
    Targets(frame).write({MOLECULE_ID: molecule_id, CONFORMER_ID: conformer_id})
    return frame


def main() -> None:
    # Unit tokens
    assert MolecularUnits.DISTANCE == "angstrom"
    assert MolecularUnits.ENERGY == "kcal/mol"
    assert MolecularUnits.FORCE == "kcal_per_mol_angstrom"
    assert MolecularUnits.ANGLE == "radian"

    # TargetSchema families
    empty = TargetSchema()
    assert empty.chemical_perception == frozenset()
    assert empty.mm == frozenset()
    assert empty.qm == frozenset()
    assert "energy" in empty.graph_level
    named = TargetSchema(
        chemical_perception=frozenset({"atom_type"}),
        mm=frozenset({"energy", "forces"}),
    )
    assert named.chemical_perception == frozenset({"atom_type"})
    assert named.mm == frozenset({"energy", "forces"})

    assert "espaloma-original" in KNOWN_SPLIT_SCHEMES
    assert "molhub-random-molecule" in KNOWN_SPLIT_SCHEMES

    # 10 molecules × 2 confs, seed=0 → 8/1/1 unique molecules
    frames = [_frame(f"m{m:02d}", f"c{c}") for m in range(10) for c in range(2)]
    source = InMemoryDataset(frames, name="regression-mc")
    mol_ids = [MolecularFrame(source[i]).require_identity() for i in range(len(source))]
    split = MoleculeSplit.random_molecule(mol_ids, ratios=(0.8, 0.1, 0.1), seed=0)
    n_train = len({mol_ids[i] for i in split.train})
    n_val = len({mol_ids[i] for i in split.val})
    n_test = len({mol_ids[i] for i in split.test})
    assert (n_train, n_val, n_test) == (8, 1, 1), (n_train, n_val, n_test)
    split.assert_molecule_disjoint(source)

    train, val, test = split.apply(source)
    assert train.source_id.endswith("#split=molhub-random-molecule:train")
    assert val.source_id.endswith("#split=molhub-random-molecule:val")
    assert test.source_id.endswith("#split=molhub-random-molecule:test")
    assert train.source_id.startswith(source.source_id)

    print("mm-param-val-01-molhub-contract: OK")


if __name__ == "__main__":
    main()
