#!/usr/bin/env python
"""Regression: MolHub's reception of the deleted MolNex ETL layer.

Exercises the public reception surface of
``molix-data-dissolution-05-molhub-reception`` end to end and offline:

1. :class:`~molhub.dataset.water_les.WaterLESDataset` over a synthetic
   extended-XYZ fixture this script writes itself, retrieved both from disk and
   through a fake :class:`~molhub.dataset.hub.ArtifactHub`.
2. :class:`~molhub.dataset.molrec.MolRecDataset` record → sample mapping,
   per-instance target schema, teacher isolation and ``source_id``.
3. :class:`~molhub.dataset.transforms.AtomicDress` /
   :class:`~molhub.dataset.transforms.UnitConvert` /
   :class:`~molhub.dataset.transforms.ConstantLabel` numerics.
4. :class:`~molhub.dataset.neighbor.NeighborDelegate` pass-through — the cutoff
   graph is molnex's contract, so the goldens are reproduced here without
   importing molnex; an optional ``MOLNEX_SRC``-gated leg checks the real
   ``molix.batch.NeighborList`` against the same literals.

Every fixture lives in a temporary directory created by this script. Nothing
resolves a registry, opens a socket, or runs a third-party oracle at run time;
every expected value below is a literal.

Provenance of externally derived literals (no tool runs here):

* ``_GOLDEN_EDGE_*`` / ``_GOLDEN_*TASK_ID`` — molnex ``molix.batch.NeighborList``
  (branch ``feat/mm-param-val``), torch 2.12.1+cpu, Python 3.14;
  command ``NeighborList(cutoff=2.0).execute({"Z": tensor([1, 1, 1]),
  "pos": tensor(_CHAIN_POS)})``; 2026-08-14.
* ``_BASELINES`` / ``_RESIDUALS`` / ``_RESIDUAL_SS`` — hand-derived from the
  3×3 normal equations of the fixture below, verified against
  ``numpy.linalg.lstsq`` (numpy 2.5.1); 2026-08-14.
* ``_HARTREE_TO_EV`` etc. — CODATA 2018 (NIST), as pinned by the deleted molnex
  ``tests/test_molix/test_datasets/test_units_contract.py`` (molnex commit
  ``6d425f7^``); verified against molpy's ``UnitSystem`` registry via
  ``(1.0 * u.Unit("hartree")).to(u.Unit("eV")).magnitude``; 2026-08-14.

tool: python
command: python regressions/molix-data-dissolution-05-molhub-reception.py
date: 2026-08-14
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from molpy import Block, Box, Frame, MolRec, Trajectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from molhub.dataset import (  # noqa: E402
    ArtifactHub,
    AtomicDress,
    ConstantLabel,
    Dataset,
    MolRecDataset,
    NeighborDelegate,
    UnitConvert,
    WaterLESDataset,
)
from molhub.dataset.water_les import COORDINATE  # noqa: E402

# ---------------------------------------------------------------------------
# Tolerances (molnex FP contract: energy 1e-10 exact / 1e-6 numerical,
# force 1e-8, position 1e-12)
# ---------------------------------------------------------------------------

_ENERGY_TEXT_ATOL = 1e-6  # energies that round-trip through 6-decimal text
_ENERGY_EXACT_ATOL = 1e-10  # energies that round-trip in binary
_FORCE_ATOL = 1e-8
_POS_ATOL = 1e-12

# ---------------------------------------------------------------------------
# WaterLES fixture — the deleted molnex conftest writer, made RNG-free
# ---------------------------------------------------------------------------

_EDGE = 12.0  # cubic cell edge, Å
_E0_PER_ATOM_EV = -10.0  # RPBE-D3 bulk water sits near -10 eV/atom
_H_OFFSETS = ((0.75, 0.5, 0.0), (0.75, -0.5, 0.0))  # Å, binary-exact
_N_TRAIN_FRAMES = 40  # smallest count with a clean 0.95/0.05 slice: 38/2
_N_TEST_FRAMES = 2

_WATER_Z = [8, 1, 1, 8, 1, 1]
_WATER_CELL = np.eye(3) * 12.0
_FIRST_OXYGEN = (4.0, 6.0, 6.0)
_FIRST_HYDROGEN = (4.75, 6.5, 6.0)
_FIRST_FORCE = (-0.5, -0.5, -0.5)
_VAL_ENERGIES = (-63.8, -63.9)  # tail frames 38, 39 of E(i) = -60.0 - 0.1 i
_TEST_ENERGIES = (-60.0, -60.1)
_TRAIN_LEN, _VAL_LEN = 38, 2
_WATER_SOURCE_ID = "dataset:molcrafts/water-les@1#split=train"

# ---------------------------------------------------------------------------
# MolRec fixture — two teachers over one 3-atom, 4-frame record
# ---------------------------------------------------------------------------

_DIMER_ELEMENTS = ("H", "H", "O")
_DIMER_Z = [1, 1, 8]
_DIMER_POS = np.array([[0.0, 0.0, 0.0], [0.75, 0.5, 0.0], [-0.75, 0.5, 0.0]])
_BOX_EDGE = 20.0
_N_RECORD_FRAMES = 4

#: The record is *written* from these rules and *asserted* against the literal
#: tuples below, so a broken record → sample mapping cannot hide behind a
#: fixture that echoes its own inputs. Every value is binary-exact.
#:   energy_A(f) = -10.0 + 1.5 f      energy_B(f) = 3.5 - 2.25 f
#:   force_A(f, a, c) = 0.25 f + 0.5 a + 0.125 c
_EXPECTED_ENERGY_A = (-10.0, -8.5, -7.0, -5.5)
_EXPECTED_ENERGY_B = (3.5, 1.25, -1.0, -3.25)
#: ``(n_frames, n_atoms, 3)``.
_EXPECTED_FORCES_A = np.array(
    [
        [[0.0, 0.125, 0.25], [0.5, 0.625, 0.75], [1.0, 1.125, 1.25]],
        [[0.25, 0.375, 0.5], [0.75, 0.875, 1.0], [1.25, 1.375, 1.5]],
        [[0.5, 0.625, 0.75], [1.0, 1.125, 1.25], [1.5, 1.625, 1.75]],
        [[0.75, 0.875, 1.0], [1.25, 1.375, 1.5], [1.75, 1.875, 2.0]],
    ]
)
_MOLREC_SOURCE_ID = "molrec:force_rec#teacher=teacherA"
_MOLREC_SUBSET_SOURCE_ID = "molrec:force_rec#teacher=teacherA,total=2"

# ---------------------------------------------------------------------------
# Transform goldens
# ---------------------------------------------------------------------------

#: Least-squares baselines of the overdetermined 4-sample fixture, per element.
#: The duplicated H2O row (targets -9.0 and -8.6) makes the exact solution of
#:     2h + o = -8.8, 4h + c = -6.0, c + 2o = -20.0
#: the fit, so the numbers are derived rather than observed.
_BASELINES = {1: -0.45, 6: -4.2, 8: -7.9}
_RESIDUALS = (-0.2, 0.0, 0.0, 0.2)
_RESIDUAL_SS = 0.08  # d^2 / 2 with d = 0.4 eV

_HARTREE_TO_EV = 27.211386245988
_HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM = 51.42208619
_BOHR_TO_ANGSTROM = 0.529177210903

# ---------------------------------------------------------------------------
# Neighbour goldens — the 3-atom chain (see module docstring for provenance)
# ---------------------------------------------------------------------------

_CHAIN_POS = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.5, 0.0, 0.0))
_CHAIN_Z = (1, 1, 1)
_CUTOFF = 2.0

#: ``symmetry=True``: the kernel's two half-pairs, then their reverses, so
#: ``E = 2 n_pairs`` and the reversed block carries the sign-flipped
#: displacement. ``edge_index[:, 0]`` is the source and
#: ``edge_diff = pos[target] - pos[source]`` (molnex edge convention).
_GOLDEN_EDGE_INDEX = ((1, 0), (2, 1), (0, 1), (1, 2))
_GOLDEN_EDGE_DIFF = ((-1.0, 0.0, 0.0), (-1.5, 0.0, 0.0), (1.0, 0.0, 0.0), (1.5, 0.0, 0.0))
_GOLDEN_EDGE_DIST = (1.0, 1.5, 1.0, 1.5)
_GOLDEN_TASK_ID = "nlist:cut=2.0:max=512:pbc=False:sym=True"
_GOLDEN_HALF_EDGE_INDEX = ((1, 0), (2, 1))
_GOLDEN_HALF_TASK_ID = "nlist:cut=2.0:max=512:pbc=False:sym=False"


# ---------------------------------------------------------------------------
# Fixture writers
# ---------------------------------------------------------------------------


def _force_row(atom: int, frame: int) -> tuple[float, float, float]:
    """Deterministic force components in ``[-0.5, 0.5]`` eV·Å⁻¹."""
    return (
        0.25 * ((atom + frame) % 5) - 0.5,
        0.25 * ((atom + 2 * frame) % 5) - 0.5,
        0.25 * ((atom + 3 * frame) % 5) - 0.5,
    )


def _water_frame(*, frame: int, n_water: int = 2) -> str:
    """One extended-XYZ frame of *n_water* H2O molecules (O, H, H per water)."""
    spacing = _EDGE / (n_water + 1)
    rows: list[str] = []
    atom = 0
    for water in range(n_water):
        ox, oy, oz = (water + 1) * spacing, _EDGE / 2.0, _EDGE / 2.0
        for symbol, (dx, dy, dz) in (("O", (0.0, 0.0, 0.0)), *zip("HH", _H_OFFSETS)):
            x, y, z = ox + dx, oy + dy, oz + dz
            fx, fy, fz = _force_row(atom, frame)
            rows.append(f"{symbol}  {x:.6f} {y:.6f} {z:.6f}  {fx:.6f} {fy:.6f} {fz:.6f}")
            atom += 1

    lattice = f'"{_EDGE:.6f} 0.0 0.0 0.0 {_EDGE:.6f} 0.0 0.0 0.0 {_EDGE:.6f}"'
    properties = "species:S:1:pos:R:3:forces:R:3"
    energy = 3 * n_water * _E0_PER_ATOM_EV - 0.1 * frame
    comment = f'Lattice={lattice} Properties={properties} energy={energy:.6f} pbc="T T T"'
    return "\n".join([str(3 * n_water), comment, *rows]) + "\n"


def _write_water_root(root: Path) -> None:
    """Write a 40-frame train pool and a 2-frame test file under *root*."""
    root.mkdir(parents=True, exist_ok=True)
    (root / WaterLESDataset.TRAIN_FILE).write_text(
        "".join(_water_frame(frame=i) for i in range(_N_TRAIN_FRAMES)), encoding="utf-8"
    )
    (root / WaterLESDataset.TEST_FILE).write_text(
        "".join(_water_frame(frame=i) for i in range(_N_TEST_FRAMES)), encoding="utf-8"
    )


class FakeHub:
    """An :class:`~molhub.dataset.hub.ArtifactHub` serving files already on disk.

    Records what was asked for, so the retrieval seam runs with no registry, no
    driver and no network.
    """

    def __init__(self, paths: dict[str, Path]) -> None:
        self._paths = paths
        self.calls: list[tuple[str, list[str] | None]] = []

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        self.calls.append((coordinate, roles))
        wanted = list(self._paths) if roles is None else roles
        return {role: self._paths[role] for role in wanted}


def _molrec_frame(elements: tuple[str, ...], xyz: np.ndarray) -> Frame:
    frame = Frame()
    block = Block()
    block.insert("element", np.array(elements, dtype=np.str_))
    block.insert("x", np.ascontiguousarray(xyz[:, 0], dtype=np.float64))
    block.insert("y", np.ascontiguousarray(xyz[:, 1], dtype=np.float64))
    block.insert("z", np.ascontiguousarray(xyz[:, 2], dtype=np.float64))
    frame["atoms"] = block
    frame.box = Box(np.eye(3) * _BOX_EDGE)
    return frame


def _write_force_record(path: Path) -> None:
    """Write the 4-frame, two-teacher record; forces on ``teacherA`` only.

    Built from the arithmetic rules documented beside
    :data:`_EXPECTED_ENERGY_A` — never from the expected literals themselves.
    """
    n_frames, n_atoms = _N_RECORD_FRAMES, len(_DIMER_Z)
    frames = [_molrec_frame(_DIMER_ELEMENTS, _DIMER_POS + 0.25 * i) for i in range(n_frames)]
    energy_a = np.array([-10.0 + 1.5 * f for f in range(n_frames)], dtype=np.float64)
    energy_b = np.array([3.5 - 2.25 * f for f in range(n_frames)], dtype=np.float64)
    forces_a = np.array(
        [
            [[0.25 * f + 0.5 * a + 0.125 * c for c in range(3)] for a in range(n_atoms)]
            for f in range(n_frames)
        ],
        dtype=np.float64,
    )

    record = MolRec()
    record.set_trajectory(Trajectory.from_frames(frames))
    record.set_system(frames[0])
    for key, values in (("teacherA.energy", energy_a), ("teacherB.energy", energy_b)):
        record.observables.add_scalar(
            key,
            values,
            unit="eV",
            axes=["timestep"],
            time_dependent=True,
            domain="trajectory",
        )
    record.observables.add_vector(
        "teacherA.forces",
        forces_a,
        unit="eV/Angstrom",
        axes=["timestep", "atom", "component"],
        time_dependent=True,
        domain="trajectory",
    )
    record.method = {
        "teacherA": {"theory_level": "DFT/PBE", "model_id": "toyA"},
        "teacherB": {"theory_level": "DFT/B3LYP", "model_id": "toyB"},
    }
    record.write_zarr(str(path))


def _dress_sample(numbers: list[int], targets: dict[str, float]) -> Frame:
    """One transform sample: atomic numbers plus graph-level targets."""
    frame = Frame()
    block = Block()
    block["number"] = np.array(numbers, dtype=np.int64)
    frame["atoms"] = block
    frame.meta.update(targets)
    return frame


def _dress_samples() -> list[Frame]:
    """The overdetermined 4-sample, 3-element fixture (H2O, CH4, CO2, H2O')."""
    return [
        _dress_sample([1, 1, 8], {"U0": -9.0}),
        _dress_sample([6, 1, 1, 1, 1], {"U0": -6.0}),
        _dress_sample([6, 8, 8], {"U0": -20.0}),
        _dress_sample([1, 1, 8], {"U0": -8.6}),
    ]


class GoldenNeighborList:
    """Stands in for ``molix.batch.NeighborList`` at the delegate's one seam.

    Returns the hard-coded goldens recorded offline from that class (see the
    module docstring), so the cutoff-graph contract is reproduced here without
    torch, molnex, or any live oracle. Mirrors the structural contract molnex
    documents — a ``task_id`` and an ``execute`` — and nothing else.
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.calls: list[dict[str, object]] = []
        self.returned: dict[str, object] = {}

    def execute(self, data: dict[str, object]) -> dict[str, object]:
        self.calls.append(data)
        self.returned = {
            **data,
            "edge_index": _GOLDEN_EDGE_INDEX,
            "edge_diff": _GOLDEN_EDGE_DIFF,
            "edge_dist": _GOLDEN_EDGE_DIST,
        }
        return self.returned


# ---------------------------------------------------------------------------
# Leg 1 — WaterLES
# ---------------------------------------------------------------------------


def check_water_les(root: Path, empty_root: Path) -> None:
    """Parsing, cell, deterministic tail split, units, identity, retrieval."""
    assert isinstance(FakeHub({}), ArtifactHub), "the fake drifted from the hub protocol"

    test_split = WaterLESDataset(root, split="test").load()
    assert isinstance(test_split, Dataset)
    assert len(test_split) == _N_TEST_FRAMES
    first = test_split[0]
    assert isinstance(first, Frame)

    atoms = first["atoms"]
    assert atoms.nrows == 6
    for column in ("element", "x", "y", "z", "number", "fx", "fy", "fz"):
        assert column in atoms, f"WaterLES atoms block lacks {column!r}"
    assert list(atoms["number"]) == _WATER_Z
    for axis, want in zip(("x", "y", "z"), _FIRST_OXYGEN):
        assert abs(float(atoms[axis][0]) - want) <= _POS_ATOL
    for axis, want in zip(("x", "y", "z"), _FIRST_HYDROGEN):
        assert abs(float(atoms[axis][1]) - want) <= _POS_ATOL
    for column, want in zip(("fx", "fy", "fz"), _FIRST_FORCE):
        assert abs(float(atoms[column][0]) - want) <= _FORCE_ATOL

    # Å pass through unscaled: a dropped Bohr→Å factor lands at ~6.3, an Å→nm
    # rescale at 0.12.
    assert first.box is not None
    assert np.allclose(np.asarray(first.box.matrix), _WATER_CELL, atol=_POS_ATOL)

    # eV pass through unscaled, and the split is the upstream tail slice.
    assert set(first.meta) == {"energy"}
    for index, want in enumerate(_TEST_ENERGIES):
        assert abs(float(test_split[index].meta["energy"]) - want) <= _ENERGY_TEXT_ATOL

    train = WaterLESDataset(root, split="train").load()
    val = WaterLESDataset(root, split="val").load()
    assert len(train) == _TRAIN_LEN
    assert len(val) == _VAL_LEN
    for index, want in enumerate(_VAL_ENERGIES):
        assert abs(float(val[index].meta["energy"]) - want) <= _ENERGY_TEXT_ATOL
    train_energies = {float(train[i].meta["energy"]) for i in range(len(train))}
    assert all(float(val[i].meta["energy"]) not in train_energies for i in range(len(val)))

    assert WaterLESDataset.TRAIN_VAL_RATIO == (0.95, 0.05)
    assert WaterLESDataset.TARGET_SCHEMA.graph_level == frozenset({"energy"})
    assert WaterLESDataset.TARGET_SCHEMA.atom_level == frozenset({"forces"})

    assert COORDINATE == "dataset:molcrafts/water-les@1"
    assert WaterLESDataset.manifest.canonical == COORDINATE
    source_id = WaterLESDataset(root, split="train").source_id
    assert source_id == _WATER_SOURCE_ID
    assert "size=" not in source_id and "n=" not in source_id
    assert len({WaterLESDataset(root, split=s).source_id for s in ("train", "val", "test")}) == 3

    # Retrieval seam: an absent local file is fetched by coordinate, and val
    # slices the train role rather than fetching a second one.
    hub = FakeHub({"train": root / WaterLESDataset.TRAIN_FILE})
    lazy = WaterLESDataset(empty_root, split="train", hub=hub)
    assert hub.calls == [], "constructing must not cost a download"
    assert len(lazy.load()) == _TRAIN_LEN
    assert hub.calls == [(COORDINATE, ["train"])]

    val_hub = FakeHub({"train": root / WaterLESDataset.TRAIN_FILE})
    WaterLESDataset(empty_root, split="val", hub=val_hub).load()
    assert val_hub.calls == [(COORDINATE, ["train"])]

    local_hub = FakeHub({})
    WaterLESDataset(root, split="train", hub=local_hub).load()
    assert local_hub.calls == [], "a usable local file must not be re-fetched"

    print(
        f"  WaterLES: {len(train)}/{len(val)}/{len(test_split)} frames, "
        f"val energies {_VAL_ENERGIES[0]}/{_VAL_ENERGIES[1]} eV, "
        f"Z={_WATER_Z}, cell 12.0 Å, source_id {_WATER_SOURCE_ID}"
    )


# ---------------------------------------------------------------------------
# Leg 2 — MolRec
# ---------------------------------------------------------------------------


def check_molrec(record_path: Path) -> None:
    """Record → sample mapping, per-instance schema, teacher isolation, identity."""
    teacher_a = MolRecDataset(record_path, teacher_id="teacherA")
    assert teacher_a.target_schema.graph_level == frozenset({"energy"})
    assert teacher_a.target_schema.atom_level == frozenset({"forces"})
    assert "TARGET_SCHEMA" not in vars(MolRecDataset), "the schema is per record, not per class"

    frames = teacher_a.load()
    assert isinstance(frames, Dataset)
    assert len(frames) == _N_RECORD_FRAMES
    assert isinstance(frames[0], Frame)

    atoms = frames[0]["atoms"]
    for column in ("element", "x", "y", "z", "number", "fx", "fy", "fz"):
        assert column in atoms, f"MolRec atoms block lacks {column!r}"
    assert list(atoms["number"]) == _DIMER_Z
    assert np.allclose(np.asarray(atoms["x"]), _DIMER_POS[:, 0], atol=_POS_ATOL)
    assert np.allclose(np.asarray(atoms["y"]), _DIMER_POS[:, 1], atol=_POS_ATOL)
    assert np.allclose(np.asarray(atoms["z"]), _DIMER_POS[:, 2], atol=_POS_ATOL)
    assert np.allclose(np.asarray(frames[0].box.matrix), np.eye(3) * _BOX_EDGE, atol=_POS_ATOL)

    assert set(frames[0].meta) == {"energy"}, "the teacher prefix must be stripped"
    for index, want in enumerate(_EXPECTED_ENERGY_A):
        assert abs(float(frames[index].meta["energy"]) - want) <= _ENERGY_EXACT_ATOL
        block = frames[index]["atoms"]
        for component, column in enumerate(("fx", "fy", "fz")):
            assert np.allclose(
                np.asarray(block[column]),
                _EXPECTED_FORCES_A[index, :, component],
                atol=_FORCE_ATOL,
            )

    # Teacher isolation: teacherB carries energies only, and a view of it must
    # not see teacherA's forces — a cache that confused the two would serve one
    # teacher's labels for the other.
    teacher_b = MolRecDataset(record_path, teacher_id="teacherB")
    assert teacher_b.target_schema.atom_level == frozenset()
    b_frames = teacher_b.load()
    assert set(b_frames[0].meta) == {"energy"}
    assert "fx" not in b_frames[0]["atoms"]
    for index, want in enumerate(_EXPECTED_ENERGY_B):
        assert abs(float(b_frames[index].meta["energy"]) - want) <= _ENERGY_EXACT_ATOL

    assert teacher_a.source_id == _MOLREC_SOURCE_ID
    assert teacher_a.source_id != teacher_b.source_id
    assert "size=" not in teacher_a.source_id and "n=" not in teacher_a.source_id
    subset = MolRecDataset(record_path, teacher_id="teacherA", total=2)
    assert subset.source_id == _MOLREC_SUBSET_SOURCE_ID
    assert len(subset.load()) == 2

    print(
        f"  MolRec: {len(frames)} conformers, teacherA energies {list(_EXPECTED_ENERGY_A)} eV, "
        f"teacherB energies {list(_EXPECTED_ENERGY_B)} eV, source_id {_MOLREC_SOURCE_ID}"
    )


# ---------------------------------------------------------------------------
# Leg 3 — transforms
# ---------------------------------------------------------------------------


def check_transforms() -> None:
    """AtomicDress fit + state round-trip, UnitConvert factors, ConstantLabel."""
    samples = _dress_samples()

    unfitted = AtomicDress(elements=(1, 6, 8), target_key="U0")
    try:
        unfitted.execute(samples[0])
    except RuntimeError:
        pass
    else:  # pragma: no cover - a silent zero baseline is the bug this guards
        raise AssertionError("an unfitted AtomicDress must refuse to execute")

    dress = AtomicDress(elements=(1, 6, 8), target_key="U0", output_key="U0_dressed")
    dress.fit(samples)
    for element, want in _BASELINES.items():
        assert abs(dress.atomic_energies[element] - want) <= _ENERGY_EXACT_ATOL

    residuals = [float(dress.execute(sample).meta["U0_dressed"]) for sample in samples]
    for got, want in zip(residuals, _RESIDUALS):
        assert abs(got - want) <= _ENERGY_EXACT_ATOL
    assert abs(sum(r * r for r in residuals) - _RESIDUAL_SS) <= _ENERGY_EXACT_ATOL
    untouched = float(samples[0].meta["U0"])
    assert abs(untouched + 9.0) <= _ENERGY_EXACT_ATOL, "execute mutated its input sample"

    state = dress.state_dict()
    assert list(state["elements"]) == [1, 6, 8]
    restored = AtomicDress(elements=(1, 6, 8), target_key="U0", output_key="U0_dressed")
    restored.load_state_dict(state)
    for element, want in _BASELINES.items():
        assert abs(restored.atomic_energies[element] - want) <= _ENERGY_EXACT_ATOL
    for sample, want in zip(samples, _RESIDUALS):
        got = float(restored.execute(sample).meta["U0_dressed"])
        assert abs(got - want) <= _ENERGY_EXACT_ATOL

    convert = UnitConvert(
        {
            "U0": ("hartree", "eV"),
            "forces": ("hartree / bohr", "eV / angstrom"),
            "length": ("bohr", "angstrom"),
        }
    )
    assert abs(convert.factors["U0"] / _HARTREE_TO_EV - 1.0) <= 1e-6
    assert abs(convert.factors["forces"] / _HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM - 1.0) <= 1e-4
    assert abs(convert.factors["length"] / _BOHR_TO_ANGSTROM - 1.0) <= 1e-4

    energy_only = UnitConvert({"U0": ("hartree", "eV")})
    sample = _dress_sample([1, 1, 8], {"U0": 2.0, "gap": 0.25})
    converted = energy_only.execute(sample)
    assert abs(float(converted.meta["U0"]) / (2 * _HARTREE_TO_EV) - 1.0) <= 1e-6
    assert abs(float(converted.meta["gap"]) - 0.25) <= _ENERGY_EXACT_ATOL
    assert abs(float(sample.meta["U0"]) - 2.0) <= _ENERGY_EXACT_ATOL, "execute mutated input"

    labelled = ConstantLabel(key="total_charge", value=0.0).execute(converted)
    assert isinstance(labelled.meta["total_charge"], float)
    assert abs(float(labelled.meta["total_charge"])) <= _ENERGY_EXACT_ATOL
    assert abs(float(labelled.meta["gap"]) - 0.25) <= _ENERGY_EXACT_ATOL
    assert "total_charge" not in converted.meta, "execute mutated input"

    print(
        f"  Transforms: AtomicDress baselines {_BASELINES} eV (atol 1e-10), "
        f"residual SS {_RESIDUAL_SS}, hartree→eV {_HARTREE_TO_EV}, "
        "ConstantLabel total_charge 0.0"
    )


# ---------------------------------------------------------------------------
# Leg 4 — neighbour delegate (structural; needs no molnex)
# ---------------------------------------------------------------------------


def check_neighbor_delegate() -> None:
    """Pass-through, verbatim task_id, and a torch-free import of the module."""
    assert "torch" not in sys.modules, "importing molhub.dataset must not pull torch"
    assert "molix" not in sys.modules, "the molix import must stay lazy"

    # Verbatim forwarding, proven with a string the delegate could not compose.
    sentinel = NeighborDelegate(cutoff=_CUTOFF, neighbor_list=GoldenNeighborList("nlist:sentinel"))
    assert sentinel.task_id == "nlist:sentinel", "task_id must be the wrapped list's, verbatim"

    inner = GoldenNeighborList(_GOLDEN_TASK_ID)
    delegate = NeighborDelegate(cutoff=_CUTOFF, neighbor_list=inner)
    assert delegate.task_id == _GOLDEN_TASK_ID, "cache identity must be delegated verbatim"

    sample: dict[str, object] = {"Z": _CHAIN_Z, "pos": _CHAIN_POS}
    out = delegate.execute(sample)
    assert out is inner.returned, "the delegate must hand the wrapped result back"
    for key in ("edge_index", "edge_diff", "edge_dist"):
        assert out[key] is inner.returned[key], f"{key} was re-derived, not forwarded"
    assert len(inner.calls) == 1
    assert inner.calls[0]["pos"] == _CHAIN_POS
    assert inner.calls[0]["Z"] == _CHAIN_Z
    assert delegate(sample) is inner.returned, "__call__ must alias execute"

    assert out["edge_index"] == _GOLDEN_EDGE_INDEX
    assert out["edge_diff"] == _GOLDEN_EDGE_DIFF
    assert out["edge_dist"] == _GOLDEN_EDGE_DIST

    # The recorded goldens must obey the convention molnex documents:
    # ``edge_diff = pos[target] - pos[source]``, ``edge_dist = ‖edge_diff‖``,
    # every edge inside the cutoff, and every half pair paired with its
    # reverse. This checks the literals against the convention — it enumerates
    # no pairs and searches no cutoff, so it is not a second neighbour list.
    for (source, target), diff, dist in zip(
        _GOLDEN_EDGE_INDEX, _GOLDEN_EDGE_DIFF, _GOLDEN_EDGE_DIST
    ):
        expected = tuple(_CHAIN_POS[target][k] - _CHAIN_POS[source][k] for k in range(3))
        for got, want in zip(diff, expected):
            assert abs(got - want) <= _POS_ATOL, f"edge ({source}, {target}) violates edge_diff"
        assert abs(dist - sum(c * c for c in diff) ** 0.5) <= _POS_ATOL
        assert dist <= _CUTOFF
    assert {(t, s) for s, t in _GOLDEN_EDGE_INDEX} == set(_GOLDEN_EDGE_INDEX), "not bidirectional"
    assert _GOLDEN_EDGE_INDEX[: len(_GOLDEN_HALF_EDGE_INDEX)] == _GOLDEN_HALF_EDGE_INDEX

    half = NeighborDelegate(
        cutoff=_CUTOFF, symmetry=False, neighbor_list=GoldenNeighborList(_GOLDEN_HALF_TASK_ID)
    )
    assert half.task_id == _GOLDEN_HALF_TASK_ID
    assert half.task_id != delegate.task_id, "half pairs must not share a cache key"

    print(
        f"  NeighborDelegate: task_id {_GOLDEN_TASK_ID!r} forwarded verbatim, "
        f"edge_index {list(_GOLDEN_EDGE_INDEX)}, edge_dist {list(_GOLDEN_EDGE_DIST)} Å"
    )


def check_live_neighbor_parity() -> None:
    """Optional: the real ``molix.batch.NeighborList`` against the same goldens.

    Gated on ``MOLNEX_SRC`` exactly as ``tests/test_dataset/test_neighbor.py``
    is: molnex is an optional peer of molhub, so its absence is reported and
    skipped rather than failed.
    """
    src = os.environ.get("MOLNEX_SRC")
    if not src:
        print("  Live molnex parity: SKIPPED (MOLNEX_SRC unset)")
        return
    if src not in sys.path:
        sys.path.insert(0, src)
    try:
        importlib.import_module("molix.batch.neighbor")
        torch = importlib.import_module("torch")
    except ImportError as error:
        print(f"  Live molnex parity: SKIPPED ({error})")
        return

    pos = torch.tensor(_CHAIN_POS, dtype=torch.float32)
    out = NeighborDelegate(cutoff=_CUTOFF).execute({"Z": _CHAIN_Z, "pos": pos})
    assert [tuple(row) for row in out["edge_index"].tolist()] == list(_GOLDEN_EDGE_INDEX)
    for row, expected in zip(out["edge_diff"].tolist(), _GOLDEN_EDGE_DIFF):
        for got, want in zip(row, expected):
            assert abs(got - want) <= _POS_ATOL
    for got, want in zip(out["edge_dist"].tolist(), _GOLDEN_EDGE_DIST):
        assert abs(got - want) <= _POS_ATOL
    assert NeighborDelegate(cutoff=_CUTOFF).task_id == _GOLDEN_TASK_ID
    assert NeighborDelegate(cutoff=_CUTOFF, symmetry=False).task_id == _GOLDEN_HALF_TASK_ID
    print("  Live molnex parity: OK (edge_index / edge_diff / edge_dist / task_id)")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="molhub-reception-") as workdir:
        root = Path(workdir)
        water_root = root / "water_les"
        _write_water_root(water_root)
        record_path = root / "force_rec.zarr"
        _write_force_record(record_path)

        check_water_les(water_root, root / "empty")
        check_molrec(record_path)
        check_transforms()
        check_neighbor_delegate()
        check_live_neighbor_parity()

    print("molix-data-dissolution-05-molhub-reception: OK")


if __name__ == "__main__":
    main()
