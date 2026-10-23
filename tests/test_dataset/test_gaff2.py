"""The shipped GAFF2 Lennard-Jones table and its ``sigma`` / ``epsilon`` reads."""

from __future__ import annotations

import math

import numpy as np
import pytest

from molhub.dataset.gaff2 import Gaff2LennardJones

#: ``R*`` and ``epsilon`` of two rows, as literals from gaff2.dat (MOD4 RE).
CA_RSTAR, CA_EPSILON = 1.8606, 0.0988
HC_RSTAR, HC_EPSILON = 1.4593, 0.0208


class TestGaff2LennardJones:
    def test_the_table_ships_every_gaff2_type(self) -> None:
        table = Gaff2LennardJones()
        assert len(table) == 98
        assert "ca" in table and "n+" in table and "sy" in table
        assert table.units == {"sigma": "angstrom", "epsilon": "kcal/mol"}

    def test_sigma_is_the_zero_crossing_of_the_tabulated_rstar(self) -> None:
        """``sigma = 2 R* / 2**(1/6)``: the minimum sits at ``2 R*``, not at ``sigma``."""
        table = Gaff2LennardJones()
        assert table.sigma("ca") == pytest.approx(2.0 * CA_RSTAR / 2.0 ** (1.0 / 6.0), rel=1e-12)
        assert table.sigma("hc") == pytest.approx(2.0 * HC_RSTAR / 2.0 ** (1.0 / 6.0), rel=1e-12)
        assert table.sigma("ca") == pytest.approx(3.3152, abs=5e-5)

    def test_epsilon_is_the_tabulated_well_depth(self) -> None:
        table = Gaff2LennardJones()
        assert table.epsilon("ca") == CA_EPSILON
        assert table.epsilon("hc") == HC_EPSILON

    def test_an_unknown_type_raises_key_error(self) -> None:
        table = Gaff2LennardJones()
        with pytest.raises(KeyError, match="'zz'"):
            table.sigma("zz")
        with pytest.raises(KeyError, match="'zz'"):
            table.epsilon("zz")

    def test_du_is_not_a_row(self) -> None:
        """Antechamber's catch-all has no well; asking for one is an error, not zero."""
        table = Gaff2LennardJones()
        assert "DU" not in table
        with pytest.raises(KeyError, match="'DU'"):
            table.epsilon("DU")

    def test_sigma_epsilon_maps_du_and_unknown_to_nan(self) -> None:
        sigma, epsilon = Gaff2LennardJones().sigma_epsilon(["ca", "DU", "hc", "zz"])
        assert sigma.dtype == np.float64 and epsilon.dtype == np.float64
        assert sigma.shape == (4,) and epsilon.shape == (4,)
        assert sigma[0] == pytest.approx(2.0 * CA_RSTAR / 2.0 ** (1.0 / 6.0), rel=1e-12)
        assert epsilon[2] == HC_EPSILON
        assert math.isnan(sigma[1]) and math.isnan(epsilon[1])
        assert math.isnan(sigma[3]) and math.isnan(epsilon[3])

    def test_sigma_epsilon_of_nothing_is_two_empty_arrays(self) -> None:
        sigma, epsilon = Gaff2LennardJones().sigma_epsilon([])
        assert sigma.shape == (0,) and epsilon.shape == (0,)
