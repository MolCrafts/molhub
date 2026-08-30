"""What the REMOTE tier holds for one collection role — projected, never indexed.

molhub already ships an index of every remote block: the registry manifests
(``src/molhub/dataset/themol_files.py``), where each shard is one
artifact role with its filename, size, digest and locators. A roster that kept
its own copy of any of that would be a second index, and a second index is a
thing that drifts — quietly, in the direction of whichever copy is not the one
being updated. So :class:`BlockRoster` **projects**: it selects which artifacts
are blocks, wraps each in the addressing the ledger uses, and carries the
manifest's own values through by identity. Nothing is re-derived, so a
re-derivation would be visible as a new object.

**What is refused, and why at construction.** ``Artifact.size`` and
``Artifact.digest`` are each individually optional in the manifest schema, and
either absence breaks an invariant this chain cannot recover later: a block with
no declared size cannot be admitted to a byte-bounded queue, and a block with no
digest cannot satisfy *a mismatching block never reaches READY*. Both are
refused where the projection is built rather than where a queue eventually
trips over them, so the manifest that is wrong is named while the caller is
still holding it.

**What the roster is not allowed to invent.** :class:`~molhub.conveyor.block.BlockId`
carries a ``split``, and for a published shard the roster cannot fill it: the
split tables key molecular identity and scan uuid, not shard role, and resolving
uuid to shard means opening the HDF5 bytes this layer deliberately never opens.
Every projected block therefore has ``id.split is None`` — the honest signal
that the block is not split-pure. Split-purity is a property of *derived* blocks,
filled by the stage that cuts and publishes them, on manifests it writes itself.
An injected :class:`~molhub.conveyor.splits._SplitTable` is here for the one job
it can do without bytes: binding the projection to a provenance-verified split
version, readable as :attr:`BlockRoster.split_provenance`.

**Unit facts stay on the role.** ``units``, ``sampling_unit``,
``reference_method`` and the target schema live on the injected
:class:`~molhub.dataset.universal_class_i.CollectionRole` and are read from it
(``roster.role.units``). Copying them onto every block would be the god-struct
the house rules forbid, and a second place for them to be wrong.

Reference:
    ``.claude/specs/streaming-data-tiers-03-conveyor-02-roster.md``
    § *``RemoteBlock`` and ``BlockRoster`` — projection, not a parallel index*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from molhub.conveyor.block import BlockId, ConveyorError
from molhub.conveyor.splits import SplitProvenance, _SplitTable
from molhub.manifest import Manifest
from molhub.sources.digest import Digest
from molhub.sources.locator import Locator

if TYPE_CHECKING:  # pragma: no cover - typing only; see the note below.
    # Imported for the annotation alone. `molhub.dataset`'s package __init__
    # pulls in molpy and numpy, and the conveyor is bookkeeping that must stay
    # importable without them; the roster needs the role's *shape* (`name`,
    # `source_coordinates`, and whatever a caller reads off `roster.role`), not
    # its module.
    from molhub.dataset.universal_class_i import CollectionRole

__all__ = [
    "RemoteBlock",
    "BlockRoster",
    "RosterError",
    "NoShardArtifacts",
    "UnsizedBlock",
    "UnverifiableBlock",
    "RoleSourceMismatch",
]

# The registry's shard convention, established by
# `scripts/generate_themol_manifests.py`. Every other role is hot-tier.
_SHARD_ROLE = re.compile(r"shard-\d+")


class RosterError(ConveyorError):
    """A manifest and a role cannot honestly produce a block roster."""


class NoShardArtifacts(RosterError):
    """A manifest yields no ``shard-<digits>`` role.

    Refused rather than returned as an empty roster: empty reads as "nothing to
    fetch", which for a 239 GB collection is the most expensive kind of lie. A
    manifest naming its shards differently should fail where it is projected.
    """


class UnsizedBlock(RosterError):
    """A shard artifact declares no size, so no byte budget can admit it."""


class UnverifiableBlock(RosterError):
    """A shard artifact declares no digest, so arrival cannot be verified."""


class RoleSourceMismatch(RosterError):
    """The manifest's coordinate is not one the collection role declares.

    Catches the pairing that is individually well-formed and wholly wrong —
    ``dataset:themol/mbis@1`` projected under the ``torsion`` role — which would
    otherwise produce a roster nothing downstream could tell was mis-tasked.
    """


@dataclass(frozen=True)
class RemoteBlock:
    """One remote block: the manifest's artifact, addressed the way the ledger is.

    Five fields, all carried from the manifest verbatim. There is deliberately
    no unit, target, sampling-unit or reference-method field: those belong to the
    collection role and are read from :attr:`BlockRoster.role`.

    Attributes:
        id: Ledger addressing — ``source`` is the manifest coordinate, ``task``
            the role name, ``block_id`` the artifact role, ``split`` ``None``
            for a published shard.
        filename: ``Artifact.filename``, verbatim.
        size: ``Artifact.size``, verbatim. Non-optional: a block whose size is
            unknown never becomes a :class:`RemoteBlock` at all.
        digest: ``Artifact.digest`` — the same object, so a re-computation would
            be visible as a new one. Non-optional, for the same reason.
        locators: ``Artifact.locators`` — likewise the same object.
    """

    id: BlockId
    filename: str
    size: int
    digest: Digest
    locators: tuple[Locator, ...]


class BlockRoster:
    """The REMOTE tier of one collection role, projected out of one manifest.

    Projects eagerly in ``__init__``, so a manifest that cannot honestly be
    projected is refused while the caller still has it in hand — the same
    loud-at-construction posture :meth:`molhub.manifest.Manifest.from_mapping`
    takes.

    Args:
        manifest: The manifest to project. A parsed manifest, not a coordinate
            and not a registry: resolution is the caller's job, which is what
            keeps a roster constructible from a YAML string with no
            ``$MOLHUB_REGISTRY``, no ``$MOLHUB_HOME`` and no network.
        role: The collection role these blocks serve. Read, never copied.
        splits: A provenance-verified split table to bind this projection to,
            when the caller has one. It fills no ``BlockId.split`` — see the
            module docstring — it only makes the split version traceable.

    Raises:
        RoleSourceMismatch: If ``role`` does not declare this manifest's
            coordinate.
        UnsizedBlock: If a shard artifact declares no size.
        UnverifiableBlock: If a shard artifact declares no digest.
        NoShardArtifacts: If the manifest yields no shard role at all.
    """

    def __init__(
        self,
        manifest: Manifest,
        role: CollectionRole,
        *,
        splits: _SplitTable | None = None,
    ) -> None:
        source = manifest.coordinate.canonical
        if source not in role.source_coordinates:
            raise RoleSourceMismatch(
                f"Collection role {role.name!r} declares {list(role.source_coordinates)}, "
                f"not {source}. A roster of one coordinate's shards under another role's "
                "name is well-formed and wholly wrong; pair the manifest with the role "
                "that names it."
            )

        blocks: dict[BlockId, RemoteBlock] = {}
        hot_roles: list[str] = []
        for artifact_role, artifact in manifest.artifacts.items():
            if not _SHARD_ROLE.fullmatch(artifact_role):
                hot_roles.append(artifact_role)
                continue
            if artifact.size is None:
                raise UnsizedBlock(
                    f"{source} artifact {artifact_role!r} declares no size, so no "
                    "byte-bounded queue can admit it. Record the size in the manifest — a "
                    "HEAD request's content-length gives one without hauling the file."
                )
            if artifact.digest is None:
                raise UnverifiableBlock(
                    f"{source} artifact {artifact_role!r} declares no digest, so a "
                    "delivered file has nothing to be verified against and could never "
                    "be certified. Copy whatever checksum the platform publishes."
                )
            block = RemoteBlock(
                id=BlockId(source, role.name, None, artifact_role),
                filename=artifact.filename,
                size=artifact.size,
                digest=artifact.digest,
                locators=artifact.locators,
            )
            blocks[block.id] = block

        if not blocks:
            raise NoShardArtifacts(
                f"{source} yields no {_SHARD_ROLE.pattern!r} artifact role; it declares "
                f"{sorted(manifest.artifacts)}. An empty roster would read as 'nothing to "
                "fetch', so a manifest naming its shards differently is refused here."
            )

        self._manifest = manifest
        self._role = role
        self._splits = splits
        self._blocks = blocks
        self._hot_roles = tuple(hot_roles)

    def blocks(self) -> tuple[RemoteBlock, ...]:
        """Every shard block, in manifest role order.

        Returns:
            The projected blocks. Manifest order, not sorted order: the manifest
            is the record, and re-ordering it here would be a second opinion
            about which block comes first.
        """
        return tuple(self._blocks.values())

    def block(self, id: BlockId) -> RemoteBlock:
        """Return the block addressed by *id*.

        Args:
            id: The block identity, as the ledger addresses it.

        Returns:
            The projected block — the same object :meth:`blocks` yields.

        Raises:
            KeyError: If this roster holds no such block; the message lists the
                keys it does hold, following
                :meth:`molhub.manifest.Manifest.artifact`.
        """
        try:
            return self._blocks[id]
        except KeyError:
            available = ", ".join(held.key() for held in self._blocks)
            raise KeyError(
                f"{self._manifest.coordinate.canonical} has no block {id.key()!r} under "
                f"role {self._role.name!r}. Available: {available}"
            ) from None

    def total_bytes(self) -> int:
        """How many bytes this role's REMOTE tier occupies.

        Returns:
            The sum of the shard sizes. Hot-tier artifacts are excluded — a
            1.45 GB index CSV silently admitted to a 40 GB rolling budget is a
            real accounting error, not a rounding one.
        """
        return sum(block.size for block in self._blocks.values())

    @property
    def hot_roles(self) -> tuple[str, ...]:
        """Manifest roles that are not shards, in manifest order.

        Reported rather than dropped: they still have to be fetched, they are
        just not part of the byte-bounded rolling queue.
        """
        return self._hot_roles

    @property
    def role(self) -> CollectionRole:
        """The injected collection role — the one home of unit and target facts."""
        return self._role

    @property
    def split_provenance(self) -> SplitProvenance | None:
        """The split derivation this projection is bound to, when one was given.

        Returns:
            The injected table's own provenance, or ``None`` when no table was
            injected. ``None`` here says "this projection names no split
            version", which is different from — and not a substitute for — the
            per-block ``id.split is None``.
        """
        return self._splits.provenance if self._splits is not None else None
