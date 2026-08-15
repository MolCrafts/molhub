"""What a dataset *contains*, described before a single byte is fetched.

Three frozen records answer the question 「用户怎么知道 shard-000 是什么东西」 by
never asking it: a :class:`DatasetInfo` carries the resolved coordinate, the
prose, the :class:`Feature` list, the :class:`SplitInfo` counts, what one record
is and what a full download costs. No field of any of them names a shard role —
roles are transport, and transport is not content.

**Where a feature's level and units come from.** Neither is on
:class:`~molhub.dataset.protocol.TargetSchema`, which has two layout sets and no
unit anywhere. So :meth:`Feature.declared` reads the level off *which declaration
set a name sits in* — ``blocks`` → ``block``, ``atom_level`` → ``atom``,
``graph_level`` → ``meta`` — and the units off the optional ``units`` mapping of
the dataset's :class:`~molhub.dataset.definition.DatasetManifest`.

**``blocks`` outranks ``graph_level``.** ``THEMolHessian`` declares ``hessian``
in ``TARGET_SCHEMA.graph_level`` because the schema has nowhere else to put it,
while ``hf-facade-02`` made the Hessian a COO block on the frame. When both name
a target, the block declaration wins: it describes the record as it now is, and
resolving the other way would tell a reader to look in ``frame.meta`` for
something that is not there.

Reference:
    ``.claude/specs/hf-facade-03-builder-info.md`` § Design (``info.py``) and
    ac-002, under the 2026-08-15 operator override recorded in
    ``.claude/notes/notes.md`` (``mol:note:topic:hf-style-api``).
"""

from __future__ import annotations

from dataclasses import dataclass

from molhub.coordinate import Coordinate
from molhub.dataset.definition import DatasetManifest
from molhub.dataset.protocol import TargetSchema

__all__ = ["Feature", "SplitInfo", "DatasetInfo"]

#: Where a declared target sits on a record, and therefore where a reader looks
#: for it: an ``atoms`` column, a ``frame.meta`` entry, or a named COO block.
ATOM_LEVEL = "atom"
META_LEVEL = "meta"
BLOCK_LEVEL = "block"


@dataclass(frozen=True)
class Feature:
    """One thing a record carries: its name, where it sits, and its unit.

    Attributes:
        name: The column, ``meta`` key or block name a reader finds on the
            record, carried verbatim from the declaration.
        level: One of ``"atom"``, ``"meta"``, ``"block"``.
        units: The unit the dataset declares for *name*, or ``""`` when it
            declares none — an absent unit is said with an empty string, not
            with ``None``, so every rendered feature reads the same way.
    """

    name: str
    level: str
    units: str = ""

    @classmethod
    def declared(
        cls,
        name: str,
        *,
        schema: TargetSchema,
        manifest: DatasetManifest,
    ) -> "Feature":
        """Derive the feature *name* from the declarations that mention it.

        Args:
            name: A declared target name.
            schema: The dataset class's layout declaration.
            manifest: The dataset class's bibliographic declaration, whose
                optional ``units`` and ``blocks`` fields carry the two facts
                *schema* cannot.

        Returns:
            The feature, with its level resolved (``blocks`` first, then
            ``atom_level``, then ``graph_level``) and its unit read from
            *manifest*.

        Raises:
            ValueError: If no declaration mentions *name*. A feature nobody
                declared has no level to report, and inventing one would put a
                name in front of a user that no record carries.
        """
        return cls(
            name=name,
            level=cls._level(name, schema=schema, manifest=manifest),
            units=manifest.units.get(name, ""),
        )

    @staticmethod
    def _level(name: str, *, schema: TargetSchema, manifest: DatasetManifest) -> str:
        """Which declaration set *name* sits in, blocks first."""
        if name in manifest.blocks:
            return BLOCK_LEVEL
        if name in schema.atom_level:
            return ATOM_LEVEL
        if name in schema.graph_level:
            return META_LEVEL
        raise ValueError(
            f"{manifest.canonical} declares no target {name!r}: it is in none of "
            f"blocks={sorted(manifest.blocks)}, atom_level={sorted(schema.atom_level)}, "
            f"graph_level={sorted(schema.graph_level)}."
        )


@dataclass(frozen=True)
class SplitInfo:
    """One split: its name, how many records it holds, and where that came from.

    Attributes:
        name: The split label, as the dataset or its split derivation spells it.
        num_examples: How many records the split holds.
        provenance: The sentence that says who decided this split and how — the
            split derivation's own record for a table-backed dataset, the
            declaring class for a dataset that owns its splits. A count nobody
            can re-derive is a number, not evidence.
    """

    name: str
    num_examples: int
    provenance: str


@dataclass(frozen=True)
class DatasetInfo:
    """Everything a user is told before any bytes move.

    Attributes:
        coordinate: The **resolved** coordinate, so a run can record what it
            actually read rather than what it asked for.
        description: Prose, from the registry manifest.
        citation: The DOI or citation text the manifest records, or ``""``.
        license: The license label the manifest records, or ``""``.
        features: What one record carries, in name order.
        splits: The declared splits with their counts and provenance.
        record_type: What one record *is* — ``"Frame"``, ``"Trajectory"``, or
            the union when the dataset yields either.
        download_size: Every declared byte of the artifact: what a full
            download costs, in bytes.
    """

    coordinate: Coordinate
    description: str
    citation: str
    license: str
    features: tuple[Feature, ...]
    splits: tuple[SplitInfo, ...]
    record_type: str
    download_size: int
