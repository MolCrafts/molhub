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
        units: Target/unit pairs stored as an immutable tuple. A name of the
            form ``<block>.<column>`` addresses one column of a source block
            whose columns do not share a unit, which is the only honest
            spelling when a single string would be wrong for one of them.
        reference_method: Electronic-structure or classical-MM provenance
            for the targets.
        derived: Whether the source must be materialized by a versioned,
            reproducible derivation before production use.
        active: Whether this role belongs to the v0 resolve/materialize
            set. Inactive roles stay addressable by :meth:`MultiSourceDatasetCollection.role`
            but are omitted from :attr:`MultiSourceDatasetCollection.source_coordinates`.
    """

    name: str
    source_coordinates: tuple[str, ...]
    target_schema: TargetSchema
    sampling_unit: str
    units: tuple[tuple[str, str], ...]
    reference_method: str
    derived: bool = False
    active: bool = True


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
    def active_roles(self) -> tuple[CollectionRole, ...]:
        """Roles that belong to the v0 resolve set, in declaration order."""
        return tuple(role for role in self.roles if role.active)

    @property
    def source_coordinates(self) -> tuple[str, ...]:
        """Active-role source coordinates in role order, without duplicates."""
        return tuple(
            dict.fromkeys(
                coordinate for role in self.active_roles for coordinate in role.source_coordinates
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
    """MolHub definition for Universal Class-I v0.

    v0 active roles are OMol25-small train (DFT energy / forces, native eV /
    eV·Å⁻¹ as published) and PhAlkEthOH-MM validation (classical ``mm_energy``,
    native kcal/mol). Every role records its source's native units verbatim —
    molhub never converts; consumers convert (e.g.
    :class:`~molhub.dataset.transforms.UnitConvert`). Construction and
    :meth:`load` perform no network or filesystem IO. THEMol Hessian /
    torsion-scan / relax / MBIS roles stay declared with ``active=False`` so
    they are not a resolve gate. Training mixtures belong to the Molexp
    experiment.

    **The electrostatic role's MBIS Slater shells are not atom-level.** The
    source ``parameters`` array is one row per Slater *shell*, not per atom —
    the shells per atom vary (H 1, most heavy atoms 2, a third-period atom up to
    3), so ``S > N`` — as the 2026-08-15 probe of the real published THEMol mbis
    ``shard-000`` established; :class:`~molhub.dataset.themol.THEMolMBIS` reads
    them into the ``mbis_shells`` block of ``atom`` / ``population`` /
    ``inverse_width``. This role declared them as ``mbis_parameters`` under
    ``atom_level`` with the unit "mixed; see source schema", which claimed a
    per-atom row the source never had.

    :class:`~molhub.dataset.protocol.TargetSchema` has only the ``graph_level``
    and ``atom_level`` *layout* sets and shell-major rows are neither, so the
    entry is dropped from ``atom_level`` and kept on the *meaning* axis as
    ``qm={"mbis_shells"}``: that says what the shells are (QM labels of this
    role) without claiming a layout the structure cannot express. Where the
    shells live is declared once, by the source dataset itself
    (``THEMolMBIS.manifest.blocks == ("mbis_shells",)``). Their two units are
    per column — ``mbis_shells.population`` in ``e``,
    ``mbis_shells.inverse_width`` in ``angstrom^-1`` — because one string for
    the whole block would be wrong for one of the two.
    """

    COORDINATE = "dataset:molcrafts/class1-universal-2026@1"

    def load(self) -> MultiSourceDatasetCollection:
        """Return the immutable v0 role composition.

        Active roles are OMol25-small train and PhAlkEthOH-MM validation.
        THEMol roles are declared with ``active=False`` and are not a
        resolve gate.
        """
        return MultiSourceDatasetCollection(
            coordinate=self.COORDINATE,
            roles=(
                CollectionRole(
                    name="train",
                    source_coordinates=("dataset:molcrafts/omol25-small@1",),
                    target_schema=TargetSchema(
                        graph_level=frozenset({"energy"}),
                        atom_level=frozenset({"forces"}),
                        qm=frozenset({"energy", "forces"}),
                    ),
                    sampling_unit="molecule",
                    units=(
                        ("coordinates", "angstrom"),
                        ("energy", "eV"),
                        ("forces", "eV/angstrom"),
                    ),
                    reference_method="ωB97M-V/def2-TZVPD",
                    derived=True,
                ),
                CollectionRole(
                    name="validation",
                    source_coordinates=("dataset:espaloma/phalkethoh-mm-small@1",),
                    target_schema=TargetSchema(
                        graph_level=frozenset({"mm_energy"}),
                        atom_level=frozenset({"forces"}),
                        mm=frozenset({"mm_energy", "forces"}),
                    ),
                    sampling_unit="molecule",
                    units=(
                        ("coordinates", "angstrom"),
                        ("mm_energy", "kcal/mol"),
                        ("forces", "kcal/mol/angstrom"),
                    ),
                    reference_method="classical MM (Espaloma PhAlkEthOH-MM-small)",
                ),
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
                    active=False,
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
                    active=False,
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
                    active=False,
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
                            }
                        ),
                        qm=frozenset(
                            {
                                "atomic_charge",
                                "atomic_dipole",
                                "atomic_quadrupole",
                                "atomic_volume",
                                "mbis_shells",
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
                        ("mbis_shells.population", "e"),
                        ("mbis_shells.inverse_width", "angstrom^-1"),
                    ),
                    reference_method="PBE0/def2-TZVPD (DZVP for iodine)",
                    active=False,
                ),
            ),
        )
