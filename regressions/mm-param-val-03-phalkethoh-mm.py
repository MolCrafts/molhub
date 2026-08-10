#!/usr/bin/env python
"""Regression: phalkethoh-mm offline fixture goldens (no network)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from molhub.dataset import PhalkethohMMDataset, Targets  # noqa: E402
from molhub.dataset.molecular import MOLECULE_ID  # noqa: E402
from molhub.dataset.phalkethoh_mm import COORDINATE  # noqa: E402


def _fixture(root: Path) -> None:
    mols = root / "mols"
    for mid, energy, x_h in (
        ("molA", [-1.0, -1.5], [1.0, 1.1]),
        ("molB", [-2.0, -2.5], [0.96, 0.97]),
    ):
        d = mols / mid
        d.mkdir(parents=True, exist_ok=True)
        z = [6, 1] if mid == "molA" else [8, 1]
        el = ["C", "H"] if mid == "molA" else ["O", "H"]
        np.savez(
            d / "atoms.npz",
            number=np.array(z, dtype=np.int64),
            element=np.array(el, dtype="U3"),
            atomi=np.array([0], dtype=np.int64),
            atomj=np.array([1], dtype=np.int64),
        )
        coords = np.zeros((2, 2, 3), dtype=np.float64)
        coords[0, 1, 0] = x_h[0]
        coords[1, 1, 0] = x_h[1]
        np.savez(
            d / "confs.npz",
            coords=coords,
            mm_energy=np.array(energy, dtype=np.float64),
        )
    (root / "splits.json").write_text(json.dumps({"train": ["molA"], "val": ["molB"], "test": []}))


def main() -> None:
    assert COORDINATE == "dataset:espaloma/phalkethoh-mm-small@1"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _fixture(root)
        full = PhalkethohMMDataset(root, download=False, split=None)
        assert len(full) == 4
        assert full.source_id == COORDINATE
        train = PhalkethohMMDataset(root, download=False, split="train")
        assert len(train) == 2
        assert train.source_id == f"{COORDINATE}#split=train"
        assert Targets(train[0])[MOLECULE_ID] == "molA"
        assert Targets(train[0])["mm_energy"] == -1.0
        assert Targets(train[1])["mm_energy"] == -1.5
    print("mm-param-val-03-phalkethoh-mm: OK")


if __name__ == "__main__":
    main()
