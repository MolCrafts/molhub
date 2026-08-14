"""Tests for the prepare-stage transforms — AtomicDress, UnitConvert, ConstantLabel.

These three carry the numerical content of the deleted molnex task tree
(``src/molix/data/tasks/{dress,unit,constant}.py`` at molnex commit ``6d425f7^``),
re-expressed on MolHub's sample shape: a :class:`molpy.Frame` whose graph-level
targets live in ``frame.meta`` and whose per-atom data lives in the ``atoms``
block.

The goldens are hand-derived, not observed:

*AtomicDress* fits per-element baselines by least squares on the count matrix
``counts @ beta ≈ target``. The overdetermined fixture below repeats one
composition with a perturbed energy, which makes the exact solution and the
exact residual derivable by hand:

    rows (H, C, O counts)      target (eV)
    H2O   (2, 0, 1)            -9.0
    CH4   (4, 1, 0)            -6.0
    CO2   (0, 1, 2)           -20.0
    H2O'  (2, 0, 1)            -8.6      <- same row, +0.4 eV

A duplicated row ``a`` with targets ``y`` and ``y + d`` contributes
``2 (a·b - ybar)^2 + d^2 / 2`` with ``ybar = y + d/2``, so the fit is the exact
solution of the 3x3 system with right-hand side ``(-8.8, -6.0, -20.0)``:

    2h +  o = -8.8      h = -0.45
    4h +  c = -6.0  =>  c = -4.2
     c + 2o = -20.0     o = -7.9

and the residual sum of squares is exactly ``d^2 / 2 = 0.08``, split as
``(-0.2, 0, 0, +0.2)`` over the four samples. Verified against
``numpy.linalg.lstsq`` (numpy 2.5.1, 2026-08-14); pinned at 1e-10.

*UnitConvert* factors are the CODATA values the deleted molnex test pinned:
``hartree -> eV = 27.211386245988``, ``hartree/bohr -> eV/angstrom = 51.42208619``,
``bohr -> angstrom = 0.529177210903``.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
from molpy import Block, Frame, UnitsError

from molhub.dataset import transforms
from molhub.dataset.transforms import (
    AtomicDress,
    ConstantLabel,
    MetaScalar,
    UnitConvert,
    _with_targets,
)

# ---------------------------------------------------------------------------
# Hand-built samples
# ---------------------------------------------------------------------------

#: Least-squares baselines of the overdetermined fixture, per element.
_BASELINES = {1: -0.45, 6: -4.2, 8: -7.9}
#: Per-sample residuals ``target - baseline`` in fixture order.
_RESIDUALS = (-0.2, 0.0, 0.0, 0.2)
#: Residual sum of squares of the fit.
_RESIDUAL_SS = 0.08

#: Exactly determined variant (drop the repeated row) — residual is zero.
_EXACT_BASELINES = {1: -0.5, 6: -4.0, 8: -8.0}

_HARTREE_TO_EV = 27.211386245988
_HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM = 51.42208619
_BOHR_TO_ANGSTROM = 0.529177210903


def _sample(numbers: list[int], targets: dict[str, float]) -> Frame:
    """One sample: an ``atoms`` block of atomic numbers plus graph-level targets."""
    frame = Frame()
    block = Block()
    block["number"] = np.array(numbers, dtype=np.int64)
    frame["atoms"] = block
    frame.meta.update(targets)
    return frame


def _dress_samples() -> list[Frame]:
    """The overdetermined 4-sample, 3-element fixture from the module docstring."""
    return [
        _sample([1, 1, 8], {"U0": -9.0}),
        _sample([6, 1, 1, 1, 1], {"U0": -6.0}),
        _sample([6, 8, 8], {"U0": -20.0}),
        _sample([1, 1, 8], {"U0": -8.6}),
    ]


def _exact_dress_samples() -> list[Frame]:
    return _dress_samples()[:3]


# ---------------------------------------------------------------------------
# AtomicDress
# ---------------------------------------------------------------------------


class TestAtomicDress:
    def test_fit_recovers_the_hand_derived_baselines(self):
        dress = AtomicDress(elements=(1, 6, 8), target_key="U0")
        dress.fit(_dress_samples())
        for element, expected in _BASELINES.items():
            assert dress.atomic_energies[element] == pytest.approx(expected, abs=1e-10)

    def test_fit_on_an_exactly_determined_set_is_exact(self):
        dress = AtomicDress(elements=(1, 6, 8), target_key="U0")
        dress.fit(_exact_dress_samples())
        for element, expected in _EXACT_BASELINES.items():
            assert dress.atomic_energies[element] == pytest.approx(expected, abs=1e-10)

    def test_dressed_targets_are_the_least_squares_residuals(self):
        dress = AtomicDress(elements=(1, 6, 8), target_key="U0", output_key="U0_dressed")
        samples = _dress_samples()
        dress.fit(samples)
        got = [float(dressed.meta["U0_dressed"]) for dressed in map(dress.execute, samples)]
        for value, expected in zip(got, _RESIDUALS):
            assert value == pytest.approx(expected, abs=1e-10)

    def test_residual_sum_of_squares(self):
        dress = AtomicDress(elements=(1, 6, 8), target_key="U0", output_key="U0_dressed")
        samples = _dress_samples()
        dress.fit(samples)
        residuals = [float(dressed.meta["U0_dressed"]) for dressed in map(dress.execute, samples)]
        assert sum(r * r for r in residuals) == pytest.approx(_RESIDUAL_SS, abs=1e-10)

    def test_exactly_determined_fit_dresses_to_zero(self):
        dress = AtomicDress(elements=(1, 6, 8), target_key="U0", output_key="U0_dressed")
        samples = _exact_dress_samples()
        dress.fit(samples)
        for dressed in map(dress.execute, samples):
            assert float(dressed.meta["U0_dressed"]) == pytest.approx(0.0, abs=1e-10)

    def test_output_key_defaults_to_the_target_key(self):
        dress = AtomicDress(elements=(1, 6, 8), target_key="U0")
        samples = _dress_samples()
        dress.fit(samples)
        assert float(dress.execute(samples[0]).meta["U0"]) == pytest.approx(-0.2, abs=1e-10)

    def test_execute_leaves_the_input_sample_untouched(self):
        dress = AtomicDress(elements=(1, 6, 8), target_key="U0")
        samples = _dress_samples()
        dress.fit(samples)
        dress.execute(samples[0])
        assert float(samples[0].meta["U0"]) == pytest.approx(-9.0, abs=1e-10)

    def test_execute_keeps_the_atoms_block(self):
        dress = AtomicDress(elements=(1, 6, 8), target_key="U0")
        samples = _dress_samples()
        dress.fit(samples)
        assert list(dress.execute(samples[1])["atoms"]["number"]) == [6, 1, 1, 1, 1]

    def test_execute_before_fit_raises(self):
        """An unfitted dress must refuse, not silently subtract zeros."""
        dress = AtomicDress(elements=(1, 6, 8), target_key="U0")
        with pytest.raises(RuntimeError, match="fit"):
            dress.execute(_dress_samples()[0])

    def test_missing_target_raises_on_fit(self):
        dress = AtomicDress(elements=(1, 6, 8), target_key="U0")
        with pytest.raises(KeyError, match="U0"):
            dress.fit([_sample([1, 1, 8], {"energy": -9.0})])

    def test_missing_target_raises_on_execute(self):
        dress = AtomicDress(elements=(1, 6, 8), target_key="U0")
        dress.fit(_dress_samples())
        with pytest.raises(KeyError, match="U0"):
            dress.execute(_sample([1, 1, 8], {"energy": -9.0}))


class TestAtomicDressState:
    def test_state_dict_elements_are_sorted_ascending(self):
        dress = AtomicDress(elements=(8, 1, 6), target_key="U0")
        dress.fit(_dress_samples())
        assert list(dress.state_dict()["elements"]) == [1, 6, 8]

    def test_state_dict_energies_align_with_elements(self):
        dress = AtomicDress(elements=(8, 1, 6), target_key="U0")
        dress.fit(_dress_samples())
        state = dress.state_dict()
        for element, energy in zip(state["elements"], state["energies"]):
            assert float(energy) == pytest.approx(_BASELINES[int(element)], abs=1e-10)

    def test_load_state_dict_restores_the_baselines(self):
        fitted = AtomicDress(elements=(1, 6, 8), target_key="U0")
        fitted.fit(_dress_samples())
        restored = AtomicDress(elements=(1, 6, 8), target_key="U0")
        restored.load_state_dict(fitted.state_dict())
        for element, expected in _BASELINES.items():
            assert restored.atomic_energies[element] == pytest.approx(expected, abs=1e-10)

    def test_round_trip_dresses_identically(self):
        """A cached dress must reproduce the fitted one bit-for-bit in effect."""
        samples = _dress_samples()
        fitted = AtomicDress(elements=(1, 6, 8), target_key="U0", output_key="U0_dressed")
        fitted.fit(samples)
        restored = AtomicDress(elements=(1, 6, 8), target_key="U0", output_key="U0_dressed")
        restored.load_state_dict(fitted.state_dict())
        for sample in samples:
            a = float(fitted.execute(sample).meta["U0_dressed"])
            b = float(restored.execute(sample).meta["U0_dressed"])
            assert a == pytest.approx(b, abs=1e-10)

    def test_a_restored_dress_no_longer_refuses_to_execute(self):
        fitted = AtomicDress(elements=(1, 6, 8), target_key="U0")
        fitted.fit(_dress_samples())
        restored = AtomicDress(elements=(1, 6, 8), target_key="U0")
        restored.load_state_dict(fitted.state_dict())
        assert float(restored.execute(_dress_samples()[0]).meta["U0"]) == pytest.approx(
            -0.2, abs=1e-10
        )


# ---------------------------------------------------------------------------
# UnitConvert
# ---------------------------------------------------------------------------


class TestUnitConvertFactors:
    def test_hartree_to_ev(self):
        convert = UnitConvert({"U0": ("hartree", "eV")})
        assert convert.factors["U0"] == pytest.approx(_HARTREE_TO_EV, rel=1e-6)

    def test_hartree_per_bohr_to_ev_per_angstrom(self):
        """Derived units flow through the registry unchanged."""
        convert = UnitConvert({"forces": ("hartree / bohr", "eV / angstrom")})
        assert convert.factors["forces"] == pytest.approx(
            _HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM, rel=1e-4
        )

    def test_bohr_to_angstrom(self):
        convert = UnitConvert({"length": ("bohr", "angstrom")})
        assert convert.factors["length"] == pytest.approx(_BOHR_TO_ANGSTROM, rel=1e-4)

    def test_each_field_chooses_its_own_pair(self):
        """No preset bundles: whatever the caller types is what they get."""
        convert = UnitConvert(
            {
                "energy": ("hartree", "eV"),
                "forces": ("hartree / bohr", "eV / angstrom"),
                "length": ("bohr", "angstrom"),
            }
        )
        assert convert.factors["energy"] == pytest.approx(_HARTREE_TO_EV, rel=1e-6)
        assert convert.factors["length"] == pytest.approx(_BOHR_TO_ANGSTROM, rel=1e-4)


class TestUnitConvertApply:
    def test_scalar_target_is_rescaled(self):
        convert = UnitConvert({"U0": ("hartree", "eV")})
        out = convert.execute(_sample([1, 1], {"U0": 1.0}))
        assert float(out.meta["U0"]) == pytest.approx(_HARTREE_TO_EV, rel=1e-6)

    def test_conversion_is_linear_in_the_value(self):
        convert = UnitConvert({"U0": ("hartree", "eV")})
        out = convert.execute(_sample([1, 1], {"U0": 2.0}))
        assert float(out.meta["U0"]) == pytest.approx(2 * _HARTREE_TO_EV, rel=1e-6)

    def test_every_configured_field_is_converted(self):
        convert = UnitConvert({"U0": ("hartree", "eV"), "U": ("hartree", "eV")})
        out = convert.execute(_sample([1], {"U0": 1.0, "U": 2.0}))
        assert float(out.meta["U0"]) == pytest.approx(_HARTREE_TO_EV, rel=1e-6)
        assert float(out.meta["U"]) == pytest.approx(2 * _HARTREE_TO_EV, rel=1e-6)

    def test_unconfigured_targets_pass_through(self):
        convert = UnitConvert({"U0": ("hartree", "eV")})
        out = convert.execute(_sample([1], {"U0": 1.0, "gap": 0.25}))
        assert float(out.meta["gap"]) == pytest.approx(0.25, abs=1e-10)

    def test_input_sample_is_left_untouched(self):
        convert = UnitConvert({"U0": ("hartree", "eV")})
        sample = _sample([1, 1], {"U0": 1.0})
        convert.execute(sample)
        assert float(sample.meta["U0"]) == pytest.approx(1.0, abs=1e-10)

    def test_input_sample_meta_is_unchanged_as_a_whole(self):
        """Purity read off the frame: every key and value survives execute()."""
        convert = UnitConvert({"U0": ("hartree", "eV")})
        sample = _sample([1, 1], {"U0": 1.0, "gap": 0.25})
        convert.execute(sample)
        assert dict(sample.meta) == pytest.approx({"U0": 1.0, "gap": 0.25}, abs=1e-10)

    def test_missing_target_raises(self):
        convert = UnitConvert({"U": ("hartree", "eV")})
        with pytest.raises(KeyError, match="U"):
            convert.execute(_sample([1], {"U0": 1.0}))


class TestUnitConvertConstruction:
    def test_empty_conversions_raises(self):
        with pytest.raises(ValueError, match="at least one"):
            UnitConvert({})

    def test_non_tuple_value_raises(self):
        with pytest.raises(ValueError, match="2-tuple"):
            UnitConvert({"x": "hartree"})

    def test_wrong_arity_value_raises(self):
        with pytest.raises(ValueError, match="2-tuple"):
            UnitConvert({"x": ("hartree",)})

    def test_incompatible_dimensions_raise(self):
        """The registry rejects hartree → Å (energy vs length)."""
        with pytest.raises(UnitsError):
            UnitConvert({"x": ("hartree", "angstrom")})

    def test_unknown_unit_raises(self):
        with pytest.raises(UnitsError):
            UnitConvert({"x": ("nonsense", "eV")})


# ---------------------------------------------------------------------------
# ConstantLabel
# ---------------------------------------------------------------------------


class TestConstantLabel:
    def test_writes_the_constant_as_a_graph_level_target(self):
        label = ConstantLabel(key="total_charge", value=0.0)
        out = label.execute(_sample([1, 1, 8], {"energy": -9.0}))
        assert float(out.meta["total_charge"]) == pytest.approx(0.0, abs=1e-10)

    def test_non_zero_constant(self):
        label = ConstantLabel(key="total_charge", value=-1.0)
        out = label.execute(_sample([1, 1, 8], {"energy": -9.0}))
        assert float(out.meta["total_charge"]) == pytest.approx(-1.0, abs=1e-10)

    def test_integer_value_is_stored_as_a_float(self):
        label = ConstantLabel(key="total_charge", value=0)
        out = label.execute(_sample([1], {"energy": -1.0}))
        assert isinstance(out.meta["total_charge"], float)

    def test_existing_targets_survive(self):
        label = ConstantLabel(key="total_charge", value=0.0)
        out = label.execute(_sample([1, 1, 8], {"energy": -9.0}))
        assert float(out.meta["energy"]) == pytest.approx(-9.0, abs=1e-10)

    def test_atoms_block_is_untouched(self):
        label = ConstantLabel(key="total_charge", value=0.0)
        out = label.execute(_sample([1, 1, 8], {"energy": -9.0}))
        assert list(out["atoms"]["number"]) == [1, 1, 8]

    def test_input_sample_is_left_untouched(self):
        label = ConstantLabel(key="total_charge", value=0.0)
        sample = _sample([1], {"energy": -1.0})
        label.execute(sample)
        assert "total_charge" not in sample.meta

    def test_existing_key_is_overwritten(self):
        label = ConstantLabel(key="total_charge", value=0.0)
        out = label.execute(_sample([1], {"total_charge": 3.0}))
        assert float(out.meta["total_charge"]) == pytest.approx(0.0, abs=1e-10)

    def test_empty_key_raises(self):
        with pytest.raises(ValueError, match="key"):
            ConstantLabel(key="", value=0.0)


# ---------------------------------------------------------------------------
# Graph-level meta lives on the frame, not behind a molhub wrapper
# ---------------------------------------------------------------------------

#: The wrapper identifiers ``hf-facade-01-meta-dissolution`` deletes. Boundary
#: aware on purpose: ``write_metadata`` (DerivedLayout's unrelated conveyor API)
#: and ``TargetSchema`` / ``TargetDeclaration`` must never match.
_DISSOLVED_WRAPPERS = re.compile(r"\bTargets\b|\bMetaCodec\b|\bwrite_meta\b(?!data)")


def _dissolved_wrapper_names(module: ModuleType) -> list[str]:
    """Deleted meta-wrapper identifiers still named in *module*'s source."""
    path = module.__file__
    assert path is not None
    source = Path(path).read_text(encoding="utf-8")
    return sorted({match.group() for match in _DISSOLVED_WRAPPERS.finditer(source)})


class TestTransformsMetaSurface:
    """The three transforms read and write ``frame.meta`` with nothing between."""

    def test_dressed_target_is_read_straight_off_frame_meta(self):
        dress = AtomicDress(elements=(1, 6, 8), target_key="U0", output_key="U0_dressed")
        samples = _dress_samples()
        dress.fit(samples)
        assert float(dress.execute(samples[0]).meta["U0_dressed"]) == pytest.approx(-0.2, abs=1e-10)

    def test_meta_scalar_stays_the_documented_scalar_contract(self):
        """The deleted codec goes; the union naming what meta may hold does not."""
        assert MetaScalar == bool | int | float | str

    def test_a_non_scalar_target_is_rejected_by_molpy(self):
        """Rejection is the platform's job now, so its message is molpy's.

        molpy 0.13.1: ``metadata values must be bool, int, float, str, a
        fixed-length sequence, or MetaValue, got NoneType``.
        """
        with pytest.raises(TypeError, match="metadata values must be"):
            _with_targets(_sample([1], {"U0": 1.0}), {"U0": None})

    def test_module_namespace_holds_no_deleted_meta_wrapper(self):
        assert [
            name for name in ("Targets", "MetaCodec", "write_meta") if hasattr(transforms, name)
        ] == []

    def test_module_source_names_no_deleted_meta_wrapper(self):
        assert _dissolved_wrapper_names(transforms) == []
