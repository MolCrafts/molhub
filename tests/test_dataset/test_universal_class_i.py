"""Composition tests for the Universal Class-I MolHub collection."""

from __future__ import annotations

import pytest

from molhub.dataset import Class1Universal2026


def test_collection_is_task_structured_and_pinned() -> None:
    collection = Class1Universal2026().load()
    assert collection.coordinate == "dataset:molcrafts/class1-universal-2026@1"
    assert [role.name for role in collection.roles] == [
        "equilibrium",
        "torsion",
        "off-equilibrium",
        "electrostatic",
    ]
    assert collection.source_coordinates == (
        "dataset:themol/hessian@1",
        "dataset:themol/torsion-scan@1",
        "dataset:molcrafts/themol-relax-diverse@1",
        "dataset:themol/mbis@1",
    )


def test_collection_preserves_physical_sampling_units() -> None:
    collection = Class1Universal2026().load()
    assert collection.role("equilibrium").sampling_unit == "molecule"
    assert collection.role("torsion").sampling_unit == "complete-torsion-profile"
    assert collection.role("off-equilibrium").derived is True
    assert collection.role("electrostatic").reference_method.startswith("PBE0/")


def test_unknown_role_fails_with_available_roles() -> None:
    with pytest.raises(KeyError, match="equilibrium, torsion"):
        Class1Universal2026().load().role("flat-pool")


def test_definition_and_load_do_not_resolve_or_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("collection composition must not fetch data")

    monkeypatch.setattr("molhub.molhub.Molhub.fetch", forbidden)
    collection = Class1Universal2026().load()
    assert len(collection.roles) == 4
