"""Quantity names on a collection header, projected onto the columns a frame uses.

A collection states ``length`` and ``energy``. A manifest states the columns
those quantities land on (``x``, ``pe``). Both collection datasets share this
projection. The datasets themselves do not share a base class.
"""

from __future__ import annotations

_QUANTITY_TARGETS: dict[str, tuple[str, ...]] = {
    "length": ("x", "y", "z"),
    "energy": ("pe", "ke", "etotal"),
    "force": ("fx", "fy", "fz"),
    "charge": ("charge", "total_charge"),
    "mass": ("mass",),
    "time": ("time",),
}


def target_units(units: dict[str, str]) -> dict[str, str]:
    """Column -> unit, from a collection's quantity -> unit map."""
    return {
        target: unit
        for quantity, unit in units.items()
        for target in _QUANTITY_TARGETS.get(quantity, (quantity,))
    }
