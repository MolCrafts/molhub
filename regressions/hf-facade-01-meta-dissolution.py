#!/usr/bin/env python
"""Regression: graph-level meta is ``frame.meta``, and the numbers did not move.

``hf-facade-01-meta-dissolution`` deleted molhub's three metadata wrappers and
routed every producer and consumer at ``molpy.Frame.meta`` directly. That
change is only correct if it is *value preserving*, so this script re-derives
the published transform goldens through the public ``molhub.dataset`` surface
alone, writing and reading graph scalars with nothing between the caller and
the frame.

The literals below are hard-coded, not recomputed: they are the same baselines,
residuals, conversion factor and constant label that
``regressions/molix-data-dissolution-05-molhub-reception.py`` and
``tests/test_dataset/test_transforms.py`` assert. No network, no third-party
runtime, no live oracle.

Fixture — the overdetermined 4-sample, 3-element set (H2O, CH4, CO2, H2O')::

    H2O   U0 = -9.0 eV      CH4  U0 =  -6.0 eV
    CO2   U0 = -20.0 eV     H2O' U0 =  -8.6 eV

Least squares over it gives the per-element baselines and residuals pinned
here; every value is exactly representable in binary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from molpy import Block, Frame

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from molhub.dataset import AtomicDress, ConstantLabel, UnitConvert  # noqa: E402

# ---------------------------------------------------------------------------
# Goldens (identical to the reception regression and the unit tests)
# ---------------------------------------------------------------------------

_ENERGY_EXACT_ATOL = 1e-10  # energies that round-trip in binary
_FACTOR_RTOL = 1e-6

_BASELINES = {1: -0.45, 6: -4.2, 8: -7.9}
_RESIDUALS = (-0.2, 0.0, 0.0, 0.2)
_RESIDUAL_SS = 0.08  # d^2 / 2 with d = 0.4 eV
_HARTREE_TO_EV = 27.211386245988
_TOTAL_CHARGE = 0.0

_SAMPLE_ENERGIES_EV = (-9.0, -6.0, -20.0, -8.6)
_SAMPLE_NUMBERS = ([1, 1, 8], [6, 1, 1, 1, 1], [6, 8, 8], [1, 1, 8])


def _sample(numbers: list[int], targets: dict[str, float]) -> Frame:
    """One sample: an ``atoms`` block of atomic numbers plus graph-level targets."""
    frame = Frame()
    block = Block()
    block["number"] = np.array(numbers, dtype=np.int64)
    frame["atoms"] = block
    frame.meta.update(targets)
    return frame


# ---------------------------------------------------------------------------
# Leg 1 — the frame is the only metadata container
# ---------------------------------------------------------------------------


def check_frame_meta_is_the_whole_surface() -> None:
    """Merge, whole replacement, plain-scalar reads, and the platform's refusal."""
    frame = _sample([1, 1, 8], {"U0": -9.0})
    assert float(frame.meta["U0"]) == -9.0
    assert isinstance(frame.meta["U0"], float), "molpy hands back a plain Python float"

    frame.meta.update({"gap": 0.25})
    assert set(frame.meta) == {"U0", "gap"}, "update() merges"
    assert float(frame.meta["U0"]) == -9.0

    frame.meta = {"U0": -9.0}
    assert set(frame.meta) == {"U0"}, "assignment replaces wholesale"

    detached = dict(frame.meta)
    detached["U0"] = 0.0
    assert float(frame.meta["U0"]) == -9.0, "dict(frame.meta) is a detached copy"

    try:
        frame.meta.update({"bad": None})
    except TypeError:
        pass
    else:  # pragma: no cover - molpy owns this refusal now
        raise AssertionError("a non-scalar meta value must be refused by molpy")

    print(
        "  Frame.meta: update() merges, assignment replaces, dict() detaches, "
        "non-scalar refused by molpy"
    )


# ---------------------------------------------------------------------------
# Leg 2 — UnitConvert -> AtomicDress -> ConstantLabel, end to end
# ---------------------------------------------------------------------------


def check_transform_chain() -> None:
    """The published goldens, re-derived through the public transform surface."""
    convert = UnitConvert({"U0": ("hartree", "eV")})
    assert abs(convert.factors["U0"] / _HARTREE_TO_EV - 1.0) <= _FACTOR_RTOL

    # Store the fixture in hartree so the chain starts at UnitConvert.
    raw = [
        _sample(numbers, {"U0": energy / _HARTREE_TO_EV})
        for numbers, energy in zip(_SAMPLE_NUMBERS, _SAMPLE_ENERGIES_EV)
    ]
    converted = [convert.execute(sample) for sample in raw]
    for sample, want in zip(converted, _SAMPLE_ENERGIES_EV):
        assert abs(float(sample.meta["U0"]) - want) <= _ENERGY_EXACT_ATOL
    for sample, want in zip(raw, _SAMPLE_ENERGIES_EV):
        got = float(sample.meta["U0"]) * _HARTREE_TO_EV
        assert abs(got - want) <= _ENERGY_EXACT_ATOL, "UnitConvert.execute mutated its input"

    dress = AtomicDress(elements=(1, 6, 8), target_key="U0", output_key="U0_dressed")
    dress.fit(converted)
    for element, want in _BASELINES.items():
        assert abs(dress.atomic_energies[element] - want) <= _ENERGY_EXACT_ATOL

    dressed = [dress.execute(sample) for sample in converted]
    residuals = [float(sample.meta["U0_dressed"]) for sample in dressed]
    for got, want in zip(residuals, _RESIDUALS):
        assert abs(got - want) <= _ENERGY_EXACT_ATOL
    assert abs(sum(r * r for r in residuals) - _RESIDUAL_SS) <= _ENERGY_EXACT_ATOL
    assert "U0_dressed" not in converted[0].meta, "AtomicDress.execute mutated its input"

    labelled = [ConstantLabel(key="total_charge", value=_TOTAL_CHARGE).execute(s) for s in dressed]
    for sample, want in zip(labelled, _RESIDUALS):
        assert isinstance(sample.meta["total_charge"], float)
        assert abs(float(sample.meta["total_charge"]) - _TOTAL_CHARGE) <= _ENERGY_EXACT_ATOL
        assert abs(float(sample.meta["U0_dressed"]) - want) <= _ENERGY_EXACT_ATOL
    assert "total_charge" not in dressed[0].meta, "ConstantLabel.execute mutated its input"

    print(
        f"  Chain UnitConvert→AtomicDress→ConstantLabel: hartree→eV {_HARTREE_TO_EV}, "
        f"baselines {_BASELINES} eV (atol 1e-10), residual SS {_RESIDUAL_SS}, "
        f"total_charge {_TOTAL_CHARGE}"
    )


def main() -> None:
    check_frame_meta_is_the_whole_surface()
    check_transform_chain()
    print("hf-facade-01-meta-dissolution: OK")


if __name__ == "__main__":
    main()
