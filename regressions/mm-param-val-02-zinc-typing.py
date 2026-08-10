#!/usr/bin/env python
"""Regression: zinc-typing offline fixture hard-coded goldens (no network)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from molhub.dataset import Targets, ZincTypingDataset  # noqa: E402
from molhub.dataset.molecular import MOLECULE_ID  # noqa: E402
from molhub.dataset.zinc_typing import COORDINATE  # noqa: E402


def _write_fixture(root: Path) -> None:
    mols = root / "mols"
    specs = {
        "m00": ([6, 1], ["c3", "hc"], [(0, 1)], ["C", "H"]),
        "m01": ([8, 1], ["oh", "ho"], [(0, 1)], ["O", "H"]),
        "m02": ([6, 6, 1], ["c3", "c3", "hc"], [(0, 1), (1, 2)], ["C", "C", "H"]),
        "m03": ([7, 1], ["n3", "hn"], [(0, 1)], ["N", "H"]),
        "m04": ([6, 8], ["c3", "oh"], [(0, 1)], ["C", "O"]),
    }
    for mid, (nums, types, bonds, elems) in specs.items():
        d = mols / mid
        d.mkdir(parents=True, exist_ok=True)
        np.savez(
            d / "atoms.npz",
            number=np.array(nums, dtype=np.int64),
            atom_type=np.array(types, dtype="U16"),
            element=np.array(elems, dtype="U3"),
        )
        np.savez(
            d / "bonds.npz",
            atomi=np.array([a for a, _ in bonds], dtype=np.int64),
            atomj=np.array([b for _, b in bonds], dtype=np.int64),
        )
    (root / "splits.json").write_text(
        json.dumps({"train": ["m00", "m01", "m02"], "val": ["m03"], "test": ["m04"]})
    )


def main() -> None:
    assert COORDINATE == "dataset:espaloma/zinc-typing@1"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_fixture(root)
        train = ZincTypingDataset(root, split="train", download=False)
        val = ZincTypingDataset(root, split="val", download=False)
        test = ZincTypingDataset(root, split="test", download=False)
        assert len(train) == 3
        assert len(val) == 1
        assert len(test) == 1
        assert train.source_id == f"{COORDINATE}#split=train"
        frame = train[0]
        assert Targets(frame)[MOLECULE_ID] == "m00"
        assert list(frame["atoms"]["atom_type"]) == ["c3", "hc"]
        assert list(frame["bonds"]["atomi"]) == [0]
        assert list(frame["bonds"]["atomj"]) == [1]
        assert set(train.molecule_ids).isdisjoint(set(val.molecule_ids))
        assert set(train.molecule_ids).isdisjoint(set(test.molecule_ids))
    print("mm-param-val-02-zinc-typing: OK")


if __name__ == "__main__":
    main()
