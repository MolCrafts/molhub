"""Tests for the dataset builder — the HF ``load_dataset_builder`` half.

Mirrors ``src/molhub/loader/builder.py``. The builder is constructed with the
two seams the spec gives it, ``registry=`` and ``hub=``, over the synthetic
registry and the counting fake hub from ``tests/test_loader/conftest.py``; the
split derivation sits under a ``tmp_path`` ``$MOLHUB_HOME``, which is where D6
says a table-backed split lives.

``.info`` is a property, as HuggingFace spells it, and it is **fetch-free**: a
table-backed split's counts come from one gz CSV, and a manifest's
``download_size`` from the declared sizes. ac-004 pins that for ``len(ds)``;
the same discipline has to hold for the description, or "look before you
download" is not what the façade offers.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

import pytest

import molhub.loader
from molhub.conveyor.splits import SplitProvenanceMismatch
from molhub.dataset.protocol import Dataset
from molhub.dataset.threebpa import ThreeBPADataset
from molhub.loader.builder import DatasetBuilder, SplitDeclaration, ThreeBPASplits
from molhub.registry import Registry

from .conftest import (
    CITATION,
    COORDINATE,
    DESCRIPTION,
    DOWNLOAD_SIZE,
    GENERATOR_MODULE,
    LICENSE,
    SPLIT_COUNTS,
    SPLIT_SUBPATH,
    SPLIT_TABLE_COMMAND,
    SPLIT_TABLE_INPUTS,
    FakeHub,
    build_registry,
    corrupt_split_table,
    write_split_derivation,
)

#: Every feature ``THEMolMBIS`` declares — the names a reader will actually find
#: on a record, hard-coded so a schema edit shows up here as a decision rather
#: than as a silently-tracking assertion.
#:
#: ``mbis_shells`` joined them when the MBIS reader learned that the source
#: ``parameters`` array is shell-major ``(S, 3)`` and not a per-atom ``(N,
#: arity)`` one (``src/molhub/dataset/themol.py``, probe recorded in
#: ``tests/test_dataset/test_themol.py``). It is the one MBIS feature that is
#: **not** an ``atoms`` column, which is why the level map below is a map.
MBIS_FEATURE_LEVELS: Mapping[str, str] = {
    "atomic_charge": "atom",
    "atomic_volume": "atom",
    "dipole_x": "atom",
    "dipole_y": "atom",
    "dipole_z": "atom",
    "mbis_shells": "block",
    "quadrupole_xx": "atom",
    "quadrupole_xy": "atom",
    "quadrupole_xz": "atom",
    "quadrupole_yx": "atom",
    "quadrupole_yy": "atom",
    "quadrupole_yz": "atom",
    "quadrupole_zx": "atom",
    "quadrupole_zy": "atom",
    "quadrupole_zz": "atom",
}
MBIS_FEATURE_NAMES: tuple[str, ...] = tuple(MBIS_FEATURE_LEVELS)

#: Every artifact ``DatasetBuilder.DECLARATIONS`` carries an entry for, by
#: unversioned coordinate and sorted. Hard-coded: the whole point of a
#: declarative table is that adding a dataset to it is a decision, so it shows
#: up here as a diff rather than as a set that tracks whatever the table says.
#:
#: ``dataset:molcrafts/water-les`` is **gone** (reachability wave, ruling 4): no
#: registry molhub ships declares that coordinate, so its entry could only ever
#: resolve to :class:`~molhub.registry.UnknownArtifact` — a row promising a
#: dataset the product cannot address is worse than no row, because
#: ``DECLARATIONS`` is what a reader consults to find out what is loadable.
DECLARED_DATASETS: list[str] = [
    "dataset:espaloma/phalkethoh-mm-small",
    "dataset:espaloma/zinc-typing",
    "dataset:molcrafts/3bpa",
    "dataset:themol/hessian",
    "dataset:themol/mbis",
    "dataset:themol/torsion-scan",
]

#: The two THEMol artifacts the table deliberately omits: ``class1-universal-
#: splits@1`` publishes no table for them, and mapping them onto a sibling's
#: table would be inventing an answer (``builder.py`` module comment).
UNTABLED_THEMOL: list[str] = ["themol/hessian-relax", "themol/torsion-relax"]

#: What ``DatasetInfo.record_type`` says for a dataset the table does not reach:
#: the builder gets there through the declaration entry, so with no entry there
#: is no class to read a parameterized record type off.
UNDECLARED_RECORD_TYPE = "Frame | Trajectory"

#: Two 3BPA structures' worth of extended XYZ, energy tag and forces included —
#: the shape ``ThreeBPADataset`` parses. Distinct per-file structure counts (see
#: :data:`THREEBPA_COUNTS`) make reading the wrong file visible.
THREEBPA_STRUCTURE = (
    "3\n"
    'Lattice="20 0 0 0 20 0 0 0 20" Properties=species:S:1:pos:R:3:forces:R:3 energy=-1.5\n'
    "C 0.00000 0.00000 0.00000 0.10000 0.20000 0.30000\n"
    "H 1.00000 0.00000 0.00000 0.40000 0.50000 0.60000\n"
    "H 0.00000 1.00000 0.00000 0.70000 0.80000 0.90000\n"
)

#: How many structures each fixture file holds. All four differ, so a count that
#: came from the wrong role cannot pass.
THREEBPA_COUNTS: dict[str, int] = {
    "train_300K": 3,
    "test_300K": 2,
    "test_600K": 1,
    "test_1200K": 4,
}


def loader_error(name: str) -> type[BaseException]:
    """The loader-layer exception class *name*, resolved when it is asked for.

    ``SplitTableUnavailable`` and ``UnknownSplit`` are what this wave adds to
    :mod:`molhub.loader`. Importing them at module scope while they do not exist
    yet would turn every other test in this file into one collection error
    instead of failures with names on them — the rule
    ``tests/test_loader/conftest.py`` already states for this package. So the
    lookup happens inside the test that needs it, and only that test fails.

    Args:
        name: The exported class name.

    Returns:
        The class, for :func:`pytest.raises` and :func:`issubclass`.
    """
    return getattr(molhub.loader, name)


def _threebpa_manifest_yaml() -> str:
    """A manifest declaring one role per published 3BPA file, as ``v1.yaml`` does."""
    artifacts = "".join(
        f"  - role: {role}\n"
        f"    filename: {role}.xyz\n"
        f"    format: extxyz\n"
        f"    size: 10\n"
        f"    locators:\n"
        f"      - fake://3bpa-{role}\n"
        for role in THREEBPA_COUNTS
    )
    return (
        "schema_version: 1\n"
        "kind: dataset\n"
        "namespace: molcrafts\n"
        "name: 3bpa\n"
        'version: "1"\n'
        "\n"
        "title: 3BPA miniature\n"
        'description: "Two-atom-type stand-in for the 3BPA benchmark files."\n'
        "license: MIT\n"
        "doi: 10.1021/acs.jctc.1c00647\n"
        "\n"
        "artifacts:\n" + artifacts + "\n"
        "targets:\n"
        "  graph_level: [energy]\n"
        "  atom_level: [forces]\n"
    )


class TestDatasetBuilder:
    """Describe first, fetch later — and only what was actually asked for."""

    @pytest.fixture
    def builder(self, registry, hub, molhub_home) -> DatasetBuilder:
        """A builder over the fixture registry, hub and split derivation."""
        return DatasetBuilder("themol/mbis", registry=registry, hub=hub)

    def test_info_reports_the_resolved_coordinate(self, builder):
        assert builder.info.coordinate.canonical == COORDINATE

    def test_info_describes_the_dataset_without_fetching_bytes(self, builder, hub):
        """Discovery that downloads 28.9 GiB first is not discovery."""
        assert builder.info.features
        assert hub.fetch_count == 0

    def test_info_carries_the_declared_prose(self, builder):
        info = builder.info
        assert info.description == DESCRIPTION
        assert info.license == LICENSE
        assert info.citation == CITATION

    def test_info_features_are_the_declared_target_names(self, builder):
        names = tuple(sorted(feature.name for feature in builder.info.features))
        assert names == MBIS_FEATURE_NAMES
        assert len(names) == 15

    def test_every_mbis_feature_is_reported_at_the_level_it_lives_at(self, builder):
        """Fourteen ``atoms`` columns and one block: the Slater shells are one row
        per *shell*, so calling them per-atom would be the reader's old bug."""
        assert {
            feature.name: feature.level for feature in builder.info.features
        } == MBIS_FEATURE_LEVELS

    def test_info_splits_count_the_split_table(self, builder):
        assert {split.name: split.num_examples for split in builder.info.splits} == dict(
            SPLIT_COUNTS
        )

    def test_info_splits_name_the_derivation_the_counts_came_from(self, builder):
        """A count with no provenance is a number nobody can re-derive."""
        assert all("class1-universal-splits" in split.provenance for split in builder.info.splits)

    def test_info_reports_what_one_record_is(self, builder):
        """02's ruling, surfaced: an MBIS record is one ``molpy.Frame``."""
        assert "Frame" in str(builder.info.record_type)

    def test_info_download_size_is_every_declared_byte(self, builder):
        assert builder.info.download_size == DOWNLOAD_SIZE == 11101

    def test_no_rendered_field_of_a_built_info_names_a_shard_role(self, builder):
        """ac-002 where it has teeth: the manifest this was built from has three."""
        info = builder.info
        rendered = {
            field.name: str(getattr(info, field.name)) for field in dataclasses.fields(info)
        }
        offenders = {name: value for name, value in rendered.items() if "shard-" in value}
        assert offenders == {}, f"a shard role leaked into {sorted(offenders)}"

    def test_an_explicit_revision_reaches_resolution(self, registry, hub, molhub_home):
        """``revision`` is HF's spelling of ``@version`` — not a git sha."""
        builder = DatasetBuilder("themol/mbis", revision="9", registry=registry, hub=hub)
        with pytest.raises(KeyError) as raised:
            builder.info
        assert "@9" in str(raised.value)

    def test_split_view_is_a_map_style_dataset(self, builder):
        view = builder.split_view("train")
        assert isinstance(view, Dataset)
        assert len(view) == 3

    def test_split_view_reads_the_records_of_that_split(self, builder):
        assert builder.split_view("train")[0].meta["source_record_id"] == "mbis-a"

    # -- what a builder says when it is echoed -----------------------------
    #
    # `load_dataset_builder("themol/mbis")` at a prompt prints the default
    # `<molhub.loader.builder.DatasetBuilder object at 0x7f…>`, which answers
    # neither "which dataset is this" nor "which version did it resolve to" —
    # and the version is the one fact a run has to be able to record. Resolving
    # it reads the registry and no shard bytes, which is what makes it printable.

    def test_repr_names_the_resolved_coordinate(self, builder):
        assert COORDINATE in repr(builder)

    def test_repr_is_not_the_default_object_repr(self, builder):
        assert "object at 0x" not in repr(builder)

    def test_repr_fetches_nothing(self, builder, hub):
        """Echoing a builder must not cost what opening one costs."""
        repr(builder)
        assert hub.fetch_count == 0

    def test_repr_of_a_name_the_registry_does_not_declare_still_renders(
        self, registry, hub, molhub_home
    ):
        """A repr that raises is one a debugger cannot print, which is exactly
        when it is needed: the resolution failure belongs to ``.info``, not to
        looking at the object. It falls back to the name that was asked for."""
        unresolvable = DatasetBuilder("themol/not-a-dataset", registry=registry, hub=hub)
        assert "themol/not-a-dataset" in repr(unresolvable)

    def test_an_unknown_split_names_the_declared_ones(self, builder):
        """Discovery is ``info.splits``, so a miss says what discovery would have."""
        with pytest.raises(KeyError) as raised:
            builder.split_view("validation")
        message = str(raised.value)
        assert "train" in message and "val" in message and "test" in message

    # -- the delegation table itself -------------------------------------

    def test_the_delegation_table_is_a_read_only_mapping(self):
        """Declarative dispatch: a table to look a dataset up in, not a branch."""
        assert isinstance(DatasetBuilder.DECLARATIONS, Mapping)
        with pytest.raises(TypeError):
            DatasetBuilder.DECLARATIONS["dataset:molcrafts/qm9"] = None  # type: ignore[index]

    def test_the_delegation_table_declares_exactly_these_datasets(self):
        assert sorted(DatasetBuilder.DECLARATIONS) == DECLARED_DATASETS

    def test_every_entry_of_the_delegation_table_is_a_split_declaration(self):
        """One entry type, so the builder never branches on which dataset it holds."""
        assert [
            isinstance(entry, SplitDeclaration) for entry in DatasetBuilder.DECLARATIONS.values()
        ] == [True] * 6

    def test_every_declared_dataset_is_one_the_bundled_registry_can_address(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A row for a coordinate nobody publishes is a promise molhub cannot keep.

        The bundled snapshot, not ``$MOLHUB_REGISTRY``: what ships in the wheel
        is what a reader with no configuration gets, and it is the only registry
        ``DECLARATIONS`` can honestly be checked against.
        """
        monkeypatch.delenv("MOLHUB_REGISTRY", raising=False)
        published = {
            manifest.coordinate.unversioned for manifest in Registry.load().search(kind="dataset")
        }
        assert sorted(set(DatasetBuilder.DECLARATIONS) - published) == []

    def test_an_unknown_split_is_the_loaders_own_key_error(self, builder):
        """One type for one refusal, table-backed flavour included."""
        with pytest.raises(loader_error("UnknownSplit")):
            builder.split_view("validation")

    @pytest.mark.parametrize("name", UNTABLED_THEMOL)
    def test_the_two_relax_datasets_are_deliberately_untabled(self, name):
        """`class1-universal-splits@1` publishes no table for them, so no entry."""
        assert f"dataset:{name}" not in DatasetBuilder.DECLARATIONS

    @pytest.mark.parametrize("name", UNTABLED_THEMOL)
    def test_an_untabled_dataset_still_describes_itself(self, tmp_path: Path, hub, name):
        """Describable without splits: prose and size come from the manifest."""
        namespace, artifact = name.split("/")
        registry = build_registry(tmp_path / artifact, namespace=namespace, name=artifact)
        info = DatasetBuilder(name, registry=registry, hub=hub).info
        assert info.coordinate.canonical == f"dataset:{name}@1"
        assert info.description == DESCRIPTION
        assert info.download_size == DOWNLOAD_SIZE == 11101
        assert hub.fetch_count == 0

    @pytest.mark.parametrize("name", UNTABLED_THEMOL)
    def test_an_untabled_dataset_declares_no_splits(self, tmp_path: Path, hub, name):
        namespace, artifact = name.split("/")
        registry = build_registry(tmp_path / artifact, namespace=namespace, name=artifact)
        assert DatasetBuilder(name, registry=registry, hub=hub).info.splits == ()

    @pytest.mark.parametrize("name", UNTABLED_THEMOL)
    def test_an_untabled_dataset_refuses_to_open_a_split(self, tmp_path: Path, hub, name):
        """A refusal that names the artifact, rather than a split invented for it."""
        namespace, artifact = name.split("/")
        registry = build_registry(tmp_path / artifact, namespace=namespace, name=artifact)
        with pytest.raises(KeyError) as raised:
            DatasetBuilder(name, registry=registry, hub=hub).split_view("train")
        message = str(raised.value)
        assert f"dataset:{name}@1" in message
        assert "declares no splits in this molhub" in message
        assert "'train'" in message

    def test_a_dataset_outside_the_table_describes_with_no_splits(self, tmp_path: Path, hub):
        """qm9 is in the registry and in no entry: whole content, one view."""
        registry = build_registry(tmp_path / "qm9", namespace="molcrafts", name="qm9")
        info = DatasetBuilder("molcrafts/qm9", registry=registry, hub=hub).info
        assert info.splits == ()
        assert info.record_type == UNDECLARED_RECORD_TYPE
        assert hub.fetch_count == 0


class TestThreeBPASplits:
    """The one declared-split entry that does not take ``split=``.

    ``ThreeBPADataset`` takes a required positional path and a ``tag``, and the
    tag doubles as the manifest role, so this entry resolves the path through
    the hub itself. The whole adapter is exercised here over a fake hub serving
    four miniature extended-XYZ files — no network, no ``$MOLHUB_HOME``.

    **These tests are RED against the code as landed.**
    ``src/molhub/loader/builder.py:314`` declares
    ``NAMES = ("train", "test_300K", "test_600K", "test_1200K")``, but the
    published training file — the manifest role at
    ``src/molhub/registry_data/dataset/molcrafts/3bpa/v1.yaml`` and the tag
    ``ThreeBPADataset.SPLITS`` accepts — is ``train_300K``. ``view()`` fetches
    ``roles=[split]``, so the name ``"train"`` addresses a role no 3BPA manifest
    has. Because ``.info`` counts *every* declared name, that also takes down
    ``split_view("test_300K")``: no split of 3BPA can be described or opened
    through the façade. The fix is one line — ``"train"`` → ``"train_300K"`` —
    and these tests pin the fixed behaviour, not the broken one.
    """

    @pytest.fixture
    def files(self, tmp_path: Path) -> dict[str, Path]:
        """One miniature extended-XYZ file per published role."""
        root = tmp_path / "3bpa"
        root.mkdir()
        paths: dict[str, Path] = {}
        for role, count in THREEBPA_COUNTS.items():
            path = root / f"{role}.xyz"
            path.write_text(THREEBPA_STRUCTURE * count, encoding="utf-8")
            paths[role] = path
        return paths

    @pytest.fixture
    def registry(self, tmp_path: Path) -> Registry:
        """A registry declaring ``dataset:molcrafts/3bpa@1`` with its four roles."""
        path = tmp_path / "3bpa-registry" / "dataset" / "molcrafts" / "3bpa" / "1.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(_threebpa_manifest_yaml(), encoding="utf-8")
        return Registry.load(tmp_path / "3bpa-registry")

    @pytest.fixture
    def hub(self, files: dict[str, Path]) -> FakeHub:
        """A counting hub over the four published files.

        Shadows the module-level ``hub`` fixture on purpose: the claims below
        are about *which roles this dataset's hub was asked for*, and that is
        only readable from the hub the builder was actually handed.
        """
        return FakeHub(files)

    @pytest.fixture
    def builder(self, registry: Registry, hub: FakeHub) -> DatasetBuilder:
        return DatasetBuilder("molcrafts/3bpa", registry=registry, hub=hub)

    def test_the_entry_names_the_four_published_files(self):
        """Each name is also the manifest role, because ``view`` fetches by it."""
        assert ThreeBPASplits.NAMES == ("train_300K", "test_300K", "test_600K", "test_1200K")

    def test_the_entry_names_exactly_the_tags_the_dataset_accepts(self):
        """The tag is the split is the role — one spelling, three declarations."""
        assert frozenset(ThreeBPASplits.NAMES) == ThreeBPADataset.SPLITS

    def test_info_counts_every_published_file(self, builder: DatasetBuilder):
        """Declared splits are exact and cost the file: four files, four counts."""
        assert {split.name: split.num_examples for split in builder.info.splits} == {
            "train_300K": 3,
            "test_300K": 2,
            "test_600K": 1,
            "test_1200K": 4,
        }

    def test_split_view_opens_that_files_records_under_its_tag(self, builder: DatasetBuilder):
        view = builder.split_view("test_600K")
        assert isinstance(view, ThreeBPADataset)
        assert view.tag == "test_600K"
        assert len(view) == 1
        assert view[0].meta["energy"] == -1.5

    # -- reachability, ruling 3: the name is checked before the bytes ------
    #
    # A declared-split dataset states its split names as a class attribute, so
    # deciding whether ``"typo"`` is one of them is free. Today the builder asks
    # ``info.splits`` instead, which for this flavour *constructs every split* —
    # so a typo downloads all four published files and only then says the name
    # was wrong, and opening one split downloads the other three. Both are pinned
    # here as fetch ledgers, because "it was slow" is not a failing assertion and
    # a number of fetches is.

    def test_an_unknown_split_is_refused_before_a_single_fetch(
        self, builder: DatasetBuilder, hub: FakeHub
    ):
        """Validating a name against a class attribute cannot cost a download."""
        with pytest.raises(loader_error("UnknownSplit")):
            builder.split_view("typo")
        assert hub.roles_fetched == ()

    def test_an_unknown_split_names_the_declared_ones(self, builder: DatasetBuilder):
        with pytest.raises(loader_error("UnknownSplit")) as raised:
            builder.split_view("typo")
        message = str(raised.value)
        assert all(name in message for name in ThreeBPASplits.NAMES)

    def test_the_unknown_split_error_is_still_a_key_error(self, builder: DatasetBuilder):
        """``load_dataset`` has always documented ``KeyError``; the type narrows it."""
        assert issubclass(loader_error("UnknownSplit"), KeyError)
        with pytest.raises(KeyError):
            builder.split_view("typo")

    def test_the_unknown_split_message_is_not_quote_mangled(self, builder: DatasetBuilder):
        """``KeyError.__str__`` is ``repr(args[0])``: a sentence comes back quoted.

        The refusal is prose — it lists the declared names — so rendering it as
        ``"molcrafts/3bpa declares splits [...]"`` with the quotes baked in is a
        message that reads like a broken dict lookup.
        """
        with pytest.raises(loader_error("UnknownSplit")) as raised:
            builder.split_view("typo")
        assert str(raised.value) == raised.value.args[0]

    def test_opening_one_split_fetches_only_that_splits_file(
        self, builder: DatasetBuilder, hub: FakeHub
    ):
        """Four published files, one asked for: the other three are not this call's."""
        builder.split_view("test_600K")
        assert hub.roles_fetched == ("test_600K",)

    def test_opening_one_split_costs_one_fetch(self, builder: DatasetBuilder, hub: FakeHub):
        assert hub.fetch_count == 0
        builder.split_view("train_300K")
        assert hub.fetch_count == 1


class TestSplitTableAvailability:
    """Absent split table ≠ corrupt split table — two states, two answers.

    ``$MOLHUB_HOME/derived/molcrafts/class1-universal-splits/1/`` is a
    *derivation*: nothing downloads it, because nobody publishes it. A reader who
    has never built it is in the ordinary first-run state, and the only useful
    thing to tell them is the command that builds it and what that build costs. A
    reader whose table no longer hashes to what its own ``metadata.json``
    recorded is in a different state entirely — the bytes moved under them — and
    the only useful thing to tell them is which file, and to rewrite it.

    Today both states arrive as :class:`SplitProvenanceMismatch` carrying a
    chained ``FileNotFoundError`` and the sentence "re-run the generator", which
    names no generator. ``molhub`` ships one now
    (:data:`~tests.test_loader.conftest.GENERATOR_MODULE`), so both messages can
    name a command the reader can type; only the absent case gets its own type.
    """

    @pytest.fixture
    def builder(self, registry: Registry, hub: FakeHub, bare_molhub_home: Path) -> DatasetBuilder:
        """A builder over a home whose ``derived/`` directory does not exist."""
        return DatasetBuilder("themol/mbis", registry=registry, hub=hub)

    @staticmethod
    def _absent(builder: DatasetBuilder) -> BaseException:
        """Open a split with no derivation on disk and return what came back."""
        with pytest.raises(loader_error("SplitTableUnavailable")) as raised:
            builder.split_view("train")
        return raised.value

    def test_an_absent_derivation_is_its_own_error(self, builder: DatasetBuilder):
        """Not a mismatch: nothing mismatches when nothing was ever written."""
        assert type(self._absent(builder)) is loader_error("SplitTableUnavailable")

    def test_the_refusal_names_the_dataset_that_was_asked_for(self, builder: DatasetBuilder):
        """The reader typed ``themol/mbis``; a message about a derivation they
        have never heard of has to say which of their calls provoked it."""
        assert COORDINATE in str(self._absent(builder))

    def test_the_refusal_names_the_derivation_that_is_missing(self, builder: DatasetBuilder):
        assert "class1-universal-splits" in str(self._absent(builder))

    def test_the_refusal_names_where_it_looked(self, builder: DatasetBuilder, bare_molhub_home):
        """A path the reader can ``ls``, not "under your molhub home somewhere"."""
        expected = bare_molhub_home.joinpath(*SPLIT_SUBPATH)
        assert str(expected) in str(self._absent(builder))

    def test_the_refusal_names_the_command_that_builds_it(self, builder: DatasetBuilder):
        """Re-run *what*? A message naming no generator is not an instruction."""
        assert SPLIT_TABLE_COMMAND in str(self._absent(builder))

    def test_the_refusal_names_what_that_build_reads(self, builder: DatasetBuilder):
        """The build needs all three THEMol index files, not just this dataset's."""
        message = str(self._absent(builder))
        assert [source for source in SPLIT_TABLE_INPUTS if source not in message] == []
        assert "index" in message

    def test_the_refusal_says_the_build_may_have_to_download(self, builder: DatasetBuilder):
        """Three index files nobody has cached is a multi-gigabyte errand, and a
        command that turns out to cost 5 GB is one nobody should type blind."""
        assert "GB" in str(self._absent(builder))

    def test_describing_the_dataset_raises_the_same_refusal(self, builder: DatasetBuilder):
        """``.info`` counts a table-backed split off the table, so it needs one too."""
        with pytest.raises(loader_error("SplitTableUnavailable")):
            builder.info

    def test_looking_for_an_absent_derivation_creates_nothing(
        self, builder: DatasetBuilder, bare_molhub_home: Path
    ):
        """Reading a location creates nothing — including the directory it read.

        ``DerivedLayout.artifact_dir`` makes the directory it returns, so asking
        it where the tables *would* live leaves an empty derivation directory
        behind, and the next reader finds a directory that exists and is empty.
        """
        self._absent(builder)
        assert not (bare_molhub_home / "derived").exists()

    def test_a_derivation_that_does_not_verify_is_a_different_error(
        self, builder: DatasetBuilder, bare_molhub_home: Path
    ):
        """Bytes that moved after they were written: the record still exists."""
        corrupt_split_table(write_split_derivation(bare_molhub_home.joinpath(*SPLIT_SUBPATH)))
        with pytest.raises(SplitProvenanceMismatch) as raised:
            builder.split_view("train")
        assert type(raised.value) is SplitProvenanceMismatch

    def test_the_mismatch_names_the_module_that_rewrites_the_table(
        self, builder: DatasetBuilder, bare_molhub_home: Path
    ):
        """The derivation on disk records the *legacy* ``scripts/`` path in its
        own ``metadata.json`` (:data:`~tests.test_loader.conftest.SPLIT_GENERATOR`),
        so echoing that field is not naming a runnable command — the message has
        to state the module molhub actually ships."""
        corrupt_split_table(write_split_derivation(bare_molhub_home.joinpath(*SPLIT_SUBPATH)))
        with pytest.raises(SplitProvenanceMismatch) as raised:
            builder.split_view("train")
        assert GENERATOR_MODULE in str(raised.value)


class TestEspalomaDeclarations:
    """The two entries whose payload molhub cannot assemble for you.

    ``espaloma/zinc-typing`` publishes a tarball of SDF structures and
    ``espaloma/phalkethoh-mm-small`` a zip of DGL heterographs; both dataset
    classes read a *converted* tree (``splits.json`` + ``mols/``) that only an
    offline conversion produces. So neither can be opened straight from the
    published bytes — and today both find that out by downloading them first
    (4 MB and 281 MB respectively) and raising ``FileNotFoundError`` afterwards,
    which is the download charged for nothing.

    They stay in ``DECLARATIONS`` — they are declared, addressable datasets — but
    the refusal moves in front of the fetch and says which conversion is missing.
    The type is :class:`ValueError`, matching the sibling refusal already landed
    in this layer (``SplitDeclaration._whole_file_refusal``, for a dataset
    published as whole files): both are "this dataset cannot be opened this way,
    here is what to do instead", and one refusal shape for one situation beats a
    second exception hierarchy for the same sentence.
    """

    @pytest.fixture
    def espaloma_registry(self, tmp_path: Path) -> Registry:
        """A registry declaring both espaloma artifacts at version 1."""
        root = tmp_path / "espaloma-registry"
        build_registry(root, namespace="espaloma", name="zinc-typing")
        return build_registry(root, namespace="espaloma", name="phalkethoh-mm-small")

    @pytest.fixture
    def hub(self, tmp_path: Path) -> FakeHub:
        """A hub that *can* serve the published payload — and counts being asked.

        It hands back the downloaded artifact as an empty directory, which is
        what an un-converted payload looks like to the dataset classes: neither
        of them finds the ``splits.json`` tree it needs. That is the state these
        tests are about, so the hub serves it rather than refusing the role and
        turning "it fetched too early" into a fixture error.
        """
        landed = tmp_path / "espaloma-payload"
        landed.mkdir()
        return FakeHub({"main": landed})

    @pytest.fixture
    def zinc(self, espaloma_registry: Registry, hub: FakeHub, molhub_home: Path) -> DatasetBuilder:
        return DatasetBuilder("espaloma/zinc-typing", registry=espaloma_registry, hub=hub)

    @pytest.fixture
    def phalkethoh(
        self, espaloma_registry: Registry, hub: FakeHub, molhub_home: Path
    ) -> DatasetBuilder:
        return DatasetBuilder("espaloma/phalkethoh-mm-small", registry=espaloma_registry, hub=hub)

    def test_zinc_typing_refuses_a_split_before_fetching_anything(
        self, zinc: DatasetBuilder, hub: FakeHub
    ):
        with pytest.raises(ValueError):
            zinc.split_view("train")
        assert hub.fetch_count == 0

    def test_the_zinc_refusal_names_the_payload_tree_it_needs(self, zinc: DatasetBuilder):
        """``splits.json`` beside ``mols/`` is what ``ZincTypingDataset`` reads."""
        with pytest.raises(ValueError) as raised:
            zinc.split_view("train")
        assert "splits.json" in str(raised.value)

    def test_the_zinc_refusal_names_the_dataset(self, zinc: DatasetBuilder):
        with pytest.raises(ValueError) as raised:
            zinc.split_view("train")
        assert "dataset:espaloma/zinc-typing@1" in str(raised.value)

    def test_describing_zinc_typing_downloads_nothing(self, zinc: DatasetBuilder, hub: FakeHub):
        """``.info`` is the look-before-you-download half; the manifest has prose."""
        assert zinc.info.description == DESCRIPTION
        assert hub.fetch_count == 0

    def test_zinc_typing_declares_no_split_it_cannot_count(self, zinc: DatasetBuilder):
        """An exact count means constructing the split, which needs the payload.

        ``()`` is the honest answer while the conversion is missing — the split
        *names* still exist as a class attribute, which is what validates a name.
        """
        assert zinc.info.splits == ()

    def test_phalkethoh_refuses_a_split_before_fetching_anything(
        self, phalkethoh: DatasetBuilder, hub: FakeHub
    ):
        with pytest.raises(ValueError):
            phalkethoh.split_view("train")
        assert hub.fetch_count == 0

    def test_the_phalkethoh_refusal_names_the_conversion_script(self, phalkethoh: DatasetBuilder):
        with pytest.raises(ValueError) as raised:
            phalkethoh.split_view("train")
        assert "scripts/convert_espaloma_phalkethoh_mm.py" in str(raised.value)

    def test_the_phalkethoh_refusal_names_what_that_conversion_needs(
        self, phalkethoh: DatasetBuilder
    ):
        """dgl is the reason it is offline and once: molhub does not depend on it."""
        with pytest.raises(ValueError) as raised:
            phalkethoh.split_view("train")
        assert "dgl" in str(raised.value)

    def test_describing_phalkethoh_downloads_nothing(
        self, phalkethoh: DatasetBuilder, hub: FakeHub
    ):
        assert phalkethoh.info.description == DESCRIPTION
        assert hub.fetch_count == 0

    def test_phalkethoh_declares_no_split_it_cannot_count(self, phalkethoh: DatasetBuilder):
        assert phalkethoh.info.splits == ()
