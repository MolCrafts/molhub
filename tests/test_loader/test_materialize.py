"""Tests for ``prepare`` — one split of one dataset, materialized as blocks.

Mirrors ``src/molhub/loader/materialize.py``. Nothing here imports torch or
molix, and nothing here needs them: the block writer is the injected fake below,
exactly as in ``tests/test_conveyor/test_prepare.py``, which is what the
``BlockWriterLike`` / ``BlockWriterFactory`` seam exists for. The fake is honest
about the one thing molhub reads back — on ``seal()`` it writes the five
manifest fields ``PrepareJob`` verifies — so a test can make a block *wrong*
rather than stub the check away.

**Two fixture datasets, because ``prepare`` has two answers.**

* ``dataset:themol/torsion-scan@1`` (``tests/test_loader/conftest.py``) is the
  **success** path. Every target a scan carries — ``pos``, ``energy``,
  ``forces``, ``torsion_angle`` and the scanned dihedral — has a
  ``molix.block/1`` column route, so what is exported is what was read, and a
  count is a count of the whole record rather than of the part that survived.
  Its records are genuinely split-mixed: both shards hold train, val and test
  rows, which is what makes D8's claim checkable — ``prepare(split="train")``
  feeds ``PrepareJob`` the **split-filtered** walk plus the **full** identity
  table, so out-of-split identities never arrive, only the train writer is ever
  opened, and ``UnroutableUnitError`` still fires for an identity the derivation
  genuinely never assigned.
* ``dataset:themol/mbis@1`` is the **refusal** path, and appears in this file
  for nothing else. ``molix.block/1`` routes none of its atom-level
  electrostatics targets, so exporting it can only write the geometry and drop
  the charges, volumes, dipoles, quadrupoles and Slater parameters the dataset
  exists for. That is the failure
  :class:`~molhub.conveyor.encoder.THEMolUnitEncoder`'s constructor refuses, and
  labelling a unit with the *collection role* instead of the subset name does
  not make it a different failure — so ``prepare`` refuses too, loudly, before
  ``output_dir`` exists.

Shapes picked here, because a test cannot call them otherwise:

* ``molhub.prepare(name, split=..., output_dir=..., registry=..., hub=...)`` —
  the entry ac-004 names, with the same ``registry=`` / ``hub=`` seams
  ``load_dataset`` takes.
* ``writer_factory=`` injects the block writer (default: molnex's, per ac-005),
  and ``provenance=`` injects the provenance mapping ``molix.block/1`` requires
  (default: one this layer builds, which a test below checks is complete).
* The unroutable-targets refusal is
  :class:`~molhub.conveyor.errors.UnsupportedRecordError` — the type the encoder
  already raises for exactly this, whose docstring reads "this *source* has no
  encoder yet" — and its message names the coordinate, the block format whose
  routes are missing, and what exporting anyway would drop.
"""

from __future__ import annotations

import importlib
import inspect
import json
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import molhub
from molhub.conveyor import PreparedBlocks
from molhub.conveyor.errors import (
    IncompleteProvenanceError,
    UnroutableUnitError,
    UnsupportedRecordError,
)
from molhub.loader.materialize import BlockExport

from .conftest import (
    COORDINATE,
    HOOH_IDENTITY,
    HSOH_IDENTITY,
    HSSH_IDENTITY,
    SPLIT_SUBPATH,
    TORSION_CONSTRAINTS,
    TORSION_TRAIN_KEYS,
    LandingHub,
    leaks,
    write_split_derivation,
)

#: What the train split of the torsion fixture is worth, as literals: three
#: scans — ``scan-a`` and ``scan-c`` from the first shard, ``scan-d`` from the
#: second — of 2, 3 and 2 constrained geometries, so 7 frames. Hand-derived from
#: ``TORSION_SPECIES_BY_KEY`` and ``TORSION_CONSTRAINTS``; the two numbers
#: differ, so a test cannot pass by reading the other one.
TRAIN_UNITS = 3
TRAIN_FRAMES = 7

#: The dataset whose targets ``molix.block/1`` routes none of, and the words its
#: refusal has to carry. ``molix.block/1`` is the block format itself, which
#: ac-003 does not forbid naming — it is molnex's public format identifier, not
#: the transfer machinery's vocabulary.
UNROUTABLE_DATASET = "themol/mbis"
BLOCK_FORMAT = "molix.block/1"

#: The four provenance keys molhub checks before a writer is opened. Mirrored
#: from ``molhub.conveyor.prepare`` rather than imported: a test that read the
#: value under test out of the module under test would agree with any value.
PROVENANCE_KEYS: tuple[str, ...] = ("source", "generator", "created_at", "units")

PROVENANCE: Mapping[str, Any] = {
    "source": "dataset:themol/torsion-scan@1",
    "generator": "tests.test_loader.test_materialize",
    "created_at": "2026-08-15T00:00:00Z",
    "units": {"coordinates": "angstrom"},
}


class FakeBlockWriter:
    """A ``BlockWriterLike`` that records what it was fed and seals honestly.

    ``append_unit`` takes the unit and nothing else, mirroring
    ``molnex:src/molix/store/block.py:890``, so a caller that tried to pass a
    per-unit ``split=`` would fail here instead of quietly working.

    Args:
        root: Block directory; created on construction, as the real writer does.
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
        return len(self.appended)

    @property
    def committed_bytes(self) -> int:
        return self._bytes

    @property
    def identities(self) -> tuple[str, ...]:
        """The molecular identity of every unit this block took, in arrival order."""
        return tuple(unit.identity for unit in self.appended)

    @property
    def keys(self) -> tuple[str, ...]:
        """The unit key of every unit this block took, in arrival order."""
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
        (self.root / "manifest.json").write_text(
            json.dumps(
                {
                    "format": BLOCK_FORMAT,
                    "split": self.split,
                    "units": self.unit_count,
                    "sealed": True,
                    "block_digest": self.digest,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


class RecordingWriterFactory:
    """A ``BlockWriterFactory`` — the *constructor* seam, with a log.

    Every writer is recorded at construction with its root and its single
    ``split``, which is how "only the requested split's writer was ever opened"
    is observable from outside.
    """

    def __init__(self) -> None:
        self.writers: list[FakeBlockWriter] = []

    def __call__(self, root: Path, *, split: str, provenance: Mapping[str, Any]) -> FakeBlockWriter:
        writer = FakeBlockWriter(
            root, split=split, provenance=provenance, digest=f"{len(self.writers):064x}"
        )
        self.writers.append(writer)
        return writer

    @property
    def splits(self) -> tuple[str, ...]:
        """The split every writer was opened for, in the order they were opened."""
        return tuple(writer.split for writer in self.writers)


@pytest.fixture
def factory() -> RecordingWriterFactory:
    return RecordingWriterFactory()


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Where blocks are written — deliberately absent until something creates it."""
    return tmp_path / "blocks"


@pytest.fixture
def prepared(verified_torsion_registry, torsion_hub, factory, output_dir: Path) -> PreparedBlocks:
    """The train split of the torsion fixture, materialized through a fake writer."""
    return molhub.prepare(
        "themol/torsion-scan",
        split="train",
        output_dir=output_dir,
        registry=verified_torsion_registry,
        hub=torsion_hub,
        writer_factory=factory,
        provenance=PROVENANCE,
    )


class TestPrepareReadsUserFirst:
    """The signature, in the order a reader meets it (ergonomics wave, ruling 9).

    ``registry=`` and ``hub=`` are seams — a test's, an embedder's — and they sat
    in front of ``writer_factory``, ``provenance`` and ``disk_budget``, which are
    the three a real ``prepare`` call actually reaches for. Every one of them is
    keyword-only, so the order is documentation rather than an ABI: it changes
    what ``help(prepare)`` and every rendered signature put first, and breaks no
    call anywhere.

    The same ordering rule the two reading functions are pinned to in
    ``tests/test_loader/test_init.py``: what names the data, then what selects
    it, then what shapes the output, then the injection points.
    """

    #: What ``prepare`` takes, in the order it should read. Hard-coded, because
    #: "user-first" is a decision about order and an expectation derived from the
    #: signature would agree with any order at all.
    PARAMETERS: tuple[str, ...] = (
        "name",
        "split",
        "output_dir",
        "revision",
        "disk_budget",
        "writer_factory",
        "provenance",
        "registry",
        "hub",
    )

    def test_it_declares_exactly_these_parameters(self) -> None:
        assert set(inspect.signature(molhub.prepare).parameters) == set(self.PARAMETERS)

    def test_it_reads_user_first(self) -> None:
        assert tuple(inspect.signature(molhub.prepare).parameters) == self.PARAMETERS

    def test_it_puts_the_seams_last(self) -> None:
        """Stated on its own, so a reordering that only moves ``disk_budget``
        still reports the half it did not fix."""
        assert tuple(inspect.signature(molhub.prepare).parameters)[-2:] == ("registry", "hub")

    def test_only_the_name_is_positional(self) -> None:
        """Which is what makes the order free to change: nobody passes these by
        position, so nobody's call breaks when they move."""
        parameters = inspect.signature(molhub.prepare).parameters
        assert parameters["name"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert all(
            parameters[name].kind is inspect.Parameter.KEYWORD_ONLY for name in self.PARAMETERS[1:]
        )


class TestBlockExport:
    """One split in, sealed split-pure blocks out — and a refusal without molnex."""

    # -- ac-004: what one export produces ----------------------------------

    def test_it_returns_prepared_blocks(self, prepared: PreparedBlocks) -> None:
        """The conveyor's own value, reused: ``prepare`` adds no fourth block type."""
        assert isinstance(prepared, PreparedBlocks)

    def test_the_work_has_a_type_with_a_name(self) -> None:
        """``prepare`` is a thin delegation — the export itself is a class, not a script."""
        assert isinstance(BlockExport, type)

    def test_it_seals_one_root(self, prepared: PreparedBlocks) -> None:
        """One split, one production-sized ceiling: one block, no size fan-out."""
        assert len(prepared.blocks) == 1

    def test_the_sealed_root_exists_on_disk(self, prepared: PreparedBlocks) -> None:
        assert prepared.blocks[0].root.is_dir()

    def test_the_sealed_root_sits_under_the_output_directory(
        self, prepared: PreparedBlocks, output_dir: Path
    ) -> None:
        assert prepared.blocks[0].root.parent == output_dir

    def test_every_sealed_block_is_the_requested_split(self, prepared: PreparedBlocks) -> None:
        assert {block.split for block in prepared.blocks} == {"train"}

    def test_no_other_splits_root_is_created(
        self, prepared: PreparedBlocks, output_dir: Path
    ) -> None:
        """The shards are split-mixed; only the filtered walk keeps val and test out."""
        assert [path.name for path in output_dir.iterdir()] == [prepared.blocks[0].root.name]

    def test_no_writer_is_opened_for_another_split(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        assert factory.splits == ("train",)

    def test_the_unit_count_is_the_train_scans(self, prepared: PreparedBlocks) -> None:
        """One whole scan is one unit, whatever it holds."""
        assert prepared.blocks[0].unit_count == TRAIN_UNITS == 3

    def test_the_frame_count_is_every_constrained_geometry(self, prepared: PreparedBlocks) -> None:
        """2 + 3 + 2: a unit count would say 3 here, so the two cannot be confused."""
        assert prepared.blocks[0].frame_count == TRAIN_FRAMES == 7

    def test_the_frame_count_is_the_sum_the_fixture_declares(self) -> None:
        """The literal above, re-derived from the fixture it was read off."""
        assert sum(TORSION_CONSTRAINTS[key] for key in TORSION_TRAIN_KEYS) == TRAIN_FRAMES

    def test_every_unit_is_a_whole_scan_of_the_walk(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        """In walk order: two scans out of the first shard, one out of the second."""
        assert factory.writers[0].keys == TORSION_TRAIN_KEYS

    def test_every_unit_carries_the_train_molecules_identity(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        """HSSH is the train species of the fixture; HOOH is val and HSOH is test."""
        assert factory.writers[0].identities == (HSSH_IDENTITY,) * TRAIN_UNITS

    def test_no_other_species_reaches_a_block(
        self, prepared: PreparedBlocks, factory: RecordingWriterFactory
    ) -> None:
        """The val and test molecules are in the same shards, one record apart."""
        landed = {identity for writer in factory.writers for identity in writer.identities}
        assert HOOH_IDENTITY not in landed and HSOH_IDENTITY not in landed

    def test_the_sealed_names_carry_no_conveyor_vocabulary(self, prepared: PreparedBlocks) -> None:
        """ac-003 for ``prepare``'s return value: a root name is a user-facing string."""
        names = " ".join([prepared.name, *(block.root.name for block in prepared.blocks)])
        assert leaks(names) == []

    # -- provenance ---------------------------------------------------------

    def test_the_default_provenance_is_complete(
        self,
        verified_torsion_registry,
        torsion_hub,
        factory: RecordingWriterFactory,
        output_dir: Path,
    ) -> None:
        """A caller who passes none still gets the four keys ``molix.block/1`` needs."""
        molhub.prepare(
            "themol/torsion-scan",
            split="train",
            output_dir=output_dir,
            registry=verified_torsion_registry,
            hub=torsion_hub,
            writer_factory=factory,
        )
        assert set(PROVENANCE_KEYS) <= set(factory.writers[0].provenance)

    @pytest.mark.parametrize("missing", PROVENANCE_KEYS)
    def test_incomplete_provenance_is_refused(
        self,
        verified_torsion_registry,
        torsion_hub,
        factory: RecordingWriterFactory,
        output_dir: Path,
        missing: str,
    ) -> None:
        provenance = {key: value for key, value in PROVENANCE.items() if key != missing}
        with pytest.raises(IncompleteProvenanceError):
            molhub.prepare(
                "themol/torsion-scan",
                split="train",
                output_dir=output_dir,
                registry=verified_torsion_registry,
                hub=torsion_hub,
                writer_factory=factory,
                provenance=provenance,
            )

    def test_incomplete_provenance_opens_no_writer(
        self,
        verified_torsion_registry,
        torsion_hub,
        factory: RecordingWriterFactory,
        output_dir: Path,
    ) -> None:
        provenance = {key: value for key, value in PROVENANCE.items() if key != "units"}
        with pytest.raises(IncompleteProvenanceError):
            molhub.prepare(
                "themol/torsion-scan",
                split="train",
                output_dir=output_dir,
                registry=verified_torsion_registry,
                hub=torsion_hub,
                writer_factory=factory,
                provenance=provenance,
            )
        assert factory.writers == []

    # -- D8: the full split_of, and the refusal it keeps reachable ----------

    def test_an_identity_the_derivation_never_assigned_is_refused(
        self,
        molhub_home: Path,
        verified_torsion_registry,
        torsion_hub,
        factory: RecordingWriterFactory,
        output_dir: Path,
    ) -> None:
        """Out-of-split identities never arrive; an *unassigned* one still refuses.

        The uuid table still routes ``scan-a`` to train, so the record arrives;
        the identity table no longer says which split its molecule belongs to, so
        there is nothing to route it by. No default split, no re-splitting.
        """
        write_split_derivation(
            molhub_home.joinpath(*SPLIT_SUBPATH),
            identity_rows=[(HOOH_IDENTITY, "val"), (HSOH_IDENTITY, "test")],
        )
        with pytest.raises(UnroutableUnitError):
            molhub.prepare(
                "themol/torsion-scan",
                split="train",
                output_dir=output_dir,
                registry=verified_torsion_registry,
                hub=torsion_hub,
                writer_factory=factory,
                provenance=PROVENANCE,
            )

    # -- ac-005: fail closed without molnex --------------------------------

    def test_without_molnex_the_default_writer_is_an_import_error(
        self, verified_torsion_registry, torsion_hub, output_dir: Path
    ) -> None:
        """No fake here on purpose: this is the default factory, in an install
        that has neither molix nor torch — which is the environment ac-005 is
        about, so nothing is simulated."""
        with pytest.raises(ImportError):
            molhub.prepare(
                "themol/torsion-scan",
                split="train",
                output_dir=output_dir,
                registry=verified_torsion_registry,
                hub=torsion_hub,
                provenance=PROVENANCE,
            )

    def test_the_import_error_names_the_prepare_extra(
        self, verified_torsion_registry, torsion_hub, output_dir: Path
    ) -> None:
        """A bare ``ModuleNotFoundError: No module named 'torch'`` is not an answer."""
        with pytest.raises(ImportError) as raised:
            molhub.prepare(
                "themol/torsion-scan",
                split="train",
                output_dir=output_dir,
                registry=verified_torsion_registry,
                hub=torsion_hub,
                provenance=PROVENANCE,
            )
        assert "prepare" in str(raised.value)

    def test_the_import_error_names_the_source_escape_hatch(
        self, verified_torsion_registry, torsion_hub, output_dir: Path
    ) -> None:
        """molnex is not on PyPI, so the extra alone cannot install it."""
        with pytest.raises(ImportError) as raised:
            molhub.prepare(
                "themol/torsion-scan",
                split="train",
                output_dir=output_dir,
                registry=verified_torsion_registry,
                hub=torsion_hub,
                provenance=PROVENANCE,
            )
        assert "MOLNEX_SRC" in str(raised.value)

    def test_without_molnex_no_partial_block_directory_is_written(
        self, verified_torsion_registry, torsion_hub, output_dir: Path
    ) -> None:
        """The wrap fires at writer-factory resolution, before any mkdir."""
        with pytest.raises(ImportError):
            molhub.prepare(
                "themol/torsion-scan",
                split="train",
                output_dir=output_dir,
                registry=verified_torsion_registry,
                hub=torsion_hub,
                provenance=PROVENANCE,
            )
        assert not output_dir.exists()


class TestPrepareRefusesUnroutableTargets:
    """A dataset ``molix.block/1`` has no routes for is refused, not exported.

    The encoder refuses ``task="mbis"`` because none of its atom-level
    electrostatics targets has a column route. Labelling the units with the
    collection role the dataset is *published* under is a different string for
    the same shard, and an export that succeeded on it would write geometry and
    topology and silently drop every target the dataset exists for — the exact
    outcome that refusal was written to prevent. So ``prepare`` refuses first,
    with nothing fetched and nothing created.
    """

    @staticmethod
    def _refusal(
        registry,
        hub,
        factory: RecordingWriterFactory,
        output_dir: Path,
    ) -> UnsupportedRecordError:
        """Run the refused export and return what it raised."""
        with pytest.raises(UnsupportedRecordError) as raised:
            molhub.prepare(
                UNROUTABLE_DATASET,
                split="train",
                output_dir=output_dir,
                registry=registry,
                hub=hub,
                writer_factory=factory,
                provenance=PROVENANCE,
            )
        return raised.value

    def test_it_refuses(
        self,
        verified_registry,
        landing_hub: LandingHub,
        factory: RecordingWriterFactory,
        output_dir: Path,
    ) -> None:
        """An injected writer is not the question: the targets are."""
        self._refusal(verified_registry, landing_hub, factory, output_dir)

    def test_the_refusal_creates_no_output_directory(
        self,
        verified_registry,
        landing_hub: LandingHub,
        factory: RecordingWriterFactory,
        output_dir: Path,
    ) -> None:
        """Fail closed: a half-written block directory is not a smaller failure."""
        self._refusal(verified_registry, landing_hub, factory, output_dir)
        assert not output_dir.exists()

    def test_the_refusal_opens_no_writer(
        self,
        verified_registry,
        landing_hub: LandingHub,
        factory: RecordingWriterFactory,
        output_dir: Path,
    ) -> None:
        self._refusal(verified_registry, landing_hub, factory, output_dir)
        assert factory.writers == []

    def test_the_refusal_fetches_nothing(
        self,
        verified_registry,
        landing_hub: LandingHub,
        factory: RecordingWriterFactory,
        output_dir: Path,
    ) -> None:
        """Which targets a dataset declares is known from its coordinate; a
        refusal that had to read 28.9 GiB of shards first would not be one."""
        self._refusal(verified_registry, landing_hub, factory, output_dir)
        assert landing_hub.fetch_count == 0

    def test_the_refusal_names_the_dataset(
        self,
        verified_registry,
        landing_hub: LandingHub,
        factory: RecordingWriterFactory,
        output_dir: Path,
    ) -> None:
        """The pinned coordinate, as every other refusal on this path spells it."""
        message = str(self._refusal(verified_registry, landing_hub, factory, output_dir))
        assert COORDINATE in message

    def test_the_refusal_names_the_format_whose_routes_are_missing(
        self,
        verified_registry,
        landing_hub: LandingHub,
        factory: RecordingWriterFactory,
        output_dir: Path,
    ) -> None:
        """Naming the format is what makes this actionable: the fix is a column
        space in ``molix.block/1``, not a flag here."""
        message = str(self._refusal(verified_registry, landing_hub, factory, output_dir))
        assert BLOCK_FORMAT in message
        assert "route" in message.lower()

    def test_the_refusal_says_what_exporting_anyway_would_cost(
        self,
        verified_registry,
        landing_hub: LandingHub,
        factory: RecordingWriterFactory,
        output_dir: Path,
    ) -> None:
        """ "It wrote something" is the failure mode; the message has to say so."""
        message = str(self._refusal(verified_registry, landing_hub, factory, output_dir))
        assert "drop" in message.lower()

    def test_the_refusal_carries_no_conveyor_vocabulary(
        self,
        verified_registry,
        landing_hub: LandingHub,
        factory: RecordingWriterFactory,
        output_dir: Path,
    ) -> None:
        """ac-003 holds for a refusal too — it is the message a user reads."""
        message = str(self._refusal(verified_registry, landing_hub, factory, output_dir))
        assert leaks(message) == []


def _chain(error: BaseException) -> str:
    """Every exception in *error*'s chain, rendered as one searchable string.

    A refusal that re-raises what it caught keeps the original underneath, and
    "the reason survived the wrapping" is a claim about the chain rather than
    about the outermost message. Follows ``__cause__`` first (an explicit
    ``raise ... from``) and ``__context__`` second, so an implicit chain counts
    too, and stops on a cycle.
    """
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    return "\n".join(parts)


class TestCheapRefusalsPrecedeTheSplitTable:
    """What ``prepare`` refuses for free, it refuses before reading anything.

    Two of ``prepare``'s refusals are decidable from the arguments alone: the
    dataset's targets have no column route in ``molix.block/1``, and this
    install cannot import a block writer. Both already fire before a byte is
    fetched and before ``output_dir`` exists — but they fire *after*
    ``DatasetBuilder`` has resolved the split, and resolving a split for a
    table-backed dataset loads the split derivation off disk.

    So on a machine that has never built the derivation, ``prepare`` answers
    "the split table is not here" for a call that was never going to run — and
    the reader chases a 5 GB rebuild for an export that would have refused
    anyway. Ordering is the whole claim, and the only way to observe it is to
    take the derivation away and read which refusal comes back.
    """

    @staticmethod
    def _without_derivation(home: Path) -> Path:
        """Remove the split derivation the ``molhub_home`` fixture filed."""
        shutil.rmtree(home / "derived")
        return home

    def test_an_unroutable_dataset_is_refused_without_reading_the_split_table(
        self,
        verified_registry,
        landing_hub: LandingHub,
        factory: RecordingWriterFactory,
        molhub_home: Path,
        output_dir: Path,
    ) -> None:
        """MBIS cannot be exported at all; that answer does not need a table."""
        self._without_derivation(molhub_home)
        with pytest.raises(UnsupportedRecordError):
            molhub.prepare(
                UNROUTABLE_DATASET,
                split="train",
                output_dir=output_dir,
                registry=verified_registry,
                hub=landing_hub,
                writer_factory=factory,
                provenance=PROVENANCE,
            )

    def test_a_missing_writer_is_refused_without_reading_the_split_table(
        self,
        verified_torsion_registry,
        torsion_hub: LandingHub,
        molhub_home: Path,
        output_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No molnex means no export, whichever split it would have been."""
        monkeypatch.delenv("MOLNEX_SRC", raising=False)
        self._without_derivation(molhub_home)
        with pytest.raises(ImportError):
            molhub.prepare(
                "themol/torsion-scan",
                split="train",
                output_dir=output_dir,
                registry=verified_torsion_registry,
                hub=torsion_hub,
                provenance=PROVENANCE,
            )


class TestMolnexSourceOverride:
    """``MOLNEX_SRC`` is named in the refusal, so it has to be honoured.

    molnex is not on PyPI: the ``prepare`` extra can only install torch, and the
    documented way to supply the other half is a source checkout pointed at by
    ``MOLNEX_SRC`` — which is what the refusal already tells the reader to set,
    and what ``tests/test_dataset/test_neighbor.py`` sets to reach the real
    thing. Nothing on the ``prepare`` path reads it: ``import_module`` looks
    down :data:`sys.path`, so a reader who follows the instruction gets the same
    refusal a second time and no way to tell why.

    The stub checkout below raises a marker on import. If ``MOLNEX_SRC`` is
    genuinely consulted, that marker is what comes back — a real failure from the
    checkout the reader named — instead of "no module named molix".
    """

    @pytest.fixture
    def molnex_src(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """A ``src/`` directory holding a ``molix`` that announces itself and dies.

        ``sys.path`` is replaced with a copy so that whatever the resolution
        inserts is thrown away with the fixture, and every ``molix`` module the
        attempt left behind is dropped afterwards — an import that raises is
        already removed from :data:`sys.modules`, but a partially imported
        package's parents are not.
        """
        root = tmp_path / "molnex" / "src"
        (root / "molix").mkdir(parents=True)
        (root / "molix" / "__init__.py").write_text(
            'raise RuntimeError("MOLNEX_SRC_MARKER")\n', encoding="utf-8"
        )
        monkeypatch.setenv("MOLNEX_SRC", str(root))
        monkeypatch.setattr(sys, "path", list(sys.path))
        yield root
        for name in [key for key in sys.modules if key == "molix" or key.startswith("molix.")]:
            del sys.modules[name]
        importlib.invalidate_caches()

    def test_the_writer_is_looked_for_under_molnex_src(
        self,
        verified_torsion_registry,
        torsion_hub: LandingHub,
        output_dir: Path,
        molnex_src: Path,
    ) -> None:
        """The marker is the checkout's own voice: it can only be heard from there."""
        with pytest.raises(Exception) as raised:
            molhub.prepare(
                "themol/torsion-scan",
                split="train",
                output_dir=output_dir,
                registry=verified_torsion_registry,
                hub=torsion_hub,
                provenance=PROVENANCE,
            )
        assert "MOLNEX_SRC_MARKER" in _chain(raised.value)

    def test_the_attempt_writes_no_partial_block_directory(
        self,
        verified_torsion_registry,
        torsion_hub: LandingHub,
        output_dir: Path,
        molnex_src: Path,
    ) -> None:
        """A checkout that fails to import is still fail-closed, not half-done."""
        with pytest.raises(Exception):
            molhub.prepare(
                "themol/torsion-scan",
                split="train",
                output_dir=output_dir,
                registry=verified_torsion_registry,
                hub=torsion_hub,
                provenance=PROVENANCE,
            )
        assert not output_dir.exists()

    def test_without_molnex_src_the_refusal_still_names_it(
        self,
        verified_torsion_registry,
        torsion_hub: LandingHub,
        output_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With nothing to consult, the message is the one already landed — and it
        is now telling the truth, because setting the variable does something."""
        monkeypatch.delenv("MOLNEX_SRC", raising=False)
        with pytest.raises(ImportError) as raised:
            molhub.prepare(
                "themol/torsion-scan",
                split="train",
                output_dir=output_dir,
                registry=verified_torsion_registry,
                hub=torsion_hub,
                provenance=PROVENANCE,
            )
        message = str(raised.value)
        assert "MOLNEX_SRC" in message
        assert "molhub[prepare]" in message
