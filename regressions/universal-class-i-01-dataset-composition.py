#!/usr/bin/env python
"""Regression: Class1Universal2026 v0 role map (no network, no THEMol fetch).

Hard-coded goldens from
`.claude/specs/universal-class-i-01-dataset-composition.md` (revised
2026-08-20). Units are the sources' native ones, recorded verbatim —
molhub never converts (operator decision 2026-08-20); consumers convert
(1 eV = 23.06055 kcal/mol stays a Domain-basis comment only).

    PYTHONPATH=src python regressions/universal-class-i-01-dataset-composition.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from molhub.dataset import Class1Universal2026  # noqa: E402

_THEMOL = (
    "dataset:themol/hessian@1",
    "dataset:themol/torsion-scan@1",
    "dataset:molcrafts/themol-relax-diverse@1",
    "dataset:themol/mbis@1",
)


def main() -> int:
    collection = Class1Universal2026().load()
    assert collection.coordinate == "dataset:molcrafts/class1-universal-2026@1"
    assert tuple(role.name for role in collection.active_roles) == (
        "train",
        "validation",
    )
    assert collection.source_coordinates == (
        "dataset:molcrafts/omol25-small@1",
        "dataset:espaloma/phalkethoh-mm-small@1",
    )
    for coordinate in _THEMOL:
        assert coordinate not in collection.source_coordinates
    for name in ("equilibrium", "torsion", "off-equilibrium", "electrostatic"):
        assert collection.role(name).active is False
    assert dict(collection.role("train").units)["energy"] == "eV"
    assert dict(collection.role("validation").units)["mm_energy"] == "kcal/mol"
    print("universal-class-i-01-dataset-composition OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
