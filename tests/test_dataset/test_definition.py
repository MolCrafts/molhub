"""Unit tests for dataset declaration types."""

from __future__ import annotations

import ast
import inspect
import json
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from molhub.coordinate import Coordinate, InvalidCoordinate
from molhub.dataset.definition import (
    DatasetManifest,
    Datasets,
    UnknownDataset,
    dataset,
)


class TestDatasetManifest:
    def test_asdict_nests_coordinate_strings(self) -> None:
        manifest = DatasetManifest(
            coordinate=Coordinate(
                kind="dataset", namespace="molcrafts", name="dummy", version="1.0"
            ),
            description="d",
            license="CC0-1.0",
            homepage="https://example.invalid",
            citation="cite",
            tags=("a",),
        )
        payload = asdict(manifest)
        assert payload["coordinate"] == {
            "kind": "dataset",
            "namespace": "molcrafts",
            "name": "dummy",
            "version": "1.0",
        }
        assert "canonical" not in payload
        json.dumps(payload)

    def test_frozen(self) -> None:
        manifest = DatasetManifest(
            coordinate=Coordinate(
                kind="dataset", namespace="molcrafts", name="dummy", version="1.0"
            )
        )
        with pytest.raises(FrozenInstanceError):
            manifest.description = "no"  # type: ignore[misc]

    def test_rejects_non_dataset_kind(self) -> None:
        with pytest.raises(InvalidCoordinate):
            DatasetManifest(
                coordinate=Coordinate(
                    kind="model", namespace="molcrafts", name="mace", version="1.0"
                )
            )

    def test_canonical_forwards_coordinate(self) -> None:
        coord = Coordinate(kind="dataset", namespace="molcrafts", name="dummy", version="1.0")
        assert DatasetManifest(coordinate=coord).canonical == coord.canonical

    def test_tags_tuple(self) -> None:
        manifest = DatasetManifest(
            coordinate=Coordinate(
                kind="dataset", namespace="molcrafts", name="dummy", version="1.0"
            ),
            tags=["a", "b"],
        )
        assert manifest.tags == ("a", "b")


class TestDataset:
    def test_attaches_manifest_with_coordinate_identity(self) -> None:
        @dataset(name="dummy", namespace="molcrafts", version="1.0")
        class Dummy:
            pass

        assert isinstance(Dummy.manifest, DatasetManifest)
        assert Dummy.manifest.canonical == "dataset:molcrafts/dummy@1.0"
        assert Dummy.manifest.coordinate == Coordinate(
            kind="dataset", namespace="molcrafts", name="dummy", version="1.0"
        )

    def test_returns_same_class(self) -> None:
        class Dummy:
            pass

        decorated = dataset(name="dummy", namespace="molcrafts", version="1.0")(Dummy)
        assert decorated is Dummy

    def test_does_not_wrap_init(self) -> None:
        @dataset(name="dummy", namespace="molcrafts", version="1.0")
        class Dummy:
            pass

        Dummy()
        assert Dummy.__init__ is object.__init__

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"name": "QM9", "namespace": "molcrafts", "version": "1.0"},
            {"name": "qm 9", "namespace": "molcrafts", "version": "1.0"},
            {"name": "-qm9", "namespace": "molcrafts", "version": "1.0"},
            {"name": "qm.9", "namespace": "molcrafts", "version": "1.0"},
            {"name": "qm_9", "namespace": "molcrafts", "version": "1.0"},
            {"name": "qm9", "namespace": "MolCrafts", "version": "1.0"},
            {"name": "qm9", "namespace": "molcrafts", "version": "!bad"},
        ],
    )
    def test_invalid_identity_raises(self, kwargs: dict[str, str]) -> None:
        with pytest.raises(InvalidCoordinate):

            @dataset(**kwargs)
            class Dummy:
                pass

    def test_kind_is_not_an_argument(self) -> None:
        with pytest.raises(TypeError):
            dataset(  # type: ignore[call-arg]
                name="dummy",
                namespace="molcrafts",
                version="1.0",
                kind="dataset",
            )


class TestDatasets:
    def test_resolve_full_form(self) -> None:
        @dataset(name="dummy", namespace="molcrafts", version="1.0")
        class Dummy:
            pass

        assert Datasets.of(Dummy).resolve("dataset:molcrafts/dummy@1.0") is Dummy

    def test_resolve_coordinate_and_shorthand(self) -> None:
        @dataset(name="dummy", namespace="molcrafts", version="1.0")
        class Dummy:
            pass

        catalog = Datasets.of(Dummy)
        coord = Coordinate(kind="dataset", namespace="molcrafts", name="dummy", version="1.0")
        assert catalog.resolve(coord) is Dummy
        assert catalog.resolve("dummy@1.0") is Dummy

    def test_with_dataset_is_immutable_and_later_write_wins(self) -> None:
        @dataset(name="dummy", namespace="molcrafts", version="1.0")
        class First:
            pass

        @dataset(name="dummy", namespace="molcrafts", version="1.0")
        class Second:
            pass

        original = Datasets.of(First)
        updated = original.with_dataset(Second)
        assert original.resolve("dataset:molcrafts/dummy@1.0") is First
        assert updated.resolve("dataset:molcrafts/dummy@1.0") is Second

    def test_unknown_raises_unknown_dataset(self) -> None:
        catalog = Datasets()
        with pytest.raises(UnknownDataset, match="dataset:molcrafts/missing@1"):
            catalog.resolve("dataset:molcrafts/missing@1")

    def test_non_dataset_kind_rejected(self) -> None:
        @dataset(name="dummy", namespace="molcrafts", version="1.0")
        class Dummy:
            pass

        with pytest.raises(InvalidCoordinate):
            Datasets.of(Dummy).resolve("model:molcrafts/mace-mp-0@1.0")

    def test_missing_manifest_is_type_error(self) -> None:
        class Bare:
            pass

        with pytest.raises(TypeError, match="DatasetManifest"):
            Datasets.of(Bare)

    def test_coordinates_insertion_order(self) -> None:
        @dataset(name="a", namespace="molcrafts", version="1")
        class A:
            pass

        @dataset(name="b", namespace="molcrafts", version="1")
        class B:
            pass

        coords = Datasets.of(A, B).coordinates()
        assert [c.name for c in coords] == ["a", "b"]


def test_definition_module_has_no_io_imports() -> None:
    source = Path(__file__).resolve().parents[2] / "src" / "molhub" / "dataset" / "definition.py"
    tree = ast.parse(source.read_text())
    forbidden = {"pydantic", "ArtifactHub", "Molhub"}
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            names.update(alias.name for alias in node.names)
    assert not (forbidden & names)
    text = source.read_text()
    assert "molhub.sources" not in text
    assert "molhub.registry" not in text
    assert inspect.getsource(dataset)


# ---------------------------------------------------------------------------
# Uniform dataset shape — the 2026-08-20 operator rule, made executable
# ---------------------------------------------------------------------------


#: Every @dataset-decorated class must present one shape, so the author of the
#: next dataset has exactly one template to copy: the manifest with declared
#: native units, a COORDINATE class attribute, a TARGET_SCHEMA, a no-IO
#: constructor with load() as the IO boundary, map-style access, and a
#: source_id. Datasets not yet migrated join this list as they land.
def _uniform_shape_classes() -> list[type]:
    from molhub.dataset.omol25 import OMol25, OMol25Small
    from molhub.dataset.qm9 import QM9
    from molhub.dataset.revmd17 import RevMD17Dataset
    from molhub.dataset.water_les import WaterLESDataset

    return [QM9, RevMD17Dataset, WaterLESDataset, OMol25, OMol25Small]


@pytest.mark.parametrize("cls", _uniform_shape_classes(), ids=lambda cls: cls.__name__)
class TestUniformDatasetShape:
    def test_carries_a_dataset_manifest(self, cls):
        assert isinstance(cls.manifest, DatasetManifest)

    def test_declares_units_for_every_target(self, cls):
        schema = cls.TARGET_SCHEMA
        targets = set(schema.graph_level) | set(schema.atom_level)
        missing = targets - set(cls.manifest.units)
        assert not missing, f"{cls.__name__} declares no unit for {sorted(missing)}"

    def test_declared_units_parse_through_the_molpy_registry(self, cls):
        from molpy import UnitSystem

        registry = UnitSystem()
        for unit in cls.manifest.units.values():
            registry.Unit(unit)

    def test_coordinate_class_attribute_matches_the_manifest(self, cls):
        assert cls.COORDINATE == cls.manifest.coordinate.canonical

    def test_load_is_the_io_boundary(self, cls):
        assert callable(getattr(cls, "load", None))

    def test_is_map_style(self, cls):
        assert callable(getattr(cls, "__len__", None))
        assert callable(getattr(cls, "__getitem__", None))

    def test_exposes_a_source_id(self, cls):
        assert isinstance(getattr(cls, "source_id", None), property)
