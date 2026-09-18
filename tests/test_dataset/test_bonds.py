"""Covalent bonds from geometry, and how far the answer rests on the cut."""

from __future__ import annotations

import numpy as np
import pytest

from molhub.dataset.bonds import _BOND_SCALE, BondMargins, infer_bonds

_METHANE_Z = np.array([6, 1, 1, 1, 1], dtype=np.int64)
_METHANE_POS = np.array(
    [
        [0.00, 0.00, 0.00],
        [1.09, 0.00, 0.00],
        [-0.36, 1.03, 0.00],
        [-0.36, -0.51, 0.89],
        [-0.36, -0.51, -0.89],
    ]
)


def _stretched(length: float) -> np.ndarray:
    pos = _METHANE_POS.copy()
    pos[1, 0] = length
    return pos


class TestInferBondsCriterion:
    def test_relaxed_methane_has_four_bonds(self):
        atomi, _ = infer_bonds(_METHANE_Z, _METHANE_POS)
        assert atomi.shape[0] == 4

    def test_a_stretched_bond_disappears(self):
        # The criterion is a hard cut at about +19 % of equilibrium length, so
        # a non-equilibrium geometry can lose a bond — and with it three
        # angles and, at the carbon that just became trivalent, an improper
        # the relaxed molecule does not have. Nothing warns.
        assert infer_bonds(_METHANE_Z, _stretched(1.30))[0].shape[0] == 3


class TestBondMargins:
    def test_a_relaxed_structure_sits_nowhere_near_the_decision(self):
        margins = BondMargins(_METHANE_Z, _METHANE_POS)
        assert margins.n_in_band == 0
        assert margins.farthest_bond < 0.9
        assert margins.closest_nonbond > 2.0

    def test_a_stretched_bond_lands_just_past_the_cut(self):
        # 1.012: the bond was lost by a little over one percent of distance.
        # That number is the point — it says how much of this structure's
        # topology rests on the criterion's exact value.
        margins = BondMargins(_METHANE_Z, _stretched(1.30))
        assert margins.n_in_band == 1
        assert 1.0 < margins.closest_nonbond < 1.05

    def test_a_bond_near_the_cut_is_reported_as_such(self):
        # Just inside: still a bond, but a tighter criterion would drop it.
        cut = _BOND_SCALE * 1.07  # covalent radii of C and H, roughly
        margins = BondMargins(_METHANE_Z, _stretched(cut * 0.97))
        assert margins.farthest_bond > 0.9
        assert margins.n_in_band >= 1

    def test_the_ratio_is_comparable_across_element_pairs(self):
        # The measure is r / cut, not r, so a C-H and a C-C at the same
        # fraction of their own thresholds report the same number.
        z = np.array([6, 6], dtype=np.int64)
        cut_cc = _BOND_SCALE * (0.76 + 0.76)
        both = BondMargins(z, np.array([[0.0, 0, 0], [cut_cc * 0.8, 0, 0]]))
        assert both.farthest_bond == pytest.approx(0.8, abs=0.02)

    def test_reports_nan_rather_than_inventing_a_number(self):
        # Two atoms far apart: no bond exists, so there is no farthest bond.
        z = np.array([6, 6], dtype=np.int64)
        margins = BondMargins(z, np.array([[0.0, 0, 0], [50.0, 0, 0]]))
        assert np.isnan(margins.farthest_bond)
        assert margins.closest_nonbond == pytest.approx(50.0 / (_BOND_SCALE * 1.52), rel=0.05)

    def test_a_single_atom_has_no_pairs_and_no_margins(self):
        margins = BondMargins(np.array([6], dtype=np.int64), np.zeros((1, 3)))
        assert margins.n_in_band == 0
        assert np.isnan(margins.farthest_bond)
        assert np.isnan(margins.closest_nonbond)

    @pytest.mark.parametrize("band", [0.0, 1.0, -0.1, 1.5])
    def test_refuses_a_band_that_is_not_a_fraction(self, band):
        with pytest.raises(ValueError):
            BondMargins(_METHANE_Z, _METHANE_POS, band=band)
