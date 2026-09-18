"""One split, walked one published file at a time, inside a byte budget.

``load_dataset(name, split=..., streaming=True)`` hands back a
:class:`StreamingSplitDataset`: it walks the dataset's published files in
manifest order, keeps **at most one of them on local disk**, and yields the
records of one split as the ``Sequence[Frame]`` the
dataset's own reader builds. ``.take(n)`` bounds the walk in HuggingFace
spelling.

**The residency rule, in the order it happens** (D7, revised after the spec's
own audit). Per published file, in manifest order:

1. Refuse before fetching: the file's declared size plus whatever this walk
   still holds must fit ``disk_budget``. A file the budget cannot hold at all is
   a :class:`ValueError` naming both numbers — checked *before* the transfer, or
   the bound would be a report rather than a bound.
2. :class:`~molhub.conveyor.transfer.ShardTransfer` brings the bytes here and
   re-verifies size and digest against the manifest. The path it returns is
   where the bytes really are — the fetcher's own cache key — so the delete in
   step 5 deletes what was fetched rather than a second copy of it.
3. ``READY`` is recorded: verified local bytes, and a claim is taken on them for
   as long as they stay.
4. The file is opened, its records are read in file order, and only the ones
   this split claims are yielded.
5. On exhaustion — or wherever a bounded ``take(n)`` walk stops — the reader
   handle is closed **first**, ``CONSUMED`` is recorded, the fetched file is
   unlinked, and only then is ``REMOTE`` recorded and the claim released. Bytes
   reclaim when the handle closes, and ``REMOTE`` says nothing is local, so
   writing it while the bytes were still there would be a false statement in a
   durable file.

**A crash is not a consumption.** Those five steps used to run out of one
``finally``, which cannot tell exhaustion, an early stop and a reader that
*raised* apart. For a reader whose exception is propagating, ``CONSUMED`` claims
a file was read to the end, the closing ``REMOTE`` claims it is gone, and the
delete makes both true by throwing away verified bytes somebody paid for — three
false statements and one expensive one, and the next run re-downloads a 4 GB file
after a decode bug. What an interrupted walk owes is the *release*: the handle
closed (it holds the bytes open) and the claim given up (it is not reading any
more). Nothing else. An early ``take(n)`` stop arrives as ``GeneratorExit``, which
is not a failure — that walk read exactly what it was asked for — so it keeps the
full teardown.

The accepted wrinkle: after a crash the bytes are on disk while this walk's last
recorded state for that file is ``READY`` with the claim released. That is not a
leak — it is the state a byte-budget eviction already knows how to reclaim, and
``READY`` is *true*: the bytes are here and they verified. The next walk's
transfer re-verifies the digest on the cache hit, so re-using them is not a
matter of trusting the crash.

A linear walk needs no plan-ordered eviction — its whole residency rule is
"delete what was used, refuse what does not fit" — which is why
:class:`~molhub.conveyor.tier.TierStore` is deliberately not on this path. It
serves the full conveyor driver, and ``molhub cache status`` still reports its
tiers unchanged.

**The bookkeeping stays invisible.** No value this module returns and no message
it raises names the machinery underneath (ac-003): a file that cannot fit is
refused with a :class:`ValueError` about ``disk_budget`` rather than with a typed
error from the layer below, a manifest that publishes no checksum is refused with
a :class:`ValueError` naming the coordinate and the file rather than with the
projection's own typed error about an artifact role, and a record key outside the
split table's key space is diagnosed without the transport noun
:class:`~molhub.loader.mapstyle.UnknownRecordKey` can afford on the map-style
path. A record's own ``meta["source_id"]`` still names the published file it came
from: that is the record's provenance, not the walk's vocabulary, and deleting it
would cost traceability to buy a word.

Reference:
    ``.claude/specs/hf-facade-04-streaming-prepare.md`` § Design (D7) and
    ac-001 to ac-003, under the 2026-08-15 operator override recorded in
    ``.claude/notes/notes.md`` (``mol:note:topic:hf-style-api``).
"""

from __future__ import annotations

from collections.abc import Generator, Iterator, Sequence
from datetime import timedelta
from pathlib import Path

from molpy import Frame

from molhub.conveyor import DEFAULT_BUDGET_BYTES
from molhub.conveyor.block import BlockState
from molhub.conveyor.ledger import Ledger
from molhub.conveyor.roster import BlockRoster, RemoteBlock, RosterError
from molhub.conveyor.splits import _SplitTable
from molhub.conveyor.transfer import ShardTransfer
from molhub.dataset.themol import THEMolHessian, THEMolMBIS, THEMolTorsionScan
from molhub.dataset.universal_class_i import Class1Universal2026, CollectionRole
from molhub.loader.mapstyle import UnknownRecordKey
from molhub.manifest import Manifest

__all__ = ["PublishedParts", "StreamingSplitDataset", "BoundedStream"]

# How long a walk claims the file it is currently reading. A documented bound on
# one file's residency, not a renewal mechanism: the claim is given up when the
# bytes are deleted, which is what it was taken to cover.
_RESIDENCY_TTL = timedelta(hours=1)

# The dataset classes whose artifacts are published as walkable parts. Spelled as
# a union of the three concrete classes rather than as their private base, so a
# fourth one is added here on purpose rather than by inheriting.
_ShardDefinition = type[THEMolHessian] | type[THEMolMBIS] | type[THEMolTorsionScan]


class PublishedParts:
    """The files one dataset is delivered in, and the role they are published under.

    Two facts out of one lookup, so they cannot drift: *which parts exist*, with
    the size and digest the registry manifest declares for each, and *the
    collection role name* they are published under. The bookkeeping addresses a
    part by that name and a prepared unit is labelled with it, so ``molhub cache
    coverage`` counts exactly the parts a streaming walk consumed instead of
    reporting zero against a second naming of the same files.

    Nothing here re-derives anything: the parts are
    :class:`~molhub.conveyor.roster.BlockRoster`'s projection of the manifest,
    and the role comes from the published collection that declares this
    coordinate as one of its sources.

    **A manifest with no checksums is refused here, in this layer's voice.** A
    walk re-verifies every delivered file against the checksum the manifest
    declares — that is what makes deleting it after reading safe — so a manifest
    declaring none cannot honestly be walked at all. The projection underneath
    already says so, with a typed error quoting the artifact role, which is
    exactly the vocabulary this layer keeps off a user's screen. So it is
    restated as a :class:`ValueError` — the shape this layer's sibling refusals
    already use — naming the dataset, the files the checksum is missing from, and
    the way to read it anyway.

    Args:
        manifest: The registry manifest of the **resolved** coordinate.

    Raises:
        KeyError: If no published collection role names this coordinate. There is
            no fallback name: a part addressed under an invented role would be
            invisible to every report keyed on the real one.
        ValueError: If the manifest declares a file with no size or no checksum,
            which is a manifest that cannot honestly be walked under a budget.
    """

    def __init__(self, manifest: Manifest) -> None:
        self._role = self._published_role(manifest)
        try:
            self._roster = BlockRoster(manifest, self._role)
        except RosterError as error:
            raise ValueError(self._unverifiable(manifest)) from error

    @property
    def task(self) -> str:
        """The collection role name every part of this dataset is published under."""
        return self._role.name

    def files(self) -> tuple[RemoteBlock, ...]:
        """Every published part, in manifest order — which is the record order."""
        return self._roster.blocks()

    @staticmethod
    def _unverifiable(manifest: Manifest) -> str:
        """Why this dataset cannot be walked, naming the files rather than a role.

        The filename is what the publishing platform shows and what a reader can
        ask its publisher about; the role is transport, and quoting it is the
        leak itself.

        Args:
            manifest: The manifest that cannot be projected into walkable parts.

        Returns:
            The refusal, naming the dataset, every file whose checksum is
            missing, and the way to read the dataset anyway.
        """
        undeclared = [
            artifact.filename
            for artifact in manifest.artifacts.values()
            if artifact.digest is None or artifact.size is None
        ]
        return (
            f"{manifest.coordinate.canonical} cannot be read one file at a time: its "
            f"manifest publishes no checksum for {', '.join(undeclared) or 'its files'}. "
            "Every delivered file is re-verified against a published checksum before it is "
            "read and thrown away again, so there is nothing to verify these against. Ask "
            "whoever published it to record the checksums, or read the dataset whole with "
            "load_dataset(name, streaming=False), which verifies nothing and "
            "keeps what it fetches."
        )

    @staticmethod
    def _published_role(manifest: Manifest) -> CollectionRole:
        """The collection role declaring *manifest*'s coordinate as one of its sources."""
        coordinate = manifest.coordinate.canonical
        collection = Class1Universal2026().load()
        for role in collection.roles:
            if coordinate in role.source_coordinates:
                return role
        raise KeyError(
            f"{coordinate} is not one of the sources {list(collection.source_coordinates)} "
            f"that {collection.coordinate} publishes in parts, so there is no ordered set "
            "of files to walk. Read it whole instead."
        )


class BoundedStream:
    """The first *n* records of a walk, and the walk stopped where they end.

    Returned by :meth:`StreamingSplitDataset.take`, in HuggingFace's spelling.
    Iterating it iterates the underlying walk and closes it at the bound, so the
    file the stop happened inside is released there and then — the same release
    an exhausted walk does, at a different point.

    Args:
        source: The walk to bound.
        limit: How many records to yield. ``0`` yields none.

    Raises:
        ValueError: If *limit* is negative. A negative bound is not a smaller
            walk; it is a typo that would silently yield everything or nothing.
    """

    def __init__(self, source: StreamingSplitDataset, limit: int) -> None:
        if limit < 0:
            raise ValueError(f"take(n) counts records, so n must not be negative; got {limit!r}.")
        self._source = source
        self._limit = limit

    @property
    def limit(self) -> int:
        """How many records this view yields at most."""
        return self._limit

    def __repr__(self) -> str:
        return f"BoundedStream({self._source!r}, limit={self._limit})"

    def __iter__(self) -> Iterator[Sequence[Frame]]:
        """Yield at most :attr:`limit` records, then close the walk behind them."""
        if self._limit == 0:
            return
        records = self._source.__iter__()
        try:
            taken = 0
            for record in records:
                yield record
                taken += 1
                if taken == self._limit:
                    break
        finally:
            # Closing the generator is what runs the walk's own release, at the
            # record it stopped on. Leaving it to garbage collection would make
            # "the bytes are gone" a claim about when the collector ran.
            records.close()


class StreamingSplitDataset:
    """One split of a published dataset, walked under a byte budget.

    Every collaborator is an explicit narrow parameter: the walk holds no
    default it could silently fall back on, and there is no ambient context it
    reaches into. It is re-iterable — a second pass re-fetches, by design, since
    the first pass deleted what it read.

    Args:
        definition: The dataset class whose reader parses these files. It is
            constructed per file over a local path, so opening a part costs no
            second transfer.
        split: Which split this walk yields.
        table: The provenance-verified split assignment, keyed by record uuid.
        parts: The published parts, in the order they are walked.
        transfer: How one part's bytes are brought here and verified.
        ledger: Where this walk's residency facts go — the one file
            :func:`~molhub.conveyor.default_ledger_path` names, shared with
            ``molhub cache coverage``.
        disk_budget: How many bytes of fetched parts may sit on local disk at
            once. Defaults to the 40 GB rolling working set.

    Raises:
        KeyError: If *table* records no such split; the message names the splits
            it does record, which is what discovery would have said.
        ValueError: If *disk_budget* is not positive.
    """

    def __init__(
        self,
        definition: _ShardDefinition,
        *,
        parts: Sequence[RemoteBlock],
        transfer: ShardTransfer,
        ledger: Ledger,
        disk_budget: int = DEFAULT_BUDGET_BYTES,
        table: _SplitTable | None = None,
        split: str | None = None,
    ) -> None:
        if split is not None:
            if table is None:
                raise TypeError("a filtered walk needs the published assignment table")
            counts = table.counts()
            if split not in counts:
                raise KeyError(
                    f"{split!r} is not a split of this table, which records {sorted(counts)}."
                )
        if disk_budget <= 0:
            raise ValueError(
                f"disk_budget is a number of bytes and must be positive; got {disk_budget!r}. "
                "A walk with no room cannot read anything at all."
            )
        self._definition = definition
        self._split = split
        self._table = table
        self._parts = tuple(parts)
        self._transfer = transfer
        self._ledger = ledger
        self._disk_budget = disk_budget

    @property
    def split(self) -> str | None:
        """The split this walk yields — ``None`` for an unfiltered walk."""
        return self._split

    @property
    def disk_budget(self) -> int:
        """How many bytes of fetched files may be on disk at once."""
        return self._disk_budget

    def __repr__(self) -> str:
        return (
            f"StreamingSplitDataset(split={self._split!r}, files={len(self._parts)}, "
            f"disk_budget={self._disk_budget})"
        )

    def take(self, n: int) -> BoundedStream:
        """Return a walk of at most *n* records.

        Args:
            n: How many records to yield.

        Returns:
            A :class:`BoundedStream` — an iterable dataset like this one, which
            stops at the bound and releases the file it stopped inside.
        """
        return BoundedStream(self, n)

    def __iter__(self) -> Generator[Sequence[Frame], None, None]:
        """Walk the parts in order, yielding this split's records.

        Yields:
            One ``Sequence[Frame]`` per record of
            this split, in the order the published files hold them.

        Raises:
            ValueError: If a part does not fit ``disk_budget``.
            UnknownRecordKey: If a part's record key is outside the split
                table's key space.
        """
        resident = 0
        for part in self._parts:
            # 1. The bound, before the bytes: a refusal after the transfer would
            #    be a report of what was already spent.
            self._require_room(part, resident=resident)

            # 2-3. Bring the bytes here, verified, and record that they are here.
            self._ledger.append(part.id, BlockState.REMOTE)
            path = self._transfer.transfer(part)
            self._ledger.append(part.id, BlockState.READY, size_bytes=part.size)
            self._ledger.lease([part.id], ttl=_RESIDENCY_TTL)
            resident += part.size

            # 4. Read the part in file order, keeping this split's records.
            records = self._definition(path).load(part.id.block_id)
            try:
                for index, key in enumerate(records.keys()):
                    if self._split is None or self._split_of(key) == self._split:
                        yield records[index]
            except GeneratorExit:
                # A bounded walk stopping at its own limit: this file was read
                # to the point the caller asked for, which is a consumption.
                records.close()
                self._reclaim(part, path)
                raise
            except BaseException:
                # A reader that raised: the release, and nothing else. See the
                # module docstring — CONSUMED, the delete and the closing REMOTE
                # would each be a false statement about an abandoned file, and
                # the delete would throw away verified bytes somebody paid for.
                records.close()
                self._ledger.release([part.id])
                raise
            # 5. Exhausted: handle first, then the delete, then the claim.
            records.close()
            self._reclaim(part, path)
            resident -= part.size

    def _reclaim(self, part: RemoteBlock, path: Path) -> None:
        """Record *part* consumed, delete its bytes, and give up the claim.

        The order is the contract: the reader handle is already closed, because
        bytes only reclaim once it lets go of them, and ``REMOTE`` claims nothing
        is local — so writing it before the delete would be a false statement in
        a durable file.

        Args:
            part: The published file that was read.
            path: Where its bytes were delivered — the transfer's own path, so
                this deletes what was fetched rather than a second copy of it.
        """
        self._ledger.append(part.id, BlockState.CONSUMED)
        path.unlink(missing_ok=True)
        self._ledger.append(part.id, BlockState.REMOTE)
        self._ledger.release([part.id])

    def _require_room(self, part: RemoteBlock, *, resident: int) -> None:
        """Refuse a part this walk has no room for, naming both numbers."""
        if part.size + resident <= self._disk_budget:
            return
        raise ValueError(
            f"{part.filename} is {part.size} bytes and this walk may keep {self._disk_budget} "
            f"bytes on disk ({resident} of them already in use), so it cannot be read one "
            "piece at a time. Raise disk_budget to at least the size of the largest file, or "
            "read the dataset whole with load_dataset(..., streaming=False)."
        )

    def _split_of(self, key: str) -> str:
        """The split *key* belongs to, refusing loudly outside the key space."""
        if self._table is None:
            raise RuntimeError(
                "_split_of on an unfiltered walk: the constructor admits a "
                "table-less walk only with split=None, and iteration checks "
                "split before asking for a key's split"
            )
        try:
            return self._table.split_of(key)
        except KeyError as error:
            raise UnknownRecordKey(
                f"Record key {key!r} has no row in the split table, which is keyed by record "
                "uuid. This dataset's declared key space is the uuid one; the declared "
                "alternative is molecular identity (each record's mapped_isomeric_smiles "
                "hashed to an identity, looked up in identity_splits.csv.gz), and it is "
                "selected by declaration, never discovered at runtime. No split is defaulted: "
                "a fabricated one leaks between train and test undetected."
            ) from error
