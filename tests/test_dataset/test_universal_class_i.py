"""Composition tests for the Universal Class-I MolHub collection."""

from __future__ import annotations

import pytest

from molhub.dataset import Class1Universal2026
from molhub.dataset.protocol import TargetSchema
from molhub.dataset.universal_class_i import CollectionRole, MultiSourceDatasetCollection

_SCHEMA = TargetSchema(
    graph_level=frozenset({"energy"}),
    atom_level=frozenset({"forces"}),
)


def _role(
    name: str,
    coordinate: str,
    *,
    derived: bool = False,
    active: bool | None = None,
) -> CollectionRole:
    kwargs: dict[str, object] = {}
    if active is not None:
        kwargs["active"] = active
    return CollectionRole(
        name=name,
        source_coordinates=(coordinate,),
        target_schema=_SCHEMA,
        sampling_unit="molecule",
        units=(("energy", "kcal/mol"),),
        reference_method="test",
        derived=derived,
        **kwargs,
    )


class TestCollectionRole:
    def test_active_defaults_true_when_omitted(self) -> None:
        role = _role("train", "dataset:example/a@1", derived=True)
        assert role.active is True
        assert role.derived is True


class TestMultiSourceDatasetCollection:
    def test_source_coordinates_lists_only_active_roles(self) -> None:
        collection = MultiSourceDatasetCollection(
            coordinate="dataset:example/collection@1",
            roles=(
                _role("train", "dataset:example/train@1"),
                _role("held", "dataset:example/held@1", active=False),
                _role("validation", "dataset:example/val@1"),
            ),
        )
        assert collection.source_coordinates == (
            "dataset:example/train@1",
            "dataset:example/val@1",
        )
        assert tuple(role.name for role in collection.active_roles) == (
            "train",
            "validation",
        )


class TestClass1Universal2026:
    def test_active_roles_are_train_then_validation(self) -> None:
        names = tuple(role.name for role in Class1Universal2026().load().active_roles)
        assert names == ("train", "validation")

    def test_train_pins_omol25_small_as_derived_qm(self) -> None:
        role = Class1Universal2026().load().role("train")
        assert role.source_coordinates == ("dataset:molcrafts/omol25-small@1",)
        assert role.derived is True
        assert role.active is True
        assert role.target_schema.qm == frozenset({"energy", "forces"})
        assert "mm_energy" not in role.target_schema.qm
        assert role.reference_method == "ωB97M-V/def2-TZVPD"

    def test_validation_pins_phalkethoh_as_classical_mm(self) -> None:
        role = Class1Universal2026().load().role("validation")
        assert role.source_coordinates == ("dataset:espaloma/phalkethoh-mm-small@1",)
        assert role.active is True
        assert "mm_energy" in role.target_schema.mm
        assert role.target_schema.qm == frozenset()
        assert "DFT" not in role.reference_method
        assert "MM" in role.reference_method

    def test_themol_roles_stay_declared_and_inactive(self) -> None:
        collection = Class1Universal2026().load()
        for name in ("equilibrium", "torsion", "off-equilibrium", "electrostatic"):
            assert collection.role(name).active is False
        with pytest.raises(KeyError, match="Available:"):
            collection.role("intermolecular")

    def test_source_coordinates_omit_themol(self) -> None:
        assert Class1Universal2026().load().source_coordinates == (
            "dataset:molcrafts/omol25-small@1",
            "dataset:espaloma/phalkethoh-mm-small@1",
        )

    def test_definition_and_load_do_not_resolve_or_fetch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("collection composition must not fetch data")

        monkeypatch.setattr("molhub.molhub.Molhub.fetch", forbidden)
        collection = Class1Universal2026().load()
        assert len(collection.active_roles) == 2

    def test_unknown_role_lists_available_names(self) -> None:
        with pytest.raises(KeyError, match="Available:.*train.*validation"):
            Class1Universal2026().load().role("flat-pool")

    def test_train_and_validation_schemas_stay_disjoint(self) -> None:
        collection = Class1Universal2026().load()
        train = collection.role("train")
        validation = collection.role("validation")
        assert train.target_schema.qm == frozenset({"energy", "forces"})
        assert "mm_energy" not in train.target_schema.graph_level
        assert "mm_energy" in validation.target_schema.mm
        assert validation.target_schema.qm == frozenset()
        assert dict(train.units)["coordinates"] == "angstrom"
        assert dict(validation.units)["coordinates"] == "angstrom"
        assert dict(train.units)["energy"] == "eV"
        assert dict(validation.units)["mm_energy"] == "kcal/mol"
