"""One downloaded shard in, sealed split-pure blocks out — the CPU half.

:class:`PrepareJob` is the middle of the three-stage conveyor: it encodes each
record of one downloaded THEMol shard, routes it to its molecule-level split,
and feeds it **whole** to a block writer, then reports exactly the evidence a
READY ledger record needs. It writes no ledger, deletes no shard and bounds no
queue — ``-01-ledger`` and the chain's residency sub-spec own those. The value it
returns, :class:`PreparedBlocks`, is the seam: one entry per sealed root, which
the conveyor driver (the single ledger-transition writer) turns into one READY
record each.

The writer is injected
---------------------

``writer_factory`` has no default. This module imports no block writer, so
``import molhub.conveyor.prepare`` succeeds in a base install, and
:class:`PrepareJob` is unit-tested against an injected fake.
:class:`BlockWriterLike` / :class:`BlockWriterFactory` are the seam;
``tests/test_conveyor/test_layering.py`` enforces the import rule against the
source text.

The identity drop is deliberate. :attr:`RawUnit.identity`'s one job — choosing
which writer a unit goes to — is finished by the time the writer's
``append_unit`` is called, so an adapter passes the payload and drops the
identity. A sealed block therefore records
``key`` (``molecule_id`` / ``scan_id``) only, and a post-hoc split-purity audit
reads the *ledger*, where each READY record names a root together with its split,
never the block bytes.

Three alternatives were considered and rejected, recorded here so they are not
re-litigated:

* an **entry-point plugin**, where molnex discovers a molhub-side converter —
  needs registration on the molnex side, i.e. a change in the repo that must
  stay dataset-agnostic;
* a **subprocess converter with a tensor-free wire format** — a third on-disk
  copy of every block, which is precisely the byte budget the conveyor exists to
  respect (I3);
* **seam inversion**, molnex pulling from molhub — contradicts the strategy's
  ownership split (§ 12), where the prepare stage is molhub's.

Reference:
    ``.claude/specs/streaming-data-tiers-03-conveyor-03-prepare.md`` §§ 1, 4, 5.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from molhub.conveyor.encoder import RawUnit, THEMolUnitEncoder
from molhub.conveyor.errors import (
    BlockFormatError,
    IncompleteProvenanceError,
    UnroutableUnitError,
)

__all__ = [
    "BlockWriterLike",
    "BlockWriterFactory",
    "PreparedBlock",
    "PreparedBlocks",
    "PrepareJob",
]

_MANIFEST_NAME = "manifest.json"

# A sealed block records these four provenance keys. molhub checks that they
# are present and nothing about their contents, before a writer is opened.
_PROVENANCE_KEYS = ("source", "generator", "created_at", "units")

# The strategy's worked example. Production blocks are 1-5 GB; a test uses a
# tiny value to exercise the size fan-out.
_DEFAULT_MAX_BLOCK_BYTES = 2_000_000_000


@runtime_checkable
class BlockWriterLike(Protocol):
    """The four members of molnex's ``BlockWriter`` this stage actually uses.

    Deliberately narrower than the real class: no ``resume``, no reader, no
    manifest accessor. A required-side view of a collaborator, in the shape of
    :class:`~molhub.dataset.hub.ArtifactHub`, so the unit tests can inject a fake
    and the base environment never needs torch.

    Four members — ``append_unit``, ``committed_bytes``, ``unit_count``,
    ``seal``. The shape came from molnex's deleted ``BlockWriter``; it is now
    simply what this stage asks of any writer it is given.
    """

    def append_unit(self, unit: Any) -> int:
        """Append one whole sampling unit and return its index."""
        ...

    @property
    def committed_bytes(self) -> int:
        """Committed column payload in bytes — what the ceiling is compared to."""
        ...

    @property
    def unit_count(self) -> int:
        """Units committed to this block so far."""
        ...

    def seal(self) -> None:
        """Finalize the block; its sealed manifest is the only READY witness."""
        ...


@runtime_checkable
class BlockWriterFactory(Protocol):
    """How a block is opened — the *constructor* seam, not a ``make_*`` wrapper.

    Satisfied by a writer class object itself (a caller's writer, a test fake),
    which is why this is a class seam and not a ``create_writer`` function.
    ``split`` is a constructor argument so that split purity is structural
    rather than checked: a writer is opened for one split and cannot be handed a
    unit from another.
    """

    def __call__(self, root: Path, *, split: str, provenance: Mapping[str, Any]) -> BlockWriterLike:
        """Open a writer for one block at *root* holding exactly one *split*."""
        ...


@dataclass(frozen=True)
class PreparedBlock:
    """READY evidence for one sealed root, verified against its own manifest.

    Every field is either something the job counted or something the sealed
    manifest states; nothing is assumed. ``block_digest`` in particular is
    **read, never recomputed** — recomputation is ``BlockReader.verify()``'s job
    in molnex, and this stage is not the fetch boundary.

    Attributes:
        root: The sealed block directory.
        split: The one split this block holds.
        unit_count: Units the writer committed, cross-checked against the
            manifest's ``units``.
        frame_count: Frames summed from the appended units — the per-pass
            coverage number the residency stage asks for. The block format
            counts units, not frames, so this is molhub's to carry.
        committed_bytes: The writer's committed column payload.
        block_digest: The manifest's ``block_digest``, as written.
    """

    root: Path
    split: str
    unit_count: int
    frame_count: int
    committed_bytes: int
    block_digest: str


@dataclass(frozen=True)
class PreparedBlocks:
    """Everything one prepare pass produced, in the order it sealed it.

    The complete input for the READY records of one shard: the driver appends
    one ledger record per entry, then advances the raw shard READY -> CONSUMED.

    Attributes:
        name: The shard's identity, e.g. ``"themol-torsion-scan-shard-000"``.
        blocks: One entry per sealed root — a split fan-out of up to three plus
            a size fan-out within each split.
    """

    name: str
    blocks: tuple[PreparedBlock, ...]


@dataclass
class _OpenBlock:
    """One writer that is currently taking units, with what it has taken."""

    writer: BlockWriterLike
    root: Path
    split: str
    frame_count: int = field(default=0)


class PrepareJob:
    """Turns one downloaded shard into sealed, split-pure, unit-aligned blocks.

    Every collaborator is an explicit narrow parameter — there is no context
    blob, and the job holds no default it could silently fall back on. It is
    single-shot: :meth:`run` consumes *records* once, and a second call raises,
    because re-running would re-open roots that already hold sealed blocks.

    Args:
        records: The shard's records, in shard order — typically a
            ``THEMolShardDataset``, whose ``__getitem__`` already returns one
            complete sampling unit per index: a ``Sequence[Frame]``.
        encoder: The per-shard encoder; its ``task`` labels every unit.
        split_of: Molecular identity -> ``"train"`` / ``"val"`` / ``"test"``.
            A plain mapping, so this class needs no file to be tested; the
            caller builds it from
            :meth:`~molhub.conveyor.splits._SplitTable.from_identity`, the
            provenance-verified loader of the hot-tier identity table. Routing
            is a lookup and never a derivation: streaming re-splits nothing.
        writer_factory: How a block is opened — see :class:`BlockWriterFactory`.
        root: Directory the block roots are created under.
        name: The shard's identity; block roots are ``<name>-<split>-<seq>``.
        provenance: Opaque provenance, passed to every writer unchanged. Must
            carry molnex's four required keys.
        max_block_bytes: Seal-and-open-the-next threshold, checked *after* each
            append, so a unit that alone exceeds it still lands whole in its own
            block. Production range is 1-5 GB.

    Raises:
        ValueError: *max_block_bytes* is not positive.
        IncompleteProvenanceError: *provenance* is missing a required key. Both
            fire at construction, before any writer is opened, so a defect
            cannot surface halfway through a shard — or in an environment where
            molnex is not even importable.
    """

    def __init__(
        self,
        records: Iterable[Any],
        *,
        encoder: THEMolUnitEncoder,
        split_of: Mapping[str, str],
        writer_factory: BlockWriterFactory,
        root: str | Path,
        name: str,
        provenance: Mapping[str, Any],
        max_block_bytes: int = _DEFAULT_MAX_BLOCK_BYTES,
    ) -> None:
        if max_block_bytes <= 0:
            raise ValueError(
                f"max_block_bytes must be positive; got {max_block_bytes!r}. A zero or "
                "negative ceiling is not a smaller block, it is one block per unit forever — "
                "the production range is 1-5 GB."
            )
        missing = [key for key in _PROVENANCE_KEYS if key not in provenance]
        if missing:
            raise IncompleteProvenanceError(
                f"provenance for shard {name!r} is missing {missing}; a block records "
                f"{list(_PROVENANCE_KEYS)} (their contents are the producer's business). "
                "Checked here so the defect surfaces before a writer is opened, "
                "not halfway through a shard."
            )
        self._records = records
        self._encoder = encoder
        self._split_of = split_of
        self._writer_factory = writer_factory
        self._root = Path(root)
        self._name = name
        self._provenance = dict(provenance)
        self._max_block_bytes = max_block_bytes
        self._ran = False

    def run(self) -> PreparedBlocks:
        """Encode, route and seal the whole shard.

        Each record becomes one whole unit, is routed by its molecule's split,
        and is appended to that split's open block — opened lazily, on the first
        unit that needs it, so a split with no members in this shard produces no
        directory and ``seal()`` is never called on an empty block. The size
        check runs after the append, never before, which is why the ceiling can
        open a new block but can never cut a unit.

        Returns:
            The READY evidence for every root this pass sealed.

        Raises:
            RuntimeError: :meth:`run` was already called on this job.
            UnroutableUnitError: A unit's molecular identity is absent from
                ``split_of``.
            BlockFormatError: A sealed block's manifest does not witness what
                molhub would report.
            UnsupportedRecordError: A record that is not a ``Sequence[Frame]``.
            IncompleteRecordError: A record that cannot be encoded whole.
        """
        if self._ran:
            raise RuntimeError(
                f"PrepareJob for shard {self._name!r} has already run; a job is single-shot "
                "because a second pass would re-open roots that already hold sealed blocks "
                "(molnex refuses that loudly). Build a new job, and let the ledger decide "
                "whether the existing blocks are to be kept or deleted."
            )
        self._ran = True

        open_blocks: dict[str, _OpenBlock] = {}
        next_sequence: dict[str, int] = {}
        sealed: list[PreparedBlock] = []

        for record in self._records:
            unit = self._encoder.encode(record)
            split = self._route(unit)
            block = open_blocks.get(split)
            if block is None:
                block = self._open(split, next_sequence)
                open_blocks[split] = block
            block.writer.append_unit(unit)
            block.frame_count += unit.n_frames
            if block.writer.committed_bytes >= self._max_block_bytes:
                sealed.append(self._seal(open_blocks.pop(split)))

        for split in tuple(open_blocks):
            sealed.append(self._seal(open_blocks.pop(split)))
        return PreparedBlocks(name=self._name, blocks=tuple(sealed))

    # -- routing -----------------------------------------------------------

    def _route(self, unit: RawUnit) -> str:
        """The split *unit*'s molecule belongs to, or a refusal naming both."""
        split = self._split_of.get(unit.identity)
        if split is None:
            raise UnroutableUnitError(
                f"unit {unit.key!r} carries molecular identity {unit.identity!r}, which the "
                "split table does not assign. There is no default split and no "
                "re-splitting: a guessed assignment leaks a molecule between train and test "
                "with nothing able to detect it afterwards. Check that the shard and the "
                "class1-universal-splits version were built from the same molecule set."
            )
        return split

    def _open(self, split: str, next_sequence: dict[str, int]) -> _OpenBlock:
        """Open the next block of *split*, numbering roots per split."""
        sequence = next_sequence.get(split, 0)
        next_sequence[split] = sequence + 1
        root = self._root / f"{self._name}-{split}-{sequence:03d}"
        writer = self._writer_factory(root, split=split, provenance=self._provenance)
        return _OpenBlock(writer=writer, root=root, split=split)

    # -- sealing -----------------------------------------------------------

    def _seal(self, block: _OpenBlock) -> PreparedBlock:
        """Seal one block and read back the evidence its manifest witnesses."""
        block.writer.seal()
        document = self._manifest(block.root)
        unit_count = block.writer.unit_count

        if document.get("sealed") is not True:
            raise BlockFormatError(
                f"{block.root} reports sealed={document.get('sealed')!r} after seal() "
                "returned. The sealed manifest is the only witness of READY, so a block "
                "that does not claim it has not become READY."
            )
        if document.get("units") != unit_count:
            raise BlockFormatError(
                f"{block.root} records {document.get('units')!r} units but its writer "
                f"committed {unit_count}. One of the two lost a unit, and a coverage number "
                "nobody can reconcile is worse than none."
            )
        if document.get("split") != block.split:
            raise BlockFormatError(
                f"{block.root} records split {document.get('split')!r} but was opened for "
                f"{block.split!r}. Split purity is what the whole fan-out exists to "
                "guarantee; a block that disagrees with its own writer breaks it."
            )
        digest = document.get("block_digest")
        if not isinstance(digest, str) or not digest:
            raise BlockFormatError(
                f"{block.root} carries block_digest {digest!r}. molhub reads the digest and "
                "never recomputes it (that is BlockReader.verify()'s job), so a block "
                "without one has nothing a READY record could quote."
            )

        return PreparedBlock(
            root=block.root,
            split=block.split,
            unit_count=unit_count,
            frame_count=block.frame_count,
            committed_bytes=block.writer.committed_bytes,
            block_digest=digest,
        )

    @staticmethod
    def _manifest(root: Path) -> Mapping[str, Any]:
        """The sealed manifest of *root*, as a JSON object.

        Four fields are read (``split``, ``units``, ``sealed``, ``block_digest``).
        The writer's ``format`` string is left as recorded.
        """
        path = root / _MANIFEST_NAME
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise BlockFormatError(
                f"{path} could not be read after seal() returned ({error}); without it "
                "nothing witnesses that this block is READY."
            ) from error
        except ValueError as error:
            raise BlockFormatError(f"{path} is not valid JSON ({error}).") from error
        if not isinstance(document, Mapping):
            raise BlockFormatError(f"{path} holds a JSON {type(document).__name__}, not an object.")
        return document
