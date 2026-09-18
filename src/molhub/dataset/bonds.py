"""Covalent bonds from geometry, for datasets that publish none.

A distance criterion against covalent-radius sums. It is not chemistry: it
knows nothing about bond order, resonance, or which of two near-degenerate
contacts is the real bond, and it decides by a hard cut, so a structure that
sits either side of that cut gets a different topology — and with a bond go
its angles, its torsions, and possibly an improper. The cut is at about
**+19 % of equilibrium bond length** for every common organic bond, which
non-equilibrium sampling reaches routinely.

Use it where a dataset gives geometry and nothing else, and prefer published
connectivity (SMILES, a connection table, an SDF) wherever one exists.

Nothing here is specific to any dataset; it lived in ``omol25`` only because
that is where it was first needed.
"""

from __future__ import annotations

import numpy as np
from molpy import Element

__all__ = ["BondMargins", "infer_bonds"]

_BOND_SCALE = 1.2
_MIN_BOND = 0.4
_MAX_Z = 118
# Pairwise geometry is computed in row blocks of this size so bond inference
# never materialises a full (N, N, 3) tensor for large frames.
_PAIR_BLOCK = 512

_SYMBOLS: np.ndarray | None = None
_COVALENT: np.ndarray | None = None


def _element_tables() -> tuple[np.ndarray, np.ndarray]:
    """Symbols and covalent radii (Å) indexed by Z, built once per process.

    Replaces per-atom ``Element(z)`` construction on the frame-decode hot
    path with two vectorised table lookups.
    """
    global _SYMBOLS, _COVALENT
    if _SYMBOLS is None or _COVALENT is None:
        symbols = np.empty(_MAX_Z + 1, dtype="U3")
        radii = np.zeros(_MAX_Z + 1, dtype=np.float64)
        symbols[0] = ""
        for z in range(1, _MAX_Z + 1):
            element = Element(z)
            symbols[z] = element.symbol
            radii[z] = float(element.covalent)
        _SYMBOLS, _COVALENT = symbols, radii
    return _SYMBOLS, _COVALENT


def _checked_numbers(numbers: np.ndarray) -> np.ndarray:
    numbers = np.asarray(numbers, dtype=np.int64).reshape(-1)
    if numbers.size and (int(numbers.min()) < 1 or int(numbers.max()) > _MAX_Z):
        raise ValueError(
            f"atomic numbers outside 1..{_MAX_Z}: min={int(numbers.min())} max={int(numbers.max())}"
        )
    return numbers


def infer_bonds(numbers: np.ndarray, pos: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Covalent bonds from pairwise distances against covalent-radius sums.

    A pair ``i < j`` is bonded when
    ``_MIN_BOND ≤ |r_j − r_i| ≤ _BOND_SCALE · (R_i + R_j)`` with ``R`` the
    covalent radius. Fully vectorised; rows are processed in blocks so large
    frames never allocate a full ``(N, N, 3)`` displacement tensor.

    Args:
        numbers: Atomic numbers ``(N,)``.
        pos: Positions ``(N, 3)`` in Å.

    Returns:
        ``(atomi, atomj)`` int64 arrays of upper-triangle bonded pairs,
        ordered by ``atomi`` then ``atomj``.
    """
    numbers = _checked_numbers(numbers)
    pos = np.asarray(pos, dtype=np.float64)
    _, radii = _element_tables()
    r = radii[numbers]
    n = int(numbers.shape[0])
    atomi_parts: list[np.ndarray] = []
    atomj_parts: list[np.ndarray] = []
    min_sq = _MIN_BOND * _MIN_BOND
    for start in range(0, n, _PAIR_BLOCK):
        stop = min(start + _PAIR_BLOCK, n)
        diff = pos[start:stop, None, :] - pos[None, :, :]
        # Both bounds are positive, so squared distances decide bonding
        # without a square root over the full pair matrix.
        dist_sq = np.einsum("ijk,ijk->ij", diff, diff)
        limit = _BOND_SCALE * (r[start:stop, None] + r[None, :])
        hit = (dist_sq >= min_sq) & (dist_sq <= limit * limit)
        # Upper triangle only: column index must exceed the global row index.
        cols = np.arange(n)[None, :]
        rows = np.arange(start, stop)[:, None]
        hit &= cols > rows
        i_local, j = np.nonzero(hit)
        atomi_parts.append(i_local + start)
        atomj_parts.append(j)
    if not atomi_parts:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty.copy()
    return (
        np.concatenate(atomi_parts).astype(np.int64),
        np.concatenate(atomj_parts).astype(np.int64),
    )


class BondMargins:
    """How close one structure sits to the bond / no-bond decision.

    :func:`infer_bonds` decides by a hard cut at ``_BOND_SCALE · (R_i + R_j)``,
    which for every common organic bond is about **+19 % of equilibrium
    length**. A relaxed geometry sits far inside it; a non-equilibrium one can
    sit either side, and which side decides whether a bond exists — and with
    it three angles, some torsions, and possibly an improper that the relaxed
    molecule does not have.

    Nothing warns when that happens. The topology is simply different, and the
    energy computed from it is simply wrong, in a way that still looks like a
    plausible number. This class makes the distance to that decision a
    measurement, so a dataset's exposure to it can be reported instead of
    assumed.

    It judges nothing: a structure close to the cut may be perfectly fine.
    What it says is how much of the result rests on the cut's exact value.

    Args:
        numbers: Atomic numbers ``(N,)``.
        pos: Positions ``(N, 3)`` in Å.
        band: Relative half-width around the cut that counts as close, as a
            fraction of the cut. ``0.1`` reads "within 10 % of the threshold".

    Example::

        margins = BondMargins(numbers, positions)
        if margins.n_in_band:
            print(f"{margins.n_in_band} pairs within 10% of the bond cut")
    """

    def __init__(self, numbers: np.ndarray, pos: np.ndarray, *, band: float = 0.1) -> None:
        numbers = _checked_numbers(numbers)
        pos = np.asarray(pos, dtype=np.float64)
        if not (0.0 < float(band) < 1.0):
            raise ValueError(f"band must lie in (0, 1), got {band!r}")
        self.band = float(band)
        _, radii = _element_tables()
        r = radii[numbers]
        n = int(numbers.shape[0])
        rows, cols = np.triu_indices(n, k=1)
        if rows.size == 0:
            self._ratio = np.empty(0, dtype=np.float64)
        else:
            diff = pos[rows] - pos[cols]
            dist = np.sqrt(np.einsum("ij,ij->i", diff, diff))
            cut = _BOND_SCALE * (r[rows] + r[cols])
            # The ratio, not the distance: one number comparable across
            # element pairs, where 1.0 is exactly the decision.
            self._ratio = dist / cut
        self._bonded = (self._ratio <= 1.0) & (self._ratio >= _MIN_BOND / _BOND_SCALE)

    @property
    def farthest_bond(self) -> float:
        """Largest ``r / cut`` among pairs judged **bonded**; ``nan`` if none.

        Approaching 1 means a bond that a slightly tighter criterion would
        have dropped.
        """
        kept = self._ratio[self._bonded]
        return float(kept.max()) if kept.size else float("nan")

    @property
    def closest_nonbond(self) -> float:
        """Smallest ``r / cut`` above 1 among pairs judged **not** bonded.

        Approaching 1 from above means a contact that a slightly looser
        criterion would have called a bond — a stretched bond, most often.
        """
        rest = self._ratio[self._ratio > 1.0]
        return float(rest.min()) if rest.size else float("nan")

    @property
    def n_in_band(self) -> int:
        """Pairs whose ``r / cut`` lies within :attr:`band` of the decision."""
        if self._ratio.size == 0:
            return 0
        return int(np.count_nonzero(np.abs(self._ratio - 1.0) <= self.band))

    def __repr__(self) -> str:
        return (
            f"BondMargins(farthest_bond={self.farthest_bond:.3f}, "
            f"closest_nonbond={self.closest_nonbond:.3f}, "
            f"n_in_band={self.n_in_band}, band={self.band})"
        )
