"""Prepare-stage transforms: atomic baselines, unit rescaling, constant labels.

These three carry the numerical content of the deleted molnex task tree
(``src/molix/data/tasks/{dress,unit,constant}.py``, molnex commit ``6d425f7^``),
re-expressed on MolHub's sample shape: a :class:`molpy.Frame` whose graph-level
targets live in ``frame.meta`` and whose per-atom data lives in the ``atoms``
block. The numbers are unchanged; only the container is.

They are three independent types, not three subclasses of a task base. MolHub
has no ``Task`` / ``SampleTask`` hierarchy and does not acquire one here: what
a caller needs from any of them is one verb, :meth:`execute`, taking a sample
and returning a new one. Ordering, caching and cache identity belong to the
conveyor (``streaming-data-tiers-03``), not to the transform.

Every :meth:`execute` is pure: the input sample is never mutated, so a
transform can be applied to a cached frame without corrupting the cache.

Example::

    from molhub.dataset.transforms import AtomicDress, ConstantLabel, UnitConvert

    convert = UnitConvert({"U0": ("hartree", "eV")})
    dress = AtomicDress(elements=(1, 6, 7, 8), target_key="U0")
    dress.fit([convert.execute(frame) for frame in train_frames])

    prepared = ConstantLabel(key="total_charge", value=0.0).execute(
        dress.execute(convert.execute(frame))
    )
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

import numpy as np
from molpy import Frame
from molpy.core import UnitRegistry

__all__ = ["AtomicDress", "UnitConvert", "ConstantLabel"]

MetaScalar = bool | int | float | str
"""What a graph-level target may be — the scalar types a transform produces.

molpy's own metadata is wider: it also admits fixed-length sequences. No
dataset target is one, so this union stays the documented contract for the
values these transforms compute and write.
"""

_MetaValue = MetaScalar | list[bool | int | float]
"""Anything ``Frame.meta`` can hand back, including molpy's fixed-length
sequences. Read paths carry values through untouched, so they must admit a
value these transforms would never compute themselves."""


def _read_targets(sample: Frame) -> dict[str, _MetaValue]:
    """Graph-level targets of *sample*, as plain Python values.

    The result is detached from the frame: ``Frame.meta`` hands back a copy of
    ``MetaValue`` wrappers, and a transform must not write back through the
    sample it reads. Unwrap here so every consumer sees the plain scalar /
    sequence it computes with.
    """
    return {key: getattr(value, "value", value) for key, value in sample.meta.items()}


def _require_number(targets: Mapping[str, _MetaValue], key: str, owner: str) -> float:
    """Return *key*'s value as a float, refusing a target these cannot rescale.

    Raises:
        KeyError: *targets* does not carry *key*.
        TypeError: *key* holds one of molpy's fixed-length sequences, which is
            metadata but not a scalar target.
    """
    if key not in targets:
        raise KeyError(f"{owner}: sample carries no target {key!r}; present: {sorted(targets)}")
    value = targets[key]
    if isinstance(value, list):
        raise TypeError(f"{owner}: target {key!r} is a sequence, not a scalar: {value!r}")
    return float(value)


def _with_targets(sample: Frame, targets: Mapping[str, _MetaValue]) -> Frame:
    """Return a copy of *sample* whose graph-level targets are *targets*.

    The copy is what keeps :meth:`execute` pure; ``Frame.meta`` is replaced
    wholesale on the copy, so the caller's frame is untouched.
    """
    updated = sample.copy()
    updated.meta = dict(targets)
    return updated


class AtomicDress:
    """Subtract an element-dependent baseline from a scalar graph-level target.

    Two-phase, because the baseline is a property of the training set and not
    of any one sample: :meth:`fit` solves for the per-element energies over a
    whole set, then :meth:`execute` subtracts each sample's baseline. An
    unfitted dress refuses to execute rather than silently subtracting zeros.

    :meth:`fit` builds a count matrix — one row per sample, one column per
    element of :attr:`elements`, entries being how many atoms of that element
    the sample holds — and solves ``counts @ beta ~= target`` by least squares
    (:func:`numpy.linalg.lstsq`). ``beta`` is the per-element baseline.

    Args:
        elements: Atomic numbers the fit solves for, in column order. Elements
            absent from the fitted set contribute nothing to a baseline.
        target_key: Graph-level target to dress (e.g. ``"U0"``).
        output_key: Where the dressed value is written. Defaults to
            *target_key*, i.e. dressing in place on the returned copy.
    """

    def __init__(
        self,
        *,
        elements: Iterable[int],
        target_key: str = "U0",
        output_key: str | None = None,
    ) -> None:
        self.elements: tuple[int, ...] = tuple(int(element) for element in elements)
        self.target_key = target_key
        self.output_key = target_key if output_key is None else output_key
        self.atomic_energies: dict[int, float] = {}

    def fit(self, samples: Iterable[Frame]) -> None:
        """Fit per-element baselines by least squares over *samples*.

        Args:
            samples: Training frames, each with an ``atoms`` block holding
                ``number`` and a graph-level :attr:`target_key`.

        Raises:
            KeyError: A sample does not carry :attr:`target_key`.
        """
        rows: list[list[float]] = []
        values: list[float] = []
        for sample in samples:
            numbers = np.asarray(sample["atoms"]["number"])
            rows.append([float((numbers == element).sum()) for element in self.elements])
            targets = _read_targets(sample)
            values.append(_require_number(targets, self.target_key, "AtomicDress.fit"))

        counts = np.asarray(rows, dtype=np.float64)
        target = np.asarray(values, dtype=np.float64)
        baseline, *_ = np.linalg.lstsq(counts, target, rcond=None)
        self.atomic_energies = {
            element: float(baseline[column]) for column, element in enumerate(self.elements)
        }

    def execute(self, sample: Frame) -> Frame:
        """Return a copy of *sample* with the fitted baseline subtracted.

        Args:
            sample: A frame with an ``atoms`` block holding ``number`` and a
                graph-level :attr:`target_key`.

        Returns:
            A new :class:`molpy.Frame`; ``meta[output_key]`` is
            ``target - baseline`` and every other target is carried over.

        Raises:
            RuntimeError: :meth:`fit` (or :meth:`load_state_dict`) has not run.
            KeyError: *sample* does not carry :attr:`target_key`.
        """
        if not self.atomic_energies:
            raise RuntimeError(
                "AtomicDress: fit() must run before execute(); an unfitted dress "
                "would silently subtract a zero baseline."
            )
        targets = _read_targets(sample)
        value = _require_number(targets, self.target_key, "AtomicDress.execute")
        numbers = np.asarray(sample["atoms"]["number"])
        baseline = sum(self.atomic_energies.get(int(number), 0.0) for number in numbers)
        targets[self.output_key] = value - baseline
        return _with_targets(sample, targets)

    def state_dict(self) -> dict[str, np.ndarray]:
        """Serialise the fitted baseline.

        Returns:
            ``{"elements": (n,) int64, "energies": (n,) float64}`` with the
            elements ascending and the energies aligned to them.
        """
        elements = sorted(self.atomic_energies)
        return {
            "elements": np.asarray(elements, dtype=np.int64),
            "energies": np.asarray(
                [self.atomic_energies[element] for element in elements], dtype=np.float64
            ),
        }

    def load_state_dict(self, state: Mapping[str, np.ndarray]) -> None:
        """Restore a baseline produced by :meth:`state_dict`.

        Args:
            state: Aligned ``"elements"`` / ``"energies"`` arrays.
        """
        elements = np.asarray(state["elements"]).tolist()
        energies = np.asarray(state["energies"]).tolist()
        self.atomic_energies = {
            int(element): float(energy) for element, energy in zip(elements, energies)
        }


class UnitConvert:
    """Rescale graph-level targets between explicitly named units.

    Each field declares the unit it *is in* and the unit it should be *in*.
    There are no preset bundles: whatever the caller types is what they get,
    which is the only form that survives a dataset changing its convention.
    Factors resolve once against the shared molpy registry, so the per-sample
    cost is one multiply per field.

    Args:
        conversions: ``{target_key: (source_unit, target_unit)}``. Units are
            whatever the molpy registry parses (``"hartree"``, ``"eV"``,
            ``"hartree / bohr"``, …).

    Raises:
        ValueError: *conversions* is empty, a value is not a 2-tuple, or a
            resolved factor is not finite.
        molpy.core.UnitsError: A unit is unknown, or the pair is dimensionally
            incompatible.
    """

    def __init__(self, conversions: Mapping[str, tuple[str, str]]) -> None:
        if not conversions:
            raise ValueError("UnitConvert needs at least one field to convert.")
        registry = UnitRegistry()
        factors: dict[str, float] = {}
        for key, pair in conversions.items():
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError(
                    f"UnitConvert: value for {key!r} must be a 2-tuple "
                    f"(source_unit, target_unit), got {pair!r}."
                )
            source, target = pair
            factor = float(registry.factor(source, target))
            if not math.isfinite(factor):
                raise ValueError(
                    f"UnitConvert: non-finite factor for {key!r} ({source} -> {target})."
                )
            factors[str(key)] = factor
        self.factors: dict[str, float] = factors

    def execute(self, sample: Frame) -> Frame:
        """Return a copy of *sample* with every configured target rescaled.

        Args:
            sample: A frame carrying each configured target.

        Returns:
            A new :class:`molpy.Frame`; unconfigured targets pass through.

        Raises:
            KeyError: A configured target is absent from *sample*.
        """
        targets = _read_targets(sample)
        for key, factor in self.factors.items():
            targets[key] = _require_number(targets, key, "UnitConvert.execute") * factor
        return _with_targets(sample, targets)


class ConstantLabel:
    """Write a constant scalar as a graph-level target.

    For a dataset whose every sample shares a value the consumer requires but
    the source never recorded — the canonical case being a uniformly neutral
    molecular set fed to a model that fail-fasts on a missing
    ``total_charge``. Making the constant explicit is what keeps that model's
    fail-fast honest.

    Args:
        key: Target name to write.
        value: The constant, stored as a float.

    Raises:
        ValueError: *key* is empty.
    """

    def __init__(self, *, key: str, value: float) -> None:
        if not key:
            raise ValueError("ConstantLabel: key must be a non-empty target name.")
        self.key = key
        self.value = float(value)

    def execute(self, sample: Frame) -> Frame:
        """Return a copy of *sample* carrying the constant target.

        Args:
            sample: Any frame; its ``atoms`` block is carried over untouched.

        Returns:
            A new :class:`molpy.Frame` whose ``meta[key]`` is :attr:`value`,
            overwriting an existing target of that name.
        """
        targets = _read_targets(sample)
        targets[self.key] = self.value
        return _with_targets(sample, targets)
