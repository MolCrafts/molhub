"""Tests for content-first dataset description.

Mirrors ``src/molhub/loader/info.py``. These are dataclass-level tests: what
:class:`~molhub.loader.info.Feature` derives from the declaration sets, what
fields :class:`~molhub.loader.info.SplitInfo` and
:class:`~molhub.loader.info.DatasetInfo` carry, and — ac-002 — that none of
those fields can say ``shard-``. The wiring (a real manifest, a real split
table, real counts) is ``test_builder.py``'s.

Shapes picked here because a test cannot call them otherwise:

* ``Feature.declared(name, schema=..., manifest=...)`` is the alternate
  constructor that performs the level/units derivation. The spec assigns that
  derivation to ``info.py`` and names exactly three types in it, so it hangs on
  the type it produces rather than on a free function.
* ``Feature.units`` defaults to ``""``: "a dataset that declares no units
  renders ``units=''``" is a statement about the field's absent value.

**The collision ruling is pinned deliberately.** ``THEMolHessian`` declares
``hessian`` in ``TARGET_SCHEMA.graph_level`` — because ``TargetSchema`` has only
the two layout sets — while ``hf-facade-02`` made the Hessian a COO *block* on
the frame. When the new ``blocks`` declaration names it too, ``blocks`` wins:
the block declaration is the one that describes the record as it now is, and
resolving the other way would render ``level="meta"`` for a thing that is not in
``frame.meta``.
"""

from __future__ import annotations

import dataclasses

import pytest

from molhub.coordinate import Coordinate
from molhub.dataset.definition import DatasetManifest
from molhub.dataset.protocol import TargetSchema
from molhub.dataset.themol import THEMolHessian, THEMolMBIS, THEMolTorsionScan
from molhub.loader.info import DatasetInfo, Feature, SplitInfo

from .conftest import CITATION, COORDINATE, DESCRIPTION, DOWNLOAD_SIZE, LICENSE


class TestFeature:
    """One declared name, one level, one unit string — and nothing else."""

    @pytest.fixture
    def schema(self) -> TargetSchema:
        """``THEMolHessian``'s two layout sets, plus a per-atom name."""
        return TargetSchema(
            graph_level=frozenset({"energy", "hessian"}),
            atom_level=frozenset({"forces"}),
        )

    @pytest.fixture
    def manifest(self) -> DatasetManifest:
        """The declaration with the two new optional fields the spec adds."""
        return DatasetManifest(
            coordinate=Coordinate.parse("dataset:themol/hessian@1"),
            description="THEMol equilibrium geometries and Cartesian Hessians.",
            license="CC-BY-NC-4.0",
            citation="10.48550/arXiv.2605.14973",
            units={"energy": "kcal/mol", "hessian": "kcal/mol/angstrom^2"},
            blocks=("hessian",),
        )

    def test_it_declares_exactly_the_three_content_fields(self):
        assert tuple(field.name for field in dataclasses.fields(Feature)) == (
            "name",
            "level",
            "units",
        )

    def test_it_is_frozen(self):
        feature = Feature(name="energy", level="meta", units="kcal/mol")
        with pytest.raises(dataclasses.FrozenInstanceError):
            feature.units = "hartree"

    def test_undeclared_units_render_as_the_empty_string(self):
        """A dataset that declares no units says so with ``""``, not with ``None``."""
        assert Feature(name="forces", level="atom").units == ""

    def test_an_atom_level_name_is_an_atom_feature(self, schema, manifest):
        assert Feature.declared("forces", schema=schema, manifest=manifest).level == "atom"

    def test_a_graph_level_name_is_a_meta_feature(self, schema, manifest):
        """Graph-level targets live in ``frame.meta``, which is what the user sees."""
        assert Feature.declared("energy", schema=schema, manifest=manifest).level == "meta"

    def test_a_declared_block_is_a_block_feature(self, schema, manifest):
        assert Feature.declared("hessian", schema=schema, manifest=manifest).level == "block"

    def test_a_block_declaration_outranks_graph_level(self, schema, manifest):
        """The 02 finding, reconciled: ``graph_level`` now names a COO block."""
        assert "hessian" in schema.graph_level
        assert "hessian" in manifest.blocks
        assert Feature.declared("hessian", schema=schema, manifest=manifest).level == "block"

    def test_units_come_from_the_manifests_declaration(self, schema, manifest):
        assert (
            Feature.declared("hessian", schema=schema, manifest=manifest).units
            == "kcal/mol/angstrom^2"
        )

    def test_a_name_the_manifest_declares_no_unit_for_renders_empty(self, schema, manifest):
        assert Feature.declared("forces", schema=schema, manifest=manifest).units == ""

    def test_the_derived_name_is_carried_verbatim(self, schema, manifest):
        assert Feature.declared("energy", schema=schema, manifest=manifest).name == "energy"

    @pytest.mark.parametrize("name", ["forces", "energy", "hessian"])
    def test_every_derived_level_is_one_of_the_three(self, schema, manifest, name):
        assert Feature.declared(name, schema=schema, manifest=manifest).level in {
            "atom",
            "meta",
            "block",
        }

    # -- what the shipped THEMol declarations actually render ------------
    #
    # The three fixtures above are synthetic; these read the real `@dataset`
    # declarations of `molhub.dataset.themol`. Every expected unit is a string
    # literal and `THEMOL_UNITS` is deliberately *not* imported: a pin that
    # computed its expectation from the same dict the code reads would pass
    # whatever that dict were edited to say, which is the one edit worth
    # catching (a unit is a scientific claim, not a label).

    @pytest.mark.parametrize(
        ("name", "units"),
        [
            ("atomic_charge", "e"),
            ("atomic_volume", "angstrom^3"),
            ("dipole_x", "e*angstrom"),
            ("quadrupole_zz", "e*angstrom^2"),
        ],
    )
    def test_the_mbis_declaration_renders_its_atom_columns_with_units(self, name, units):
        feature = Feature.declared(
            name, schema=THEMolMBIS.TARGET_SCHEMA, manifest=THEMolMBIS.manifest
        )
        assert (feature.name, feature.level, feature.units) == (name, "atom", units)

    def test_the_hessian_declaration_renders_a_block_in_kcal_per_mol_per_square_angstrom(self):
        """The COO block of `hf-facade-02`, described as one: level and unit together."""
        feature = Feature.declared(
            "hessian", schema=THEMolHessian.TARGET_SCHEMA, manifest=THEMolHessian.manifest
        )
        assert (feature.name, feature.level, feature.units) == (
            "hessian",
            "block",
            "kcal/mol/angstrom^2",
        )

    def test_the_torsion_scan_declaration_renders_its_scanned_angle_in_degrees(self):
        """`torsion_angle` is a per-frame `meta` scalar, and degrees are not radians."""
        feature = Feature.declared(
            "torsion_angle",
            schema=THEMolTorsionScan.TARGET_SCHEMA,
            manifest=THEMolTorsionScan.manifest,
        )
        assert (feature.name, feature.level, feature.units) == (
            "torsion_angle",
            "meta",
            "degree",
        )


class TestSplitInfo:
    """A split is a name, a count and a sentence saying where the count came from."""

    def test_it_declares_exactly_the_three_fields(self):
        assert tuple(field.name for field in dataclasses.fields(SplitInfo)) == (
            "name",
            "num_examples",
            "provenance",
        )

    def test_it_carries_what_it_was_given(self):
        split = SplitInfo(name="train", num_examples=3, provenance=COORDINATE)
        assert (split.name, split.num_examples, split.provenance) == ("train", 3, COORDINATE)

    def test_it_is_frozen(self):
        split = SplitInfo(name="train", num_examples=3, provenance=COORDINATE)
        with pytest.raises(dataclasses.FrozenInstanceError):
            split.num_examples = 4


class TestDatasetInfo:
    """What a user is told before any bytes move — and what they are never told."""

    @pytest.fixture
    def info(self) -> DatasetInfo:
        return DatasetInfo(
            coordinate=Coordinate.parse(COORDINATE),
            description=DESCRIPTION,
            citation=CITATION,
            license=LICENSE,
            features=(
                Feature(name="atomic_charge", level="atom", units="e"),
                Feature(name="atomic_volume", level="atom"),
            ),
            splits=(
                SplitInfo(name="train", num_examples=3, provenance="dataset:molcrafts/x@1"),
                SplitInfo(name="val", num_examples=2, provenance="dataset:molcrafts/x@1"),
            ),
            record_type="Frame",
            download_size=DOWNLOAD_SIZE,
        )

    def test_it_declares_the_content_fields_ac_002_names(self):
        assert {field.name for field in dataclasses.fields(DatasetInfo)} == {
            "coordinate",
            "description",
            "citation",
            "license",
            "features",
            "splits",
            "record_type",
            "download_size",
        }

    def test_the_coordinate_echoes_the_resolved_one(self, info):
        """So a run can record what it actually read, not what it asked for."""
        assert info.coordinate.canonical == COORDINATE

    def test_it_is_frozen(self, info):
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.description = "something else"

    def test_no_rendered_field_names_a_shard_role(self, info):
        """ac-002, made mechanical: 「用户怎么知道shard-000是什么东西」 — they never meet it."""
        rendered = {
            field.name: str(getattr(info, field.name)) for field in dataclasses.fields(info)
        }
        offenders = {name: value for name, value in rendered.items() if "shard-" in value}
        assert offenders == {}, f"a shard role leaked into {sorted(offenders)}"

    def test_the_whole_record_renders_without_a_shard_role(self, info):
        """Not only the fields one at a time: ``repr`` is what a notebook prints."""
        assert "shard-" not in repr(info)
