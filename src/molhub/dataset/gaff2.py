"""The GAFF2 Lennard-Jones well per atom type, from molhub's shipped table.

The table is ``molhub/data/gaff2_lj.json``: the ``MOD4 RE`` section of
AmberTools25 ``dat/leap/parm/gaff2.dat`` (GAFF 2.2.30, Oct 2025), one
``type: [R*, epsilon]`` row per atom type, ``R*`` in angstrom and ``epsilon``
in kcal/mol, with its provenance in the file's header.

Reference:
    Wang et al. "Development and testing of a general amber force field"
    J. Comput. Chem. 25, 1157 (2004). https://doi.org/10.1002/jcc.20035
    He et al. "A fast and high-quality charge model for the next generation
    general AMBER force field" J. Chem. Phys. 153, 114502 (2020).
    https://doi.org/10.1063/5.0019056
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib import resources

import numpy as np

__all__ = ["Gaff2LennardJones"]


class Gaff2LennardJones:
    """Per-type Lennard-Jones ``(sigma, epsilon)`` from the shipped GAFF2 table.

    AMBER tabulates the well as ``R*`` (half the minimum-energy separation)
    and ``epsilon``; this type answers in ``sigma`` — the zero crossing,
    ``sigma = 2 R* / 2**(1/6)`` — so a consumer gets the ``4 eps [(s/r)^12 -
    (s/r)^6]`` form directly. Units are the table's: angstrom and kcal/mol.

    Antechamber labels an atom no rule matches ``"DU"``; the table has no
    such row, so :meth:`sigma_epsilon` reports it as ``NaN``, never as zero.
    """

    #: The asset, relative to the ``molhub`` package.
    RESOURCE = ("data", "gaff2_lj.json")
    #: Antechamber's catch-all label for an atom no rule matched.
    UNTYPED = "DU"

    def __init__(self) -> None:
        text = resources.files("molhub").joinpath(*self.RESOURCE).read_text(encoding="utf-8")
        table = json.loads(text)
        self.provenance: dict[str, object] = dict(table["provenance"])
        self.units: dict[str, str] = {
            "sigma": table["units"]["rstar"],
            "epsilon": table["units"]["epsilon"],
        }
        self._rows: dict[str, tuple[float, float]] = {
            name: (float(rstar), float(epsilon))
            for name, (rstar, epsilon) in table["types"].items()
        }

    def __len__(self) -> int:
        return len(self._rows)

    def __contains__(self, type_name: object) -> bool:
        return type_name in self._rows

    def types(self) -> tuple[str, ...]:
        """Every atom type the table has a row for, in table order."""
        return tuple(self._rows)

    def sigma(self, type_name: str) -> float:
        """The zero crossing ``sigma = 2 R* / 2**(1/6)`` of *type_name*, in angstrom.

        Raises:
            KeyError: *type_name* has no row — including ``"DU"``.
        """
        rstar, _ = self._row(type_name)
        return 2.0 * rstar / 2.0 ** (1.0 / 6.0)

    def epsilon(self, type_name: str) -> float:
        """The well depth of *type_name*, in kcal/mol.

        Raises:
            KeyError: *type_name* has no row — including ``"DU"``.
        """
        return self._row(type_name)[1]

    def sigma_epsilon(self, types: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
        """``(sigma, epsilon)`` for every label in *types*, ``NaN`` where the table has none.

        Args:
            types: Atom-type labels, one per atom.

        Returns:
            Two ``float64`` arrays of ``len(types)``; an unknown label or ``"DU"``
            gives ``NaN`` in both, so a missing prior cannot read as a zero one.
        """
        sigma = np.full(len(types), np.nan, dtype=np.float64)
        epsilon = np.full(len(types), np.nan, dtype=np.float64)
        for index, name in enumerate(types):
            row = self._rows.get(str(name))
            if row is not None:
                sigma[index] = 2.0 * row[0] / 2.0 ** (1.0 / 6.0)
                epsilon[index] = row[1]
        return sigma, epsilon

    def _row(self, type_name: str) -> tuple[float, float]:
        try:
            return self._rows[type_name]
        except KeyError:
            raise KeyError(f"GAFF2 has no Lennard-Jones row for atom type {type_name!r}") from None
