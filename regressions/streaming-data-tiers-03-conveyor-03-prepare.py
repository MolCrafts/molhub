#!/usr/bin/env python
"""Regression: one mixed-split THEMol shard prepared into sealed, split-pure blocks.

Exercises the public surface of the conveyor's prepare stage
(``streaming-data-tiers-03-conveyor-03-prepare``) offline, in two legs over the
*same* fixture shard: five :class:`molpy.Trajectory` records carrying three
molecular identities routed ``train`` / ``val`` / ``test``, built out of
hand-made :class:`molpy.Frame`\\ s. Every coordinate and energy is a multiple of
``0.5``, exact in float32, so no assertion below needs a tolerance.

**The torch-free claim, checked first.** The statement immediately after
``import molhub.conveyor.prepare`` asserts that neither ``torch`` nor ``molix``
reached :data:`sys.modules`. That is the Option-A ruling of the spec (§ 5) made
observable: the whole package's single ``from molix.store.block import
BlockWriter, SamplingUnit`` lives inside
:class:`~molhub.conveyor.prepare.MolnexBlockWriter`'s constructor, so a base
install with neither package installed can still encode, route and unit-test a
shard.

**Leg A — ungated, fake writer.** The shard is driven through
:class:`~molhub.conveyor.prepare.PrepareJob` with the in-script
:class:`FakeBlockWriter`, which is honest about the one thing molhub reads back:
on ``seal()`` it writes the five manifest fields (``format``, ``split``,
``units``, ``sealed``, ``block_digest``) the job verifies before reporting a
block as READY evidence. Pinned as literals: the three sealed roots and their
``<name>-<split>-<seq>`` names, the per-split unit / frame / payload-byte counts,
the per-split unit keys, the digests read back out of each manifest, and the
concatenated ``pos`` / ``energy`` of each block. Whole-unit ingestion (I2) is
checked as a multiset: every input record appears exactly once across all
blocks, as one :class:`~molhub.conveyor.encoder.RawUnit` carrying all of its
source record's frames.

**Leg B — ``MOLNEX_SRC``-gated, the real molnex writer.** Gated exactly like
``tests/test_dataset/test_neighbor.py`` — ``MOLNEX_SRC`` onto :data:`sys.path`,
then ``importlib.import_module("molix.store")``, printing a SKIP line and
returning when molnex (or torch) is absent, so the script exits 0 either way. It
re-runs the same shard through :class:`MolnexBlockWriter` into a
:class:`tempfile.TemporaryDirectory`, then reads every sealed root back with
``molix.store.BlockReader`` and asserts: the same per-split unit and frame
counts as leg A, exactly one ``split`` per ``manifest.json`` (and no column in
the frozen schema whose name mentions a split — purity is structural), the unit
keys in append order, ``verify()`` passing over the sealed bytes, and
``pos`` equal **bit-for-bit** (``tobytes()``) to the float32 arrays the
encoder produced independently on this side of the seam.

Determinism: no network, no clock, no environment lookup other than the
``MOLNEX_SRC`` gate, no HDF5, and no third-party oracle runs to produce any
expected value. Both legs write only into a temporary directory this script
creates.

Provenance of the goldens (no tool runs here):

* Counts, names, keys, coordinates, energies and payload byte sizes are
  hand-derived from the fixture recipe in this file — the same recipe
  ``tests/test_conveyor/test_prepare.py`` uses. Coordinates are
  ``x = 0.5 * atom_index + 0.5 * step``, ``y = z = 0``; energies are
  ``-0.5 * step``; payload bytes are ``sum(column.nbytes)`` over the encoder's
  own columns (``Z`` ``<i2``, three ``<i4`` bond columns, ``pos`` and ``forces``
  ``(F*N, 3)`` ``<f4``, ``energy`` ``(F,)`` ``<f4``).
* The three identity hexes are the literals pinned by
  ``tests/test_conveyor/test_encoder.py``: blake2b-128 of the mapped isomeric
  SMILES, the rule ``scripts/build_class1_splits.py`` uses to *produce* the
  ``class1-universal-splits@1`` tables.
  command: ``python -c "import hashlib; print(hashlib.blake2b(SMILES.encode(),
  digest_size=16).hexdigest())"``; CPython 3.14.5, stdlib only; 2026-08-14.

tool: python
command: python regressions/streaming-data-tiers-03-conveyor-03-prepare.py
date: 2026-08-14
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from molhub.conveyor.prepare import (  # noqa: E402
    BlockWriterFactory,
    BlockWriterLike,
    MolnexBlockWriter,
    PreparedBlocks,
    PrepareJob,
)

# The Option-A ruling, checked before anything else this script does: importing
# the prepare stage must not drag in torch or molix. The one import of either
# lives inside MolnexBlockWriter.__init__ (leg B), which is what keeps a base
# install — no torch, no molnex — able to encode and route a whole shard.
assert "torch" not in sys.modules, (
    "importing molhub.conveyor.prepare pulled torch into sys.modules; the single "
    "import site is MolnexBlockWriter.__init__, so the base environment must stay "
    "torch-free."
)
assert "molix" not in sys.modules, (
    "importing molhub.conveyor.prepare pulled molix into sys.modules; molnex is an "
    "optional peer reached only through MolnexBlockWriter, never at module scope."
)

import numpy as np  # noqa: E402
from molpy import Block, Frame, Trajectory  # noqa: E402

from molhub.conveyor.encoder import RawUnit, THEMolUnitEncoder  # noqa: E402
from molhub.dataset.themol import THEMOL_UNITS  # noqa: E402

# ---------------------------------------------------------------------------
# The shard: five relaxations over three molecular identities, deliberately
# interleaved so arrival order and split order disagree.
# ---------------------------------------------------------------------------

WATER_SMILES = "[O:2]([H:1])[H:3]"
HOOH_SMILES = "[H:1][O:2][O:3][H:4]"
HF_SMILES = "[H:1][F:2]"

#: blake2b-128 of the mapped SMILES above — see the module docstring.
WATER_IDENTITY = "810eef0a316c3ae716b15724bd6a8779"
HOOH_IDENTITY = "159fcddf7a882e2d79a52e4f129e2459"
HF_IDENTITY = "b0881071b1d54c8fb0d6817885e2a9ab"

#: Molecular identity -> split. A plain mapping is the whole routing seam:
#: routing is a lookup, never a derivation, and streaming never re-splits.
SPLIT_OF: Mapping[str, str] = {
    WATER_IDENTITY: "train",
    HOOH_IDENTITY: "val",
    HF_IDENTITY: "test",
}

NAME = "themol-hessian-relax-shard-000"
TASK = "hessian-relax"
PROVENANCE: Mapping[str, Any] = {
    "source": "dataset:themol/hessian-relax@1#role=shard-000",
    "generator": "molhub.conveyor.prepare",
    "created_at": "2026-08-14T00:00:00Z",
    "units": dict(THEMOL_UNITS),
}

BLOCK_FORMAT = "molix.block/1"

#: The production-sized ceiling: this shard is kilobytes, so the only fan-out
#: exercised here is the split one, and each split seals exactly one block.
MAX_BLOCK_BYTES = 2_000_000_000

#: key -> (identity, frame count), in shard order.
SHARD_LAYOUT: tuple[tuple[str, str, int], ...] = (
    ("water-a", WATER_IDENTITY, 2),
    ("hooh-a", HOOH_IDENTITY, 1),
    ("water-b", WATER_IDENTITY, 3),
    ("hf-a", HF_IDENTITY, 1),
    ("hooh-b", HOOH_IDENTITY, 2),
)

#: identity -> (mapped SMILES, elements, atomic numbers, (atomi, atomj, order)).
_Species = tuple[str, tuple[str, ...], tuple[int, ...], tuple[tuple[int, ...], ...]]
_SPECIES: Mapping[str, _Species] = {
    WATER_IDENTITY: (WATER_SMILES, ("H", "O", "H"), (1, 8, 1), ((1, 1), (0, 2), (1, 1))),
    HOOH_IDENTITY: (
        HOOH_SMILES,
        ("H", "O", "O", "H"),
        (1, 8, 8, 1),
        ((0, 1, 2), (1, 2, 3), (1, 1, 1)),
    ),
    HF_IDENTITY: (HF_SMILES, ("H", "F"), (1, 9), ((0,), (1,), (1,))),
}

# ---------------------------------------------------------------------------
# Goldens. Every one of them is a literal, hand-derived from the recipe above.
# ---------------------------------------------------------------------------

#: Seal order: a writer is opened lazily on the first unit that routes to it, so
#: this is the arrival order of each split's *first* record (0, 1, 3).
SEAL_ORDER: tuple[str, ...] = ("train", "val", "test")

ROOT_NAMES: Mapping[str, str] = {
    "train": f"{NAME}-train-000",
    "val": f"{NAME}-val-000",
    "test": f"{NAME}-test-000",
}

UNITS_PER_SPLIT: Mapping[str, int] = {"train": 2, "val": 2, "test": 1}
FRAMES_PER_SPLIT: Mapping[str, int] = {"train": 5, "val": 3, "test": 1}
KEYS_PER_SPLIT: Mapping[str, tuple[str, ...]] = {
    "train": ("water-a", "water-b"),
    "val": ("hooh-a", "hooh-b"),
    "test": ("hf-a",),
}

#: The encoder's own column payload, in bytes, per sealed block:
#: ``Z`` ``2N`` + three ``<i4`` bond columns ``12B`` + per frame
#: ``(3N + 3N + 1) * 4``. water ``N=3, B=2`` -> ``30 + 76F``; hooh ``N=4, B=3``
#: -> ``44 + 100F``; hf ``N=2, B=1`` -> ``16 + 52F``.
#: This is what the fake writer commits. molnex additionally commits its own
#: synthesised index columns (``n_atoms``, ``unit_key_bytes``, ``bond_n``,
#: …), so leg B checks that its number is strictly larger rather than equal.
PAYLOAD_BYTES_PER_SPLIT: Mapping[str, int] = {"train": 440, "val": 388, "test": 68}

#: The fake's digests, handed out in writer-construction order — pinned so that
#: "the digest is read out of the manifest, never recomputed" is visible.
DIGEST_PER_SPLIT: Mapping[str, str] = {
    "train": f"{0:064x}",
    "val": f"{1:064x}",
    "test": f"{2:064x}",
}

#: ``pos`` of each sealed block, one row per **frame**, as x coordinates:
#: the fixture puts every atom on the x axis at ``0.5 * atom_index + 0.5 * step``,
#: so ``y`` and ``z`` are exactly ``0.0`` and the rows below flatten to the whole
#: ``(F * N, 3)`` column. train = water-a (2 frames of 3 atoms) then water-b (3
#: of 3); val = hooh-a (1 frame of 4) then hooh-b (2 of 4); test = hf-a (1 of 2).
POS_X_PER_SPLIT: Mapping[str, tuple[tuple[float, ...], ...]] = {
    "train": (
        (0.0, 0.5, 1.0),
        (0.5, 1.0, 1.5),
        (0.0, 0.5, 1.0),
        (0.5, 1.0, 1.5),
        (1.0, 1.5, 2.0),
    ),
    "val": (
        (0.0, 0.5, 1.0, 1.5),
        (0.0, 0.5, 1.0, 1.5),
        (0.5, 1.0, 1.5, 2.0),
    ),
    "test": ((0.0, 0.5),),
}

#: ``energy`` of each sealed block, in append order: ``-0.5 * step`` per frame,
#: one value per frame, so a unit that lost or gained a frame moves this list as
#: well as the counts above.
ENERGY_PER_SPLIT: Mapping[str, tuple[float, ...]] = {
    "train": (0.0, -0.5, 0.0, -0.5, -1.0),
    "val": (0.0, 0.0, -0.5),
    "test": (0.0,),
}


def _expected_pos(split: str) -> np.ndarray:
    """The ``(F * N, 3)`` ``<f4`` positions of *split*'s block, from the literals."""
    return np.asarray(
        [[x, 0.0, 0.0] for frame in POS_X_PER_SPLIT[split] for x in frame],
        dtype=np.float32,
    )


# ---------------------------------------------------------------------------
# Fixture construction — hand-built frames, no HDF5 and no reader involved
# ---------------------------------------------------------------------------


def _frame(
    *,
    smiles: str,
    molecule_id: str,
    elements: Sequence[str],
    numbers: Sequence[int],
    bonds: tuple[tuple[int, ...], ...],
    step: int,
) -> Frame:
    """One E/F frame of *molecule_id*, displaced by ``0.5 * step`` along x."""
    n_atoms = len(numbers)
    offset = 0.5 * step
    coords = np.asarray(
        [[0.5 * index + offset, 0.0, 0.0] for index in range(n_atoms)], dtype=np.float64
    )
    frame = Frame()
    frame["atoms"] = Block(
        {
            "element": np.asarray(elements, dtype=str),
            "number": np.asarray(numbers, dtype=np.int64),
            "atom_map": np.arange(1, n_atoms + 1, dtype=np.int64),
            "formal_charge": np.zeros(n_atoms, dtype=np.int64),
            "x": coords[:, 0],
            "y": coords[:, 1],
            "z": coords[:, 2],
            "fx": np.zeros(n_atoms, dtype=np.float64),
            "fy": np.zeros(n_atoms, dtype=np.float64),
            "fz": np.zeros(n_atoms, dtype=np.float64),
        }
    )
    atomi, atomj, order = bonds
    frame["bonds"] = Block(
        {
            "atomi": np.asarray(atomi, dtype=np.int64),
            "atomj": np.asarray(atomj, dtype=np.int64),
            "bond_number": np.asarray(order, dtype=np.int64),
        }
    )
    frame.meta.update(
        {
            "molecule_id": molecule_id,
            "source_record_id": molecule_id,
            "mapped_nonisomeric_smiles": smiles,
            "mapped_isomeric_smiles": smiles,
            "source_id": "dataset:themol/hessian-relax@1#role=shard-000",
            "total_charge": 0,
            "energy": -0.5 * step,
        }
    )
    return frame


def _trajectory(key: str, identity: str, n_frames: int) -> Trajectory:
    """One whole relaxation of the species behind *identity* — one sampling unit."""
    smiles, elements, numbers, bonds = _SPECIES[identity]
    return Trajectory(
        [
            _frame(
                smiles=smiles,
                molecule_id=key,
                elements=elements,
                numbers=numbers,
                bonds=bonds,
                step=step,
            )
            for step in range(n_frames)
        ]
    )


def _shard() -> tuple[Trajectory, ...]:
    """The five-record, three-identity, split-MIXED fixture shard."""
    return tuple(_trajectory(key, identity, n_frames) for key, identity, n_frames in SHARD_LAYOUT)


def _job(records: Sequence[Any], *, root: Path, factory: BlockWriterFactory) -> PrepareJob:
    """The job under test — every collaborator an explicit, narrow parameter."""
    return PrepareJob(
        records,
        encoder=THEMolUnitEncoder(task=TASK),
        split_of=SPLIT_OF,
        writer_factory=factory,
        root=root,
        name=NAME,
        provenance=PROVENANCE,
        max_block_bytes=MAX_BLOCK_BYTES,
    )


def _encoded_by_split() -> Mapping[str, tuple[RawUnit, ...]]:
    """The shard encoded here, grouped by split — leg B's reference arrays.

    Re-derives the routing independently of :class:`PrepareJob`: a unit goes to
    ``SPLIT_OF[unit.identity]``, in shard order. If the job and this loop ever
    disagree about which block a molecule belongs in, leg B's per-block
    comparison fails rather than passing on a coincidence.
    """
    encoder = THEMolUnitEncoder(task=TASK)
    grouped: dict[str, list[RawUnit]] = {}
    for record in _shard():
        unit = encoder.encode(record)
        grouped.setdefault(SPLIT_OF[unit.identity], []).append(unit)
    return {split: tuple(units) for split, units in grouped.items()}


# ---------------------------------------------------------------------------
# The fake writer — honest about the five manifest fields molhub reads back
# ---------------------------------------------------------------------------


class FakeBlockWriter:
    """A ``BlockWriterLike`` that records what it was fed and seals honestly.

    ``append_unit`` takes the unit and nothing else, mirroring
    ``molnex:src/molix/store/block.py:890``: a job that tried to pass a per-unit
    ``split=`` would raise a ``TypeError`` here rather than quietly working, so
    split purity is observable as a *shape* and not only as a value.

    ``seal()`` writes the five fields the prepare stage reads back out of
    ``manifest.json`` (``format``, ``split``, ``units``, ``sealed``,
    ``block_digest``). Stubbing them away would have made leg A's READY evidence
    a tautology.

    Args:
        root: Block directory, created on construction as the real writer does.
        split: The one split this block holds — a constructor argument, never a
            per-unit field.
        provenance: Opaque provenance mapping, recorded for inspection.
        digest: The ``block_digest`` this fake writes on ``seal()``.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        split: str,
        provenance: Mapping[str, Any],
        digest: str = f"{0:064x}",
    ) -> None:
        self.root = Path(root)
        self.split = split
        self.provenance = dict(provenance)
        self.digest = digest
        self.appended: list[Any] = []
        self.sealed = False
        self._bytes = 0
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def unit_count(self) -> int:
        """Units committed to this block so far."""
        return len(self.appended)

    @property
    def committed_bytes(self) -> int:
        """The encoder's own column payload, in bytes."""
        return self._bytes

    @property
    def keys(self) -> tuple[str, ...]:
        """The unit keys this block holds, in arrival order."""
        return tuple(unit.key for unit in self.appended)

    def append_unit(self, unit: Any) -> int:
        """Take one whole unit; there is no frame-level entry point."""
        self.appended.append(unit)
        self._bytes += sum(
            column.nbytes for column in (*unit.topology.values(), *unit.frames.values())
        )
        return len(self.appended) - 1

    def seal(self) -> None:
        """Finalize the block and write the manifest molhub verifies."""
        if self.sealed:
            raise AssertionError(f"block at {self.root} was sealed twice")
        if not self.appended:
            raise AssertionError(f"block at {self.root} has no units; molnex rejects an empty seal")
        self.sealed = True
        document = {
            "format": BLOCK_FORMAT,
            "split": self.split,
            "units": self.unit_count,
            "sealed": True,
            "block_digest": self.digest,
        }
        (self.root / "manifest.json").write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )


class RecordingWriterFactory:
    """A ``BlockWriterFactory`` — the *constructor* seam, with a log.

    Every writer is recorded at construction together with its single ``split``,
    which is how "one ``split=`` per writer" is observable from outside the job.
    """

    def __init__(self) -> None:
        self.writers: list[FakeBlockWriter] = []

    def __call__(self, root: Path, *, split: str, provenance: Mapping[str, Any]) -> FakeBlockWriter:
        """Open one block at *root* holding exactly one *split*."""
        writer = FakeBlockWriter(
            root, split=split, provenance=provenance, digest=f"{len(self.writers):064x}"
        )
        self.writers.append(writer)
        return writer

    @property
    def sealed(self) -> tuple[FakeBlockWriter, ...]:
        """Every writer this factory opened that reached ``seal()``."""
        return tuple(writer for writer in self.writers if writer.sealed)


# ---------------------------------------------------------------------------
# Leg A — the ungated goldens
# ---------------------------------------------------------------------------


def check_fake_writer(workdir: Path) -> None:
    """One mixed shard, three split-pure sealed roots, every unit whole and once."""
    factory = RecordingWriterFactory()
    prepared = _job(_shard(), root=workdir, factory=factory).run()

    assert isinstance(prepared, PreparedBlocks)
    assert prepared.name == NAME

    # -- the fan-out: three sealed roots, named and ordered ------------------
    assert len(prepared.blocks) == 3, f"expected 3 sealed blocks, got {len(prepared.blocks)}"
    assert [block.split for block in prepared.blocks] == list(SEAL_ORDER)
    assert [block.root for block in prepared.blocks] == [
        workdir / ROOT_NAMES[split] for split in SEAL_ORDER
    ]
    assert len(factory.sealed) == 3, "a writer was opened and never sealed"
    assert sorted(writer.split for writer in factory.writers) == ["test", "train", "val"], (
        "split purity is structural: exactly one split= value per writer"
    )

    # -- the counts, per split ----------------------------------------------
    assert {block.split: block.unit_count for block in prepared.blocks} == dict(UNITS_PER_SPLIT)
    assert {block.split: block.frame_count for block in prepared.blocks} == dict(FRAMES_PER_SPLIT)
    assert {block.split: block.committed_bytes for block in prepared.blocks} == dict(
        PAYLOAD_BYTES_PER_SPLIT
    )
    assert {writer.split: writer.keys for writer in factory.sealed} == dict(KEYS_PER_SPLIT)

    # -- I2: every input record appended exactly once, and whole -------------
    appended = [unit for writer in factory.writers for unit in writer.appended]
    assert all(isinstance(unit, RawUnit) for unit in appended), "something other than a unit landed"
    assert sorted(unit.key for unit in appended) == sorted(key for key, _, _ in SHARD_LAYOUT), (
        "the appended keys are not the shard's keys, each exactly once"
    )
    assert {unit.key: unit.n_frames for unit in appended} == {
        key: n_frames for key, _, n_frames in SHARD_LAYOUT
    }, "a unit reached a writer with a frame count its source record does not have"
    assert isinstance(factory.writers[0], BlockWriterLike), "the fake drifted from the seam"
    assert isinstance(factory, BlockWriterFactory), "the factory drifted from the seam"

    # -- READY evidence: read out of each manifest, never recomputed ---------
    assert {block.split: block.block_digest for block in prepared.blocks} == dict(DIGEST_PER_SPLIT)
    for block in prepared.blocks:
        document = json.loads((block.root / "manifest.json").read_text(encoding="utf-8"))
        assert document["format"] == BLOCK_FORMAT
        assert document["sealed"] is True
        assert document["split"] == block.split
        assert document["units"] == block.unit_count
        assert document["block_digest"] == block.block_digest

    # -- the payload itself, per block ---------------------------------------
    for writer in factory.sealed:
        positions = np.concatenate([unit.frames["pos"] for unit in writer.appended])
        energies = np.concatenate([unit.frames["energy"] for unit in writer.appended])
        assert positions.dtype.str == "<f4"
        assert energies.dtype.str == "<f4"
        assert positions.tolist() == _expected_pos(writer.split).tolist(), (
            f"{writer.split} positions drifted"
        )
        assert energies.tolist() == list(ENERGY_PER_SPLIT[writer.split])

    print(
        f"  Leg A (fake writer): {len(prepared.blocks)} sealed roots "
        f"{[ROOT_NAMES[split] for split in SEAL_ORDER]}, units "
        f"{ {block.split: block.unit_count for block in prepared.blocks} }, frames "
        f"{ {block.split: block.frame_count for block in prepared.blocks} }, keys "
        f"{ {writer.split: writer.keys for writer in factory.sealed} }, "
        f"{len(appended)} whole units appended once each, digests read from manifest.json"
    )


# ---------------------------------------------------------------------------
# Leg B — the real molnex BlockWriter, gated on MOLNEX_SRC
# ---------------------------------------------------------------------------


def check_molnex_writer(workdir: Path) -> None:
    """The same shard through ``MolnexBlockWriter``, read back with ``BlockReader``.

    Gated on ``MOLNEX_SRC`` exactly as ``tests/test_dataset/test_neighbor.py``
    is: molnex is an optional, unpublished peer of molhub, so its absence is
    reported and skipped rather than failed.
    """
    src = os.environ.get("MOLNEX_SRC")
    if not src:
        print("  Leg B (real molnex BlockWriter): SKIPPED (MOLNEX_SRC unset)")
        return
    if src not in sys.path:
        sys.path.insert(0, src)
    try:
        block_reader = importlib.import_module("molix.store").BlockReader
    except ImportError as error:
        print(f"  Leg B (real molnex BlockWriter): SKIPPED ({error})")
        return

    assert isinstance(MolnexBlockWriter, BlockWriterFactory), (
        "the adapter class object is the factory seam; a create_writer() function is not"
    )
    factory: BlockWriterFactory = MolnexBlockWriter
    prepared = _job(_shard(), root=workdir, factory=factory).run()

    assert [block.split for block in prepared.blocks] == list(SEAL_ORDER)
    assert [block.root for block in prepared.blocks] == [
        workdir / ROOT_NAMES[split] for split in SEAL_ORDER
    ]
    assert {block.split: block.unit_count for block in prepared.blocks} == dict(UNITS_PER_SPLIT)
    assert {block.split: block.frame_count for block in prepared.blocks} == dict(FRAMES_PER_SPLIT)

    encoded = _encoded_by_split()
    splits: list[str] = []
    for block in prepared.blocks:
        # One split per manifest, and no per-unit split anywhere in the schema.
        document = json.loads((block.root / "manifest.json").read_text(encoding="utf-8"))
        assert document["format"] == BLOCK_FORMAT
        assert document["sealed"] is True
        assert isinstance(document["split"], str)
        assert document["split"] == block.split
        assert document["units"] == block.unit_count
        assert document["block_digest"] == block.block_digest
        assert not [name for name in document["columns"] if "split" in name], (
            f"{block.root} declares a per-unit split column; purity must stay structural"
        )
        splits.append(document["split"])

        # molnex commits its own index columns on top of the encoder's payload.
        assert block.committed_bytes > PAYLOAD_BYTES_PER_SPLIT[block.split]

        reader = block_reader(block.root)
        reader.verify()
        assert reader.unit_count == UNITS_PER_SPLIT[block.split]
        assert reader.frame_count == FRAMES_PER_SPLIT[block.split]
        assert (
            tuple(reader.unit_key(index) for index in range(reader.unit_count))
            == KEYS_PER_SPLIT[block.split]
        )

        units = encoded[block.split]
        expected = np.concatenate([unit.frames["pos"] for unit in units])
        assert expected.dtype.str == "<f4"
        assert expected.tolist() == _expected_pos(block.split).tolist(), (
            "the encoder's positions drifted from this script's literals"
        )
        stored = reader.column("pos")
        assert stored.dtype.itemsize == 4, f"pos came back as {stored.dtype}"
        assert tuple(stored.shape) == expected.shape
        # Bit-for-bit: the block's bytes are the encoder's bytes, not a rounded
        # copy of them — MolnexBlockWriter wraps the numpy buffer, never casts it.
        assert stored.numpy().tobytes() == expected.tobytes(), (
            f"{block.root} pos differs bit-for-bit from the encoder's float32 array"
        )
        stored_energy = reader.column("energy")
        assert stored_energy.numpy().tolist() == list(ENERGY_PER_SPLIT[block.split])

    assert sorted(splits) == ["test", "train", "val"], f"splits drifted: {splits}"

    print(
        f"  Leg B (real molnex BlockWriter): {len(prepared.blocks)} sealed roots "
        f"{[block.root.name for block in prepared.blocks]}, one split per manifest "
        f"{splits}, units { {block.split: block.unit_count for block in prepared.blocks} }, "
        f"frames { {block.split: block.frame_count for block in prepared.blocks} }, "
        "verify() clean, pos bit-for-bit identical to the encoder's float32 arrays"
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="molhub-conveyor-prepare-") as workdir:
        root = Path(workdir)
        check_fake_writer(root / "fake")
        check_molnex_writer(root / "molnex")

    print("streaming-data-tiers-03-conveyor-03-prepare: OK")


if __name__ == "__main__":
    main()
