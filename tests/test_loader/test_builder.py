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

from molhub.dataset.protocol import Dataset
from molhub.dataset.threebpa import ThreeBPADataset
from molhub.loader.builder import DatasetBuilder, SplitDeclaration, ThreeBPASplits
from molhub.registry import Registry

from .conftest import (
    CITATION,
    COORDINATE,
    DESCRIPTION,
    DOWNLOAD_SIZE,
    LICENSE,
    SPLIT_COUNTS,
    FakeHub,
    build_registry,
)

#: Every ``atoms`` column ``THEMolMBIS.TARGET_SCHEMA`` declares — the names a
#: reader will actually find on a record, hard-coded so a schema edit shows up
#: here as a decision rather than as a silently-tracking assertion.
MBIS_FEATURE_NAMES: tuple[str, ...] = (
    "atomic_charge",
    "atomic_volume",
    "dipole_x",
    "dipole_y",
    "dipole_z",
    "quadrupole_xx",
    "quadrupole_xy",
    "quadrupole_xz",
    "quadrupole_yx",
    "quadrupole_yy",
    "quadrupole_yz",
    "quadrupole_zx",
    "quadrupole_zy",
    "quadrupole_zz",
)

#: Every artifact ``DatasetBuilder.DECLARATIONS`` carries an entry for, by
#: unversioned coordinate and sorted. Hard-coded: the whole point of a
#: declarative table is that adding a dataset to it is a decision, so it shows
#: up here as a diff rather than as a set that tracks whatever the table says.
DECLARED_DATASETS: list[str] = [
    "dataset:espaloma/phalkethoh-mm-small",
    "dataset:espaloma/zinc-typing",
    "dataset:molcrafts/3bpa",
    "dataset:molcrafts/water-les",
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
        """Discovery that downloads 150 GB first is not discovery."""
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
        assert len(names) == 14

    def test_mbis_features_are_all_per_atom(self, builder):
        """Every MBIS target is an ``atoms`` column, so every level is ``atom``."""
        assert {feature.level for feature in builder.info.features} == {"atom"}

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
        ] == [True] * 7

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
    def builder(self, registry: Registry, files: dict[str, Path]) -> DatasetBuilder:
        return DatasetBuilder("molcrafts/3bpa", registry=registry, hub=FakeHub(files))

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
