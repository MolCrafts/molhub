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

**Two shapes the ergonomics wave adds, and why they are types here.**

* :class:`~molhub.loader.info.ByteSize` — one byte count that knows how to say
  itself. ``download_size=31041658614`` is a number a reader has to count digits
  on; ``28.9 GiB`` is the same fact and is the one they can act on. It is a
  *type* rather than a ``humanize_bytes`` free function because
  ``tests/test_loader/test_layering.py`` bounds this package to three free
  functions and because the house rules put a verb on its owning noun — and
  because two renderings of one number (one in the CLI, one in ``__str__``) is
  exactly the drift a shared type prevents.
* :meth:`~molhub.loader.info.DatasetInfo.__str__` — the dataclass ``repr`` puts
  every field of a 15-feature dataset on one line, which is where ``.info``
  stopped being readable at a notebook prompt. ``__str__`` is the human view and
  ``repr`` stays the dataclass's own: ``print(info)`` and ``info`` at a REPL are
  different questions, and Python already has two hooks for them.

The rendering literals below are computed 1024-based and written out, never
recomputed from the implementation: a golden that called the code under test
would agree with whatever it were edited to say. Two of them are real bundled
manifest totals (``dataset:themol/mbis@1`` and ``dataset:themol/hessian-relax@1``),
so the two sizes a THEMol reader actually meets are the two that are pinned.
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


def info_type(name: str) -> type:
    """The :mod:`molhub.loader.info` type *name*, resolved when it is asked for.

    The same deferred lookup ``test_builder.py``'s ``loader_error`` makes, for
    the same reason: importing a type this wave adds at module scope would turn
    every other test in this file into one collection error instead of failures
    with names on them.

    Args:
        name: The exported type name.

    Returns:
        The class.
    """
    from molhub.loader import info

    return getattr(info, name)


#: How the fixture dataset's 11 101 declared bytes read once humanized. Stated
#: as a literal beside :data:`~tests.test_loader.conftest.DOWNLOAD_SIZE`, which
#: is what ``DatasetInfo.__str__`` is asked to render.
DOWNLOAD_SIZE_HUMANIZED = "10.8 KiB"

#: The rendering contract, as (bytes, text) pairs computed with 1024-based math:
#: binary units, one decimal place, and a bare ``B`` below 1 KiB because
#: ``0.9 KiB`` is a worse answer than ``999 B``.
#:
#: The boundaries are here on purpose — 1023 is the last plain byte count, 1024
#: the first KiB — and so are the two real ones: ``31041658614`` is every
#: declared byte of ``dataset:themol/mbis@1`` and ``1048543472353`` of
#: ``dataset:themol/hessian-relax@1``, which is the number the ladder has to keep
#: in GiB (0.95 TiB is not yet a TiB).
HUMANIZED: tuple[tuple[int, str], ...] = (
    (0, "0 B"),
    (1, "1 B"),
    (999, "999 B"),
    (1023, "1023 B"),
    (1024, "1.0 KiB"),
    (1536, "1.5 KiB"),
    (11101, "10.8 KiB"),
    (1048576, "1.0 MiB"),
    (1234000, "1.2 MiB"),
    (31041658614, "28.9 GiB"),
    (1048543472353, "976.5 GiB"),
    (1099511627776, "1.0 TiB"),
)


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

    # -- the human rendering ------------------------------------------------
    #
    # `print(info)` is the first thing a reader does with a description, and the
    # dataclass repr answers it with one line carrying every field of every
    # feature and every split — for THEMol MBIS, fifteen features and three
    # splits on a single line. `__str__` is the view for that question; `repr`
    # stays the dataclass's own, because a REPL echo and a print are different
    # questions and Python already gives them different hooks.

    def test_printing_it_spans_several_lines(self, info):
        assert len(str(info).splitlines()) > 1

    def test_printing_it_leads_with_the_resolved_coordinate(self, info):
        """Which artifact, at which version — the one fact a run has to record."""
        assert str(info).splitlines()[0].strip() == COORDINATE

    @pytest.mark.parametrize(("name", "other"), [("atomic_charge", "atomic_volume")])
    def test_printing_it_gives_every_feature_a_line_of_its_own(self, info, name, other):
        """Fifteen features on one line is the state this rendering replaces, so
        the pin is not "the name appears" — it is that its line is its own."""
        lines = [line for line in str(info).splitlines() if name in line]
        assert len(lines) == 1, str(info)
        assert other not in lines[0], str(info)

    @pytest.mark.parametrize(("name", "count", "other"), [("train", 3, "val"), ("val", 2, "train")])
    def test_printing_it_gives_every_split_a_line_with_its_count(self, info, name, count, other):
        """Name and count on one line, and only one split's: two lines that each
        carry half of it can be read in the wrong pairing."""
        lines = [line for line in str(info).splitlines() if name in line]
        assert len(lines) == 1, str(info)
        assert str(count) in lines[0], str(info)
        assert other not in lines[0], str(info)

    def test_printing_it_humanizes_the_download_size(self, info):
        """``download_size=11101`` is a number to count digits on; this is the
        same fact in the form a reader can weigh."""
        assert DOWNLOAD_SIZE_HUMANIZED in str(info)

    def test_the_humanized_size_is_the_one_type_that_renders_bytes(self, info):
        """One rendering, not two that agree today: the CLI prints the same type."""
        assert DOWNLOAD_SIZE_HUMANIZED == str(info_type("ByteSize")(DOWNLOAD_SIZE))

    def test_printing_it_names_no_shard_role(self, info):
        """ac-002 holds for the human view too, not only for ``repr``."""
        assert "shard-" not in str(info)

    def test_the_dataclass_repr_is_left_alone(self, info):
        """``repr`` is the exhaustive one — it is what a debugger and a failing
        assertion print, and losing a field there costs more than it buys."""
        assert repr(info).startswith("DatasetInfo(")

    def test_the_two_renderings_are_not_the_same_string(self, info):
        """A ``__str__`` that fell back to ``__repr__`` would pass every content
        assertion above and answer neither question."""
        assert str(info) != repr(info)


class TestByteSize:
    """One byte count, in the form a reader can weigh — and one place it is done.

    Binary units (a 40 GB budget is a 2^30 GB budget everywhere else in this
    repo), one decimal, and a bare ``B`` below 1 KiB. Every literal in
    :data:`HUMANIZED` is written out rather than computed here: a golden that
    called the implementation would agree with whatever the implementation were
    edited to say, and the whole value of a rendering pin is that it does not.
    """

    @pytest.mark.parametrize(("size", "text"), HUMANIZED, ids=lambda value: str(value))
    def test_it_renders_the_declared_text(self, size, text):
        assert str(info_type("ByteSize")(size)) == text

    def test_a_kibibyte_is_1024_bytes_not_1000(self):
        """The one decision the whole table turns on, stated on its own."""
        byte_size = info_type("ByteSize")
        assert str(byte_size(1024)) == "1.0 KiB"
        assert str(byte_size(1000)) == "1000 B"

    def test_it_stops_at_the_largest_unit_below_the_value(self):
        """0.95 TiB is still reported in GiB: a leading ``0.`` is a unit too far."""
        assert str(info_type("ByteSize")(1048543472353)) == "976.5 GiB"

    def test_it_carries_the_exact_count_it_was_given(self):
        """The rendering is lossy on purpose; the value must not be."""
        assert info_type("ByteSize")(31041658614).value == 31041658614

    def test_it_is_frozen(self):
        size = info_type("ByteSize")(1024)
        with pytest.raises(dataclasses.FrozenInstanceError):
            size.value = 2048
