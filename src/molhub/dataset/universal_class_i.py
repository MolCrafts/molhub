"""Versioned, task-structured Universal Class-I dataset collection.

This module describes dataset composition only. It does not flatten sources,
choose training batches, or import a model/training framework. Consumers keep
the physical roles separate and resolve each pinned source through MolHub.
"""

from __future__ import annotations

from dataclasses import dataclass

from molhub.dataset.definition import dataset
from molhub.dataset.protocol import TargetSchema

__all__ = [
    "CollectionRole",
    "MultiSourceDatasetCollection",
    "Class1Universal2026",
]


@dataclass(frozen=True)
class CollectionRole:
    """One physically meaningful role in a multi-source collection.

    Args:
        name: Stable role name used by consumers.
        source_coordinates: Immutable MolHub source coordinates. Multiple
            coordinates mean one derived role has declared inputs, not that
            their frames may be concatenated indiscriminately.
        target_schema: Target schemas available from the role.
        sampling_unit: Hierarchical object that must remain intact.
        units: Target/unit pairs stored as an immutable tuple.
        reference_method: Electronic-structure provenance for the targets.
        derived: Whether the source must be materialized by a versioned,
            reproducible derivation before production use.
    """

    name: str
    source_coordinates: tuple[str, ...]
    target_schema: TargetSchema
    sampling_unit: str
    units: tuple[tuple[str, str], ...]
    reference_method: str
    derived: bool = False


@dataclass(frozen=True)
class MultiSourceDatasetCollection:
    """Immutable dataset collection whose physical roles remain separate."""

    coordinate: str
    roles: tuple[CollectionRole, ...]

    def role(self, name: str) -> CollectionRole:
        """Return a named role or raise with the available role names."""
        for role in self.roles:
            if role.name == name:
                return role
        available = ", ".join(role.name for role in self.roles)
        raise KeyError(f"Unknown collection role {name!r}. Available: {available}")

    @property
    def source_coordinates(self) -> tuple[str, ...]:
        """All pinned source coordinates in role order, without duplicates."""
        return tuple(
            dict.fromkeys(
                coordinate for role in self.roles for coordinate in role.source_coordinates
            )
        )


@dataset(
    name="class1-universal-2026",
    namespace="molcrafts",
    version="1",
    description="Task-structured Universal Class-I training collection.",
    license="CC-BY-NC-4.0",
    tags=("class-i", "multi-source", "task-balanced"),
)
class Class1Universal2026:
    """MolHub definition for the first THEMol-only Class-I collection.

    Construction and :meth:`load` perform no network or filesystem IO. The
    return value is a composition manifest; consumers resolve and load each
    role source explicitly. Training mixtures belong to the Molexp experiment.
    """

    COORDINATE = "dataset:molcrafts/class1-universal-2026@1"

    def load(self) -> MultiSourceDatasetCollection:
        """Return the immutable v0 physical-role composition."""
        return MultiSourceDatasetCollection(
            coordinate=self.COORDINATE,
            roles=(
                CollectionRole(
                    name="equilibrium",
                    source_coordinates=("dataset:themol/hessian@1",),
                    target_schema=TargetSchema(
                        graph_level=frozenset({"hessian"}),
                        atom_level=frozenset(),
                        qm=frozenset({"hessian"}),
                    ),
                    sampling_unit="molecule",
                    units=(
                        ("coordinates", "angstrom"),
                        ("hessian", "kcal/mol/angstrom^2"),
                    ),
                    reference_method="B3LYP-D3(BJ)/DZVP",
                ),
                CollectionRole(
                    name="torsion",
                    source_coordinates=("dataset:themol/torsion-scan@1",),
                    target_schema=TargetSchema(
                        graph_level=frozenset({"energy", "torsion_angle"}),
                        atom_level=frozenset({"forces"}),
                        qm=frozenset({"energy", "forces"}),
                    ),
                    sampling_unit="complete-torsion-profile",
                    units=(
                        ("coordinates", "angstrom"),
                        ("torsion_angle", "degree"),
                        ("energy", "kcal/mol"),
                        ("forces", "kcal/mol/angstrom"),
                    ),
                    reference_method="B3LYP-D3(BJ)/DZVP",
                ),
                CollectionRole(
                    name="off-equilibrium",
                    source_coordinates=("dataset:molcrafts/themol-relax-diverse@1",),
                    target_schema=TargetSchema(
                        graph_level=frozenset({"energy"}),
                        atom_level=frozenset({"forces"}),
                        qm=frozenset({"energy", "forces"}),
                    ),
                    sampling_unit="molecule-then-selected-configuration",
                    units=(
                        ("coordinates", "angstrom"),
                        ("energy", "kcal/mol"),
                        ("forces", "kcal/mol/angstrom"),
                    ),
                    reference_method="B3LYP-D3(BJ)/DZVP",
                    derived=True,
                ),
                CollectionRole(
                    name="electrostatic",
                    source_coordinates=("dataset:themol/mbis@1",),
                    target_schema=TargetSchema(
                        graph_level=frozenset(),
                        atom_level=frozenset(
                            {
                                "atomic_charge",
                                "atomic_dipole",
                                "atomic_quadrupole",
                                "atomic_volume",
                                "mbis_parameters",
                            }
                        ),
                        qm=frozenset(
                            {
                                "atomic_charge",
                                "atomic_dipole",
                                "atomic_quadrupole",
                                "atomic_volume",
                                "mbis_parameters",
                            }
                        ),
                    ),
                    sampling_unit="molecule",
                    units=(
                        ("coordinates", "angstrom"),
                        ("atomic_charge", "e"),
                        ("atomic_dipole", "e*angstrom"),
                        ("atomic_quadrupole", "e*angstrom^2"),
                        ("atomic_volume", "angstrom^3"),
                        ("mbis_parameters", "mixed; see source schema"),
                    ),
                    reference_method="PBE0/def2-TZVPD (DZVP for iodine)",
                ),
            ),
        )
