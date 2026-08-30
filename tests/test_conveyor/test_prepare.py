"""Tests for the prepare stage — split routing and unit-integral block output.

Mirrors ``src/molhub/conveyor/prepare.py``. Nothing here imports torch, molix or
molnex: the writer is the injected fake below, which is the whole point of the
``BlockWriterLike`` / ``BlockWriterFactory`` seam. The fake is honest about the
one thing molhub reads back — on ``seal()`` it writes the five manifest fields
(``format``, ``split``, ``units``, ``sealed``, ``block_digest``) that the job
verifies before it reports a block as READY evidence — so a test can make a
manifest *wrong* instead of stubbing the check away.

Fixtures are hand-built :class:`molpy.Frame` records of three species, so five
records carry exactly three molecular identities and one shard is genuinely
split-MIXED. Coordinates and energies are multiples of ``0.5``; no assertion in
this file needs a tolerance.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from molpy import Block, Frame

import molhub
from molhub.conveyor.encoder import RawUnit, THEMolUnitEncoder
from molhub.conveyor.errors import (
    BlockFormatError,
    IncompleteProvenanceError,
    UnroutableUnitError,
)
from molhub.conveyor.prepare import PreparedBlock, PreparedBlocks, PrepareJob
from molhub.dataset.themol import THEMOL_UNITS

_PREPARE_SOURCE = Path(molhub.__file__).parent / "conveyor" / "prepare.py"

# ---------------------------------------------------------------------------
# The shard: five relaxation trajectories over three molecular identities.
# ---------------------------------------------------------------------------

WATER_SMILES = "[O:2]([H:1])[H:3]"
HOOH_SMILES = "[H:1][O:2][O:3][H:4]"
HF_SMILES = "[H:1][F:2]"

# blake2b-128 of the mapped SMILES, the rule `scripts/build_class1_splits.py`
# uses to *produce* the split tables. Pinned literals; see test_encoder.py.
WATER_IDENTITY = "810eef0a316c3ae716b15724bd6a8779"
HOOH_IDENTITY = "159fcddf7a882e2d79a52e4f129e2459"
HF_IDENTITY = "b0881071b1d54c8fb0d6817885e2a9ab"

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

# key -> (identity, frame count). The shard is deliberately interleaved, so a
# job that grouped by arrival order instead of by split would still look right
# on the first two records.
SHARD_LAYOUT: tuple[tuple[str, str, int], ...] = (
    ("water-a", WATER_IDENTITY, 2),
    ("hooh-a", HOOH_IDENTITY, 1),
    ("water-b", WATER_IDENTITY, 3),
    ("hf-a", HF_IDENTITY, 1),
    ("hooh-b", HOOH_IDENTITY, 2),
)

UNITS_PER_SPLIT: Mapping[str, int] = {"train": 2, "val": 2, "test": 1}
FRAMES_PER_SPLIT: Mapping[str, int] = {"train": 5, "val": 3, "test": 1}
KEYS_PER_SPLIT: Mapping[str, tuple[str, ...]] = {
    "train": ("water-a", "water-b"),
    "val": ("hooh-a", "hooh-b"),
    "test": ("hf-a",),
}

# identity -> (mapped SMILES, elements, atomic numbers, (atomi, atomj, order)).
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


def _trajectory(key: str, identity: str, n_frames: int) -> tuple:
    """One whole relaxation of the species behind *identity*."""
    smiles, elements, numbers, bonds = _SPECIES[identity]
    return tuple(
        _frame(
            smiles=smiles,
            molecule_id=key,
            elements=elements,
            numbers=numbers,
            bonds=bonds,
            step=step,
        )
        for step in range(n_frames)
    )


def _shard() -> tuple[tuple, ...]:
    """The five-record, three-identity, split-MIXED fixture shard."""
    return tuple(_trajectory(key, identity, n_frames) for key, identity, n_frames in SHARD_LAYOUT)


# ---------------------------------------------------------------------------
# The fake writer. The only thing standing in for molnex in this file.
# ---------------------------------------------------------------------------


class FakeBlockWriter:
    """A ``BlockWriterLike`` that records what it was fed and seals honestly.

    ``append_unit`` takes the unit and nothing else, mirroring
    ``molnex:src/molix/store/block.py:890``: a job that tried to pass ``split=``
    per unit would fail here with a ``TypeError`` rather than quietly working.

    Args:
        root: Block directory; created on construction, as the real writer does.
        split: The one split this block holds — a constructor argument, never a
            per-unit field.
        provenance: Opaque provenance mapping, recorded for inspection.
        digest: The ``block_digest`` this fake writes on ``seal()``.
        manifest_patch: Fields overwritten in the sealed manifest, so a test can
            produce a manifest molhub must refuse.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        split: str,
        provenance: Mapping[str, Any],
        digest: str = f"{0:064x}",
        manifest_patch: Mapping[str, Any] | None = None,
    ) -> None:
        self.root = Path(root)
        self.split = split
        self.provenance = dict(provenance)
        self.digest = digest
        self.appended: list[Any] = []
        self.sealed = False
        self.sealed_bytes: int | None = None
        self._bytes = 0
        self._patch = dict(manifest_patch or {})
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def unit_count(self) -> int:
        return len(self.appended)

    @property
    def committed_bytes(self) -> int:
        return self._bytes

    @property
    def keys(self) -> tuple[str, ...]:
        """The unit keys this block holds, in arrival order."""
        return tuple(unit.key for unit in self.appended)

    def append_unit(self, unit: Any) -> int:
        self.appended.append(unit)
        self._bytes += sum(
            column.nbytes for column in (*unit.topology.values(), *unit.frames.values())
        )
        return len(self.appended) - 1

    def seal(self) -> None:
        if self.sealed:
            raise ValueError(f"block at {self.root} is already sealed")
        if not self.appended:
            raise ValueError(f"block at {self.root} has no units; molnex rejects an empty seal")
        self.sealed = True
        self.sealed_bytes = self._bytes
        document: dict[str, Any] = {
            "format": BLOCK_FORMAT,
            "split": self.split,
            "units": self.unit_count,
            "sealed": True,
            "block_digest": self.digest,
            **self._patch,
        }
        (self.root / "manifest.json").write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )


class RecordingWriterFactory:
    """A ``BlockWriterFactory`` — the *constructor* seam, with a log.

    Every writer is recorded at construction with its root and its single
    ``split``, which is how "one ``split=`` value per writer" is observable from
    outside the job.
    """

    def __init__(self, *, manifest_patch: Mapping[str, Any] | None = None) -> None:
        self.writers: list[FakeBlockWriter] = []
        self._patch = manifest_patch

    def __call__(self, root: Path, *, split: str, provenance: Mapping[str, Any]) -> FakeBlockWriter:
        writer = FakeBlockWriter(
            root,
            split=split,
            provenance=provenance,
            digest=f"{len(self.writers):064x}",
            manifest_patch=self._patch,
        )
        self.writers.append(writer)
        return writer

    @property
    def sealed(self) -> tuple[FakeBlockWriter, ...]:
        return tuple(writer for writer in self.writers if writer.sealed)

    def by_split(self, split: str) -> tuple[FakeBlockWriter, ...]:
        return tuple(writer for writer in self.writers if writer.split == split)


def _job(
    records: Iterable[tuple],
    *,
    root: Path,
    factory: RecordingWriterFactory,
    split_of: Mapping[str, str] = SPLIT_OF,
    provenance: Mapping[str, Any] = PROVENANCE,
    max_block_bytes: int = 2_000_000_000,
) -> PrepareJob:
    return PrepareJob(
        records,
        encoder=THEMolUnitEncoder(task=TASK),
        split_of=split_of,
        writer_factory=factory,
        root=root,
        name=NAME,
        provenance=provenance,
        max_block_bytes=max_block_bytes,
    )


@pytest.fixture
def factory() -> RecordingWriterFactory:
    return RecordingWriterFactory()


@pytest.fixture
def prepared(tmp_path: Path, factory: RecordingWriterFactory) -> PreparedBlocks:
    """The whole fixture shard, prepared with a production-sized ceiling."""
    return _job(_shard(), root=tmp_path, factory=factory).run()


def _block_of(prepared: PreparedBlocks, split: str) -> PreparedBlock:
    """The single prepared block of *split* — fails loudly if the fan-out is wrong."""
    matches = [block for block in prepared.blocks if block.split == split]
    assert len(matches) == 1, f"expected one {split} block, got {matches}"
    return matches[0]


class TestPrepareJob:
    """A shard in, split-pure sealed blocks out, one whole unit at a time."""

    # -- unit integrality (I2) --------------------------------------------

    def test_every_appended_object_is_a_whole_unit(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        appended = [unit for writer in factory.writers for unit in writer.appended]
        assert len(appended) == len(SHARD_LAYOUT)
        assert all(isinstance(unit, RawUnit) for unit in appended)

    def test_each_unit_carries_its_records_frame_count(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        """A trajectory is one unit; flattening it would show up here first."""
        frames = {unit.key: unit.n_frames for writer in factory.writers for unit in writer.appended}
        assert frames == {key: n_frames for key, _, n_frames in SHARD_LAYOUT}

    def test_every_record_is_appended_exactly_once(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        keys = [unit.key for writer in factory.writers for unit in writer.appended]
        assert sorted(keys) == sorted(key for key, _, _ in SHARD_LAYOUT)

    # -- split fan-out (I7) -----------------------------------------------

    def test_a_mixed_shard_seals_one_block_per_split(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        assert len(factory.sealed) == 3
        assert {block.split for block in prepared.blocks} == {"train", "val", "test"}

    def test_each_writer_is_constructed_with_exactly_one_split(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        """Split purity is structural: the constructor takes it, nothing else does."""
        assert sorted(writer.split for writer in factory.writers) == ["test", "train", "val"]

    def test_no_writer_is_opened_for_a_split_with_no_members(
        self, tmp_path: Path, factory: RecordingWriterFactory
    ) -> None:
        """Lazy open: molnex rejects sealing a block that never got a unit."""
        _job(_shard()[3:4], root=tmp_path, factory=factory).run()
        assert [writer.split for writer in factory.writers] == ["test"]

    def test_per_split_unit_counts_are_pinned(self, prepared: PreparedBlocks) -> None:
        counts = {block.split: block.unit_count for block in prepared.blocks}
        assert counts == dict(UNITS_PER_SPLIT)

    def test_per_split_frame_counts_are_pinned(self, prepared: PreparedBlocks) -> None:
        """The per-pass coverage number, summed from the units, not guessed."""
        counts = {block.split: block.frame_count for block in prepared.blocks}
        assert counts == dict(FRAMES_PER_SPLIT)

    def test_each_unit_lands_in_the_block_of_its_molecules_split(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        landed = {writer.split: writer.keys for writer in factory.sealed}
        assert landed == dict(KEYS_PER_SPLIT)

    def test_block_roots_are_named_by_split_and_sequence(
        self, tmp_path: Path, prepared: PreparedBlocks
    ) -> None:
        assert {block.root for block in prepared.blocks} == {
            tmp_path / f"{NAME}-train-000",
            tmp_path / f"{NAME}-val-000",
            tmp_path / f"{NAME}-test-000",
        }

    def test_an_unroutable_identity_names_the_identity_and_the_key(
        self, tmp_path: Path, factory: RecordingWriterFactory
    ) -> None:
        """No default split, no "assume train": streaming never re-splits."""
        job = _job(
            _shard()[:1],
            root=tmp_path,
            factory=factory,
            split_of={HOOH_IDENTITY: "val"},
        )
        with pytest.raises(UnroutableUnitError) as raised:
            job.run()
        message = str(raised.value)
        assert WATER_IDENTITY in message
        assert "water-a" in message

    def test_an_unroutable_identity_opens_no_writer(
        self, tmp_path: Path, factory: RecordingWriterFactory
    ) -> None:
        with pytest.raises(UnroutableUnitError):
            _job(_shard()[:1], root=tmp_path, factory=factory, split_of={}).run()
        assert factory.writers == []

    # -- size fan-out (I2, second half) -----------------------------------

    def test_a_tiny_ceiling_seals_one_block_per_unit(
        self, tmp_path: Path, factory: RecordingWriterFactory
    ) -> None:
        """The check runs *after* the append, so a unit still lands whole."""
        records = [_trajectory(key, WATER_IDENTITY, n) for key, n in (("a", 2), ("b", 3), ("c", 1))]
        prepared = _job(records, root=tmp_path, factory=factory, max_block_bytes=1).run()
        assert len(prepared.blocks) == 3
        assert [block.unit_count for block in prepared.blocks] == [1, 1, 1]

    def test_size_fan_out_numbers_the_blocks_in_order(
        self, tmp_path: Path, factory: RecordingWriterFactory
    ) -> None:
        records = [_trajectory(key, WATER_IDENTITY, n) for key, n in (("a", 2), ("b", 3), ("c", 1))]
        prepared = _job(records, root=tmp_path, factory=factory, max_block_bytes=1).run()
        assert [block.root for block in prepared.blocks] == [
            tmp_path / f"{NAME}-train-000",
            tmp_path / f"{NAME}-train-001",
            tmp_path / f"{NAME}-train-002",
        ]

    def test_no_unit_is_cut_by_the_ceiling(
        self, tmp_path: Path, factory: RecordingWriterFactory
    ) -> None:
        """Each block holds one whole trajectory, with all of its frames."""
        records = [_trajectory(key, WATER_IDENTITY, n) for key, n in (("a", 2), ("b", 3), ("c", 1))]
        _job(records, root=tmp_path, factory=factory, max_block_bytes=1).run()
        assert [(writer.keys, writer.appended[0].n_frames) for writer in factory.sealed] == [
            (("a",), 2),
            (("b",), 3),
            (("c",), 1),
        ]

    def test_no_unit_key_appears_in_two_blocks(
        self, tmp_path: Path, factory: RecordingWriterFactory
    ) -> None:
        records = [_trajectory(key, WATER_IDENTITY, n) for key, n in (("a", 2), ("b", 3), ("c", 1))]
        _job(records, root=tmp_path, factory=factory, max_block_bytes=1).run()
        keys = [key for writer in factory.writers for key in writer.keys]
        assert sorted(keys) == ["a", "b", "c"]

    # -- provenance --------------------------------------------------------

    @pytest.mark.parametrize("missing", ["source", "generator", "created_at", "units"])
    def test_incomplete_provenance_is_rejected(
        self, tmp_path: Path, factory: RecordingWriterFactory, missing: str
    ) -> None:
        provenance = {key: value for key, value in PROVENANCE.items() if key != missing}
        with pytest.raises(IncompleteProvenanceError):
            _job(_shard(), root=tmp_path, factory=factory, provenance=provenance).run()

    @pytest.mark.parametrize("missing", ["source", "generator", "created_at", "units"])
    def test_incomplete_provenance_is_rejected_before_any_writer_opens(
        self, tmp_path: Path, factory: RecordingWriterFactory, missing: str
    ) -> None:
        """molnex may not even be importable; the defect must surface first."""
        provenance = {key: value for key, value in PROVENANCE.items() if key != missing}
        with pytest.raises(IncompleteProvenanceError):
            _job(_shard(), root=tmp_path, factory=factory, provenance=provenance).run()
        assert factory.writers == []

    # -- manifest verification (I5) ---------------------------------------

    def test_an_unsealed_manifest_is_rejected(self, tmp_path: Path) -> None:
        """READY is witnessed by the sealed manifest, or it is not witnessed."""
        factory = RecordingWriterFactory(manifest_patch={"sealed": False})
        with pytest.raises(BlockFormatError):
            _job(_shard(), root=tmp_path, factory=factory).run()

    def test_a_foreign_block_format_is_rejected(self, tmp_path: Path) -> None:
        factory = RecordingWriterFactory(manifest_patch={"format": "molix.block/2"})
        with pytest.raises(BlockFormatError):
            _job(_shard(), root=tmp_path, factory=factory).run()

    def test_a_unit_count_disagreement_is_rejected(self, tmp_path: Path) -> None:
        """The manifest's ``units`` must agree with what the writer says it took."""
        factory = RecordingWriterFactory(manifest_patch={"units": 99})
        with pytest.raises(BlockFormatError):
            _job(_shard(), root=tmp_path, factory=factory).run()

    # -- lifecycle ---------------------------------------------------------

    def test_a_second_run_is_rejected(
        self, tmp_path: Path, factory: RecordingWriterFactory
    ) -> None:
        """Single-shot: re-running would re-open roots that already hold blocks."""
        job = _job(_shard(), root=tmp_path, factory=factory)
        job.run()
        with pytest.raises(RuntimeError):
            job.run()

    def test_a_non_positive_ceiling_is_rejected(
        self, tmp_path: Path, factory: RecordingWriterFactory
    ) -> None:
        with pytest.raises(ValueError):
            _job(_shard(), root=tmp_path, factory=factory, max_block_bytes=0).run()


class TestPreparedBlock:
    """The READY evidence for one sealed root, read back from its manifest."""

    def test_it_carries_the_split_it_was_written_with(self, prepared: PreparedBlocks) -> None:
        assert _block_of(prepared, "train").split == "train"

    def test_it_carries_the_writers_unit_count(self, prepared: PreparedBlocks) -> None:
        assert _block_of(prepared, "train").unit_count == UNITS_PER_SPLIT["train"]

    def test_it_carries_the_frame_count_summed_from_the_units(
        self, prepared: PreparedBlocks
    ) -> None:
        assert _block_of(prepared, "val").frame_count == FRAMES_PER_SPLIT["val"]

    def test_it_carries_the_writers_committed_bytes(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        by_root = {writer.root: writer.sealed_bytes for writer in factory.sealed}
        assert {block.root: block.committed_bytes for block in prepared.blocks} == by_root

    def test_it_carries_the_manifests_block_digest(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        """Read, never recomputed: recomputation is ``BlockReader.verify``'s job."""
        by_root = {writer.root: writer.digest for writer in factory.sealed}
        assert {block.root: block.block_digest for block in prepared.blocks} == by_root

    def test_the_digest_is_the_one_in_the_manifest_file(self, prepared: PreparedBlocks) -> None:
        block = _block_of(prepared, "test")
        document = json.loads((block.root / "manifest.json").read_text(encoding="utf-8"))
        assert block.block_digest == document["block_digest"]

    def test_it_is_frozen(self, prepared: PreparedBlocks) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            _block_of(prepared, "train").split = "test"  # type: ignore[misc]


class TestPreparedBlocks:
    """One value carrying everything the conveyor driver needs to write READY."""

    def test_it_carries_the_shard_name(self, prepared: PreparedBlocks) -> None:
        assert prepared.name == NAME

    def test_it_names_every_root_the_job_sealed(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        assert {block.root for block in prepared.blocks} == {
            writer.root for writer in factory.sealed
        }

    def test_it_has_one_entry_per_sealed_root(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        assert len(prepared.blocks) == len(factory.sealed)

    def test_it_is_frozen(self, prepared: PreparedBlocks) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            prepared.name = "somewhere-else"  # type: ignore[misc]


class TestOnlyWholeUnitsCanBeIngested:
    """A source-level guard: a frame-level path must not be expressible.

    The runtime tests above prove the *current* code appends whole units; this
    proves no second ingestion call site exists to grow one later. Deliberately
    crude, in the shape of ``tests/test_conveyor/test_layering.py``: a call to a
    writer method named ``append_*`` may only be ``append_unit`` (a plain
    ``list.append`` has no underscore and is not matched), and none of the
    frame-level names molnex does not have may be called at all.
    """

    _FRAME_LEVEL_NAMES = frozenset(
        {
            "append_frame",
            "append_frames",
            "add_frame",
            "add_frames",
            "write_frame",
            "write_frames",
            "extend_frames",
        }
    )

    @staticmethod
    def _called_attribute_names() -> set[str]:
        tree = ast.parse(_PREPARE_SOURCE.read_text(encoding="utf-8"))
        return {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

    def test_the_only_ingestion_call_is_append_unit(self) -> None:
        called = {name for name in self._called_attribute_names() if name.startswith("append_")}
        assert called == {"append_unit"}

    def test_no_frame_level_ingestion_call_exists(self) -> None:
        assert self._called_attribute_names() & self._FRAME_LEVEL_NAMES == set()
