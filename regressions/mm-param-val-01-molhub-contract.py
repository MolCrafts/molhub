#!/usr/bin/env python
"""Regression: molhub dataset contract — Frame is the molecule.

No network. Dataset protocol, identity on frame.meta, no wrapper in between.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from molpy import Block, Frame

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from molhub.dataset import Dataset, TargetSchema  # noqa: E402
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
    frame.meta.update({"molecule_id": molecule_id, "conformer_id": conformer_id})
    return frame


def main() -> None:
    empty = TargetSchema()
    assert empty.chemical_perception == frozenset()
    assert empty.mm == frozenset()
    assert empty.qm == frozenset()
    assert "energy" in empty.graph_level

    frames = [_frame(f"m{m:02d}", f"c{c}") for m in range(10) for c in range(2)]
    source = InMemoryDataset(frames, name="regression-mc")
    assert isinstance(source, Dataset)
    assert len(source) == 20
    assert source[0].meta["molecule_id"] == "m00"
    assert source[0].meta["conformer_id"] == "c0"
    assert source[1].meta["molecule_id"] == "m00"
    assert source[1].meta["conformer_id"] == "c1"

    print("mm-param-val-01-molhub-contract: OK")


if __name__ == "__main__":
    main()
