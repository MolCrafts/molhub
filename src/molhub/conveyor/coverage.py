"""What the run has seen, and what it can consume right now.

Two surfaces, one module, because they answer the same question at two scales:
:class:`CoverageReport` folds ``-01``'s record stream into what the run saw over
time, and :class:`ReadyBlocks` reads the sealed manifests of the blocks tier into
what a consumer may open this instant. Partial coverage is legitimate;
unreported coverage is not (I10), which is why the report is derived from the
ledger on disk rather than from counters in a process that may have died.

**Digests are copied, never computed.** Per ``.claude/notes/notes.md``
§ "版本标识靠 DOI 与钉版本的 locator，不靠 digest", molhub never computes a digest of
its own: identity comes from a pinned coordinate and a published checksum, not
from hashing bytes locally. :attr:`BlockMetadata.block_digest` and
:attr:`BlockMetadata.column_digests` are therefore carried verbatim out of the
producer's ``manifest.json``. Column verification is molnex's
``BlockReader.verify()``; transfer verification is ``-02``'s ``ShardTransfer``.
Re-deriving either here would need molnex's canonical-JSON rule, and a
cross-repo copy of a hashing rule is a drift hazard that would fail silently —
by agreeing, right up until the day it did not.

**``metadata.json`` versus ``manifest.json``.** ``metadata.json`` sits at the
*artifact* level and describes a derivation run (inputs, outputs, seed,
generator); it is :class:`~molhub.conveyor.tier.DerivedLayout`'s file.
``manifest.json`` sits *inside* one block directory and is molnex's
``molix.block/1`` contract — columns, split, task_names, units, rows, digests,
sealed. This module reads only the second. They never merge and never nest: a
block directory that grew a ``metadata.json`` would be a schema collision
waiting to be mis-parsed by one of the two repos.

The handoff is torch-free on purpose. Everything the molnex-side sampler needs
to plan a batch — split, units, frames, task names, provenance pin — is in that
JSON object, so molhub stays a data-plane repo and the block *reader* stays
molnex's single owner.

Reference:
    ``.claude/specs/streaming-data-tiers-03-conveyor-04-residency.md`` § 6.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from molhub.conveyor.block import BlockId, BlockState, ConveyorError
from molhub.conveyor.ledger import LedgerRecord
from molhub.conveyor.tier import TierStore

__all__ = [
    "CoveragePoint",
    "CoverageReport",
    "BlockMetadata",
    "ReadyBlocks",
    "BlockNotSealed",
    "UnsupportedBlockFormat",
]

# molnex's block contract, as `molnex:src/molix/store/block.py` writes it. Two
# fields are validated and eight are read; the rest ride along untouched.
_BLOCK_FORMAT = "molix.block/1"
_SCHEMA_VERSION = 1
_MANIFEST_NAME = "manifest.json"

# The row space the sampler plans in. A block counts units; a batch counts
# frames, and `rows` is where the producer writes both.
_FRAME_SPACE = "frame"


class BlockNotSealed(ConveyorError):
    """A block directory's manifest does not claim to be sealed.

    READY is conjunctive — written, verified and sealed — so there is no
    half-ready state a consumer may read. A block still being written is not a
    smaller block; it is one whose columns do not yet mean what its manifest
    says.
    """


class UnsupportedBlockFormat(ConveyorError):
    """A manifest declares a block format or schema version molhub cannot read.

    Refused rather than parsed hopefully: the fields this module reads are
    ``molix.block/1``'s, and reading a future layout through them would produce
    a coverage number and a sampler plan that are quietly wrong.
    """


@dataclass(frozen=True)
class CoveragePoint:
    """One instant on the coverage timeline.

    Attributes:
        at: When the consuming record was written.
        blocks: Distinct blocks consumed up to and including that instant.
        units: Sampling units those blocks carried, cumulative.
    """

    at: datetime
    blocks: int
    units: int


@dataclass(frozen=True)
class CoverageReport:
    """What a run saw, folded out of the ledger it wrote.

    Every number is derived from records on disk, so the answer survives the
    process that produced it — which is the whole point of reporting coverage
    rather than trusting it.

    Attributes:
        blocks_seen: Blocks that reached ``READY``, in first-occurrence order.
        blocks_consumed: Blocks that reached ``CONSUMED``, in the order they
            first did.
        units_seen: Sampling units carried by :attr:`blocks_seen`, summed from
            the caller's ``units_by_block``.
        bytes_downloaded: Bytes summed over ``DOWNLOADING`` records, so a
            retried fetch counts twice — it measures network traffic honestly,
            not the size of what finally arrived.
        bytes_prepared: Bytes summed over ``READY`` records.
        bytes_evicted: Bytes summed over ``REMOTE`` records that follow a
            ``READY`` for the same **derived** block (``split is not None``) —
            the I4 residency reclaim. A block's first ``REMOTE`` is where it
            starts, not where it went, so registration is not a deletion.
        bytes_raw_released: The same rule for **raw** published shards
            (``split is None``) — the I3 reclaim, a shard deleted once its
            prepare consumed it. Kept apart from :attr:`bytes_evicted` because
            the two answer different questions: one is pressure, the other is
            the pipeline working as designed.
        timeline: One :class:`CoveragePoint` per ``CONSUMED`` record,
            cumulative.
    """

    blocks_seen: tuple[BlockId, ...]
    blocks_consumed: tuple[BlockId, ...]
    units_seen: int
    bytes_downloaded: int
    bytes_prepared: int
    bytes_evicted: int
    bytes_raw_released: int
    timeline: tuple[CoveragePoint, ...]

    @classmethod
    def replay(
        cls,
        records: Iterable[LedgerRecord],
        *,
        units_by_block: Mapping[BlockId, int],
    ) -> CoverageReport:
        """Fold a record stream into one frozen report.

        Args:
            records: ``-01``'s transition records, in the order they were
                written.
            units_by_block: Sampling units per block, supplied by the caller
                from ``-02``'s roster and this tier's sealed manifests. A plain
                mapping — a protocol here would couple the report to whichever
                collaborator happened to know the counts.

        Returns:
            The report. An empty stream reports zeros rather than failing:
            "nothing yet" is a legitimate answer, and refusing it would push
            callers into treating absence as an error.
        """
        seen: dict[BlockId, None] = {}
        consumed: dict[BlockId, None] = {}
        ready_now: set[BlockId] = set()
        downloaded = prepared = evicted = raw_released = 0
        timeline: list[CoveragePoint] = []
        units_running = 0

        for record in records:
            size = record.size_bytes or 0
            block = record.block
            if record.state is BlockState.DOWNLOADING:
                downloaded += size
            elif record.state is BlockState.READY:
                prepared += size
                seen.setdefault(block, None)
                ready_now.add(block)
            elif record.state is BlockState.CONSUMED:
                if block not in consumed:
                    consumed[block] = None
                    units_running += units_by_block.get(block, 0)
                timeline.append(
                    CoveragePoint(at=record.at, blocks=len(consumed), units=units_running)
                )
            elif record.state is BlockState.REMOTE and block in ready_now:
                ready_now.discard(block)
                if block.split is None:
                    raw_released += size
                else:
                    evicted += size

        return cls(
            blocks_seen=tuple(seen),
            blocks_consumed=tuple(consumed),
            units_seen=sum(units_by_block.get(block, 0) for block in seen),
            bytes_downloaded=downloaded,
            bytes_prepared=prepared,
            bytes_evicted=evicted,
            bytes_raw_released=raw_released,
            timeline=tuple(timeline),
        )

    def fraction(self, total_blocks: int) -> float:
        """The share of the corpus this run consumed.

        Args:
            total_blocks: Blocks in the corpus, from ``-02``'s roster.

        Returns:
            Consumed blocks over *total_blocks*.

        Raises:
            ValueError: If *total_blocks* is not positive. A fraction over an
                empty corpus is not zero percent, it is undefined — and
                reporting it as a number is exactly the implicit coverage I10
                forbids.
        """
        if total_blocks <= 0:
            raise ValueError(
                f"total_blocks must be a positive block count; got {total_blocks}. Without a "
                "corpus denominator there is no coverage number to report."
            )
        return len(self.blocks_consumed) / total_blocks


@dataclass(frozen=True)
class BlockMetadata:
    """One sealed block, as the sampler needs to see it — and no columns.

    Every field is read from the block's own ``manifest.json``; the digests are
    the producer's, copied verbatim.

    Attributes:
        block_id: How the ledger addresses this block.
        root: The block directory, holding its ``manifest.json`` and columns.
        split: The split label the producer sealed it with.
        units: Sampling units in the block — the granularity a plan slot cannot
            be cut below.
        frames: Rows in the ``frame`` space, which is what a batch counts.
        task_names: The task dictionary the block carries, in manifest order.
        column_digests: Per-column digests, read from the manifest's ``digests``
            field. Never recomputed.
        block_digest: The block's own digest, likewise verbatim.
    """

    block_id: BlockId
    root: Path
    split: str | None
    units: int
    frames: int
    task_names: tuple[str, ...]
    column_digests: Mapping[str, str]
    block_digest: str


class ReadyBlocks:
    """The sealed blocks of one tier, read as JSON — the sampler handoff.

    Walks the blocks tier and parses each block's ``manifest.json`` with stdlib
    :mod:`json`. Nothing here opens a column, imports torch or constructs a
    sampler: building ``TaskMixtureBatchSampler`` is molnex's job, and this
    class only guarantees that the surface it needs is available without either
    repo importing the other.

    Args:
        tier: The tier holding sealed blocks, usually the one over
            ``conveyor/blocks``. Read only — reading manifests writes no ledger
            transition.
    """

    def __init__(self, tier: TierStore) -> None:
        self._tier = tier

    def metadata(self) -> tuple[BlockMetadata, ...]:
        """Every sealed block in the tier, in block-key order.

        A directory with no ``manifest.json`` is skipped rather than refused: it
        is a block being written, not a broken one, and the file appearing is
        precisely the event that makes it readable.

        Returns:
            One :class:`BlockMetadata` per sealed block.

        Raises:
            BlockNotSealed: If a manifest is present but does not claim
                ``sealed``.
            UnsupportedBlockFormat: If a manifest declares another format or
                schema version, is unreadable, or omits a field the format it
                declares promises.
        """
        found: list[BlockMetadata] = []
        for block in sorted(self._tier.entries(), key=lambda entry: entry.key()):
            root = self._tier.path_for(block)
            path = root / _MANIFEST_NAME
            if not path.is_file():
                continue
            found.append(self._read(block, root, self._document(path)))
        return tuple(found)

    @staticmethod
    def _document(path: Path) -> Mapping[str, Any]:
        """One manifest, parsed, with a typed refusal for anything unreadable."""
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise UnsupportedBlockFormat(f"{path} could not be read ({error}).") from error
        except ValueError as error:
            raise UnsupportedBlockFormat(f"{path} is not valid JSON ({error}).") from error
        if not isinstance(document, Mapping):
            raise UnsupportedBlockFormat(
                f"{path} holds a JSON {type(document).__name__}, not an object; a block "
                f"manifest is one {_BLOCK_FORMAT} object."
            )
        return document

    @classmethod
    def _read(cls, block: BlockId, root: Path, document: Mapping[str, Any]) -> BlockMetadata:
        """Project one validated manifest onto the fields the sampler needs."""
        declared = document.get("format")
        version = document.get("schema_version")
        if declared != _BLOCK_FORMAT or version != _SCHEMA_VERSION:
            raise UnsupportedBlockFormat(
                f"{root} declares format {declared!r} schema_version {version!r}; molhub "
                f"reads {_BLOCK_FORMAT} version {_SCHEMA_VERSION}. A future layout read "
                "through today's field names is a wrong answer, not a partial one."
            )
        if document.get("sealed") is not True:
            raise BlockNotSealed(
                f"{root} reports sealed={document.get('sealed')!r}. READY is conjunctive, "
                "so a block that does not claim to be sealed is not one a consumer may read."
            )
        rows = document.get("rows")
        if not isinstance(rows, Mapping):
            raise UnsupportedBlockFormat(
                f"{root} carries rows={rows!r}; {_BLOCK_FORMAT} counts its rows per space, "
                "and a block that does not is not the format it declares."
            )
        return BlockMetadata(
            block_id=block,
            root=root,
            split=cls._field(root, document, "split"),
            units=cls._field(root, document, "units"),
            frames=cls._field(root, rows, _FRAME_SPACE),
            task_names=tuple(cls._field(root, document, "task_names")),
            # Copied, never computed: `digests` is the producer's spelling and
            # its values are the producer's numbers.
            column_digests=MappingProxyType(dict(cls._field(root, document, "digests"))),
            block_digest=cls._field(root, document, "block_digest"),
        )

    @staticmethod
    def _field(root: Path, document: Mapping[str, Any], name: str) -> Any:
        """Read one field the declared format promises, refusing its absence."""
        if name not in document:
            raise UnsupportedBlockFormat(
                f"{root} declares {_BLOCK_FORMAT} but its manifest carries no {name!r}. "
                "molhub reads eight fields and invents none of them."
            )
        return document[name]
