"""The i-th record of a split, and an honest account of what asking costs.

``ds[i]`` needs to know which shard owns row *i*, and no published artifact says.
Building that answer eagerly would require every shard on local disk — 28.9 GiB
for THEMol MBIS, 4.4 TiB for torsion-relax, 5.9 TiB for the whole collection —
which is exactly the residency invariant the streaming tiers exist to keep. So
:class:`ShardIndex` builds the answer **one shard at a time**, from the group
keys ``THEMolShardDataset`` already listed, and memoizes it under the same
:class:`~molhub.conveyor.tier.DerivedLayout` every other derived artifact uses.

The consequence is stated rather than hidden: a map-style view fetches the shard
owning the row you ask for, plus every earlier shard it has not indexed yet.
Sequential access pays once per shard; random access to a late row pays for the
walk. That is HuggingFace's own ``load`` semantic — it downloads — only
charged out loud.

**One key space, declared, never guessed.** A shard's group keys are read as
record uuids, which is the key space ``mbis_uuid_splits.csv.gz`` and its siblings
hold. A key the table has no row for raises :class:`UnknownRecordKey` naming both
that key space and the declared alternative (molecular identity, via
``mapped_isomeric_smiles`` → ``THEMolUnitEncoder.identity`` →
``identity_splits.csv.gz``). There is no runtime fallback: a fabricated split
leaks between train and test with nothing to detect it.

**And the cost is said out loud, before it is spent.** :class:`DownloadNotice`
is the one thing in this package that writes to stderr: ``ds[0]`` fetches a
published file — 3.9 GiB of real THEMol shard — and that was documented and
never *said*. It states the byte total for a human and the raw count for whoever
reconciles it against the manifest, on stderr so a piped record or a captured
``print(info)`` is unchanged by it, and it is silent when nothing will move: the
file is already in the cache, or was already announced. A warning printed on
every cache hit is one nobody reads by the third call, and being read is the
whole point of it. :class:`~molhub.loader.builder.DatasetBuilder` builds the same
type for its ``.info`` path, so what a dataset costs is stated in one sentence
however it is opened, rather than in one wording here and another there.

Reference:
    ``.claude/specs/hf-facade-03-builder-info.md`` § Design (D6), ac-004 and
    ac-005, under the 2026-08-15 operator override recorded in
    ``.claude/notes/notes.md`` (``mol:note:topic:hf-style-api``).
"""

from __future__ import annotations

import json
import operator
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from molpy import Frame

from molhub.conveyor.splits import _SplitTable
from molhub.conveyor.tier import DerivedLayout
from molhub.coordinate import Coordinate
from molhub.loader.info import ByteSize
from molhub.sources.blobs import BlobStore

__all__ = [
    "UnknownRecordKey",
    "DownloadNotice",
    "ShardRecords",
    "ShardSource",
    "ShardIndex",
    "SplitDataset",
]

#: What the memo of one shard's keys is called, and what wrote it. The layout
#: files it beside the artifact it describes, so a stale index is deletable by
#: the same rule as any other derived file.
_MEMO_SUFFIX = ".keys.json"
_GENERATOR = "molhub.loader.mapstyle.ShardIndex"


class UnknownRecordKey(KeyError):
    """A shard's record key is not in the split table's key space.

    Raised on the walk rather than inside the index, because the table is what
    the dataset holds and the index holds no opinion about splits. The message
    names both key spaces: the caller is holding the wrong table, or this
    dataset's keys need the declared identity route, and neither is something to
    resolve by defaulting a split.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self._message = message

    def __str__(self) -> str:
        return self._message


class DownloadNotice:
    """What a fetch is about to pull, said on stderr before it moves.

    One notice per set of published files, so a dataset opened through the
    façade warns once about each file it fetches, however many records are read
    out of it. It answers three questions in one sentence — why bytes are about
    to move, how many of them (humanized, through the same
    :class:`~molhub.loader.info.ByteSize` the report prints), and the raw count
    for a script — and it stays quiet whenever nothing will actually move.

    Args:
        coordinate: The **resolved** coordinate whose files these are; a notice
            that named an unversioned artifact would not say which release is
            being pulled.
        sizes: Declared byte size per role, from the registry manifest.
            Declared rather than measured: the files are not here, which is the
            whole question.
        because: How this notice opens — "Reading a record of", "Counting the
            splits of". The caller knows why it is about to fetch; this type
            knows how much and whether to say anything at all.
        home: The molhub home whose cache is probed. Probing is a read: it
            creates nothing and fetches nothing.
    """

    def __init__(
        self,
        *,
        coordinate: Coordinate,
        sizes: Mapping[str, int],
        because: str,
        home: str | Path | None = None,
    ) -> None:
        self._coordinate = coordinate
        self._sizes = dict(sizes)
        self._because = because
        self._blobs = BlobStore(home)
        self._announced: set[str] = set()

    def announce(self, *roles: str) -> None:
        """Say what fetching *roles* will pull, unless it will pull nothing.

        Silent for a role whose bytes are already in this home's cache — the
        bytes are on this machine, and announcing a download would be a lie
        printed often enough to train the reader to ignore the true one — and
        silent for one already announced, so a second record out of one open
        file says nothing.

        Args:
            roles: The roles about to be asked for, in the manifest's order.
        """
        pending = [role for role in roles if role not in self._announced and not self._cached(role)]
        self._announced.update(roles)
        size = sum(self._sizes.get(role, 0) for role in pending)
        if not size:
            return
        print(
            f"{self._because} {self._coordinate.canonical} will download {ByteSize(size)} "
            f"({size} B) first. The files stay in the molhub cache, so reading them again "
            "costs nothing.",
            file=sys.stderr,
        )

    def _cached(self, role: str) -> bool:
        """Whether *role*'s bytes already sit at the path a fetch would use."""
        return self._blobs.has(f"{self._coordinate.cache_path()}/{role}")


@runtime_checkable
class ShardRecords(Protocol):
    """One shard, already open: its record keys and its records."""

    def keys(self) -> tuple[str, ...]:
        """The shard's record keys, positionally aligned with ``self[i]``."""
        ...

    def __getitem__(self, index: int) -> Sequence[Frame]:
        """The record at *index*."""
        ...


@runtime_checkable
class ShardSource(Protocol):
    """Whatever turns a shard role into an open shard — a dataset definition."""

    def load(self, role: str) -> ShardRecords:
        """Fetch or locate the shard filed under *role* and open it."""
        ...


class ShardIndex:
    """Which records each shard holds, indexed lazily and memoized on disk.

    The one thing in this package that opens a shard. Both halves of that job
    are the same fact paid for once: the key list is memoized under *layout* so
    a second process never re-derives it, and the open shard is memoized in this
    object so reading two rows of one shard costs one fetch.

    Args:
        shards: The dataset definition to load shards through — anything with
            ``load(role)``, which is what the THEMol definitions are.
        coordinate: The **resolved** coordinate, which is what the memo is filed
            under: two revisions of one dataset have different keys.
        roles: The shard roles, in the order the registry manifest declares
            them. That order is the record order of the dataset.
        layout: Where the memo is written.
        notice: What says, on stderr, that a file is about to be pulled.
            ``None`` opens shards silently, which is what a caller that has
            already accounted for the bytes — or a test measuring fetches
            rather than warnings — wants.
    """

    def __init__(
        self,
        shards: ShardSource,
        *,
        coordinate: Coordinate,
        roles: Sequence[str],
        layout: DerivedLayout,
        notice: DownloadNotice | None = None,
    ) -> None:
        self._source = shards
        self._coordinate = coordinate
        self._roles = tuple(roles)
        self._layout = layout
        self._notice = notice
        self._keys: dict[str, tuple[str, ...]] = {}
        self._open: dict[str, ShardRecords] = {}

    @property
    def source(self) -> ShardSource:
        """The definition this index loads shards through."""
        return self._source

    @property
    def coordinate(self) -> Coordinate:
        """The resolved coordinate whose shards this indexes."""
        return self._coordinate

    @property
    def roles(self) -> tuple[str, ...]:
        """The shard roles, in the order they are walked."""
        return self._roles

    def keys(self, role: str) -> tuple[str, ...]:
        """The record keys the shard *role* holds, in shard order.

        Reads the memo when one exists, and otherwise opens the shard once,
        writes the memo and keeps the open shard for :meth:`shard`.

        Args:
            role: One of :attr:`roles`.

        Returns:
            The shard's record keys.

        Raises:
            KeyError: If *role* is not one of :attr:`roles`.
        """
        remembered = self._keys.get(role)
        if remembered is not None:
            return remembered
        self._require_role(role)
        memo = self._memo_path(role)
        keys = self._read_memo(memo) if memo.is_file() else self._derive(role, memo)
        self._keys[role] = keys
        return keys

    def shard(self, role: str) -> ShardRecords:
        """The open shard *role*, fetched at most once per process.

        Args:
            role: One of :attr:`roles`.

        Returns:
            The open shard, so that indexing it and reading a record of it are
            one fetch rather than two.

        Raises:
            KeyError: If *role* is not one of :attr:`roles`.
        """
        self._require_role(role)
        opened = self._open.get(role)
        if opened is None:
            if self._notice is not None:
                self._notice.announce(role)
            opened = self._source.load(role)
            self._open[role] = opened
        return opened

    def _require_role(self, role: str) -> None:
        """Refuse a role this artifact does not declare, naming the ones it does."""
        if role not in self._roles:
            raise KeyError(
                f"{self._coordinate.canonical} declares shards {list(self._roles)}, not {role!r}."
            )

    def _derive(self, role: str, memo: Path) -> tuple[str, ...]:
        """Index one shard by opening it, and write the memo that replaces it."""
        keys = tuple(self.shard(role).keys())
        self._write_provenance(memo.parent)
        memo.write_text(
            json.dumps(
                {"coordinate": self._coordinate.canonical, "role": role, "keys": list(keys)},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return keys

    def _memo_path(self, role: str) -> Path:
        """Where *role*'s memo lives; the artifact directory is created here."""
        directory = self._layout.artifact_dir(
            self._coordinate.namespace, self._coordinate.name, self._coordinate.version
        )
        return directory / f"{role}{_MEMO_SUFFIX}"

    def _write_provenance(self, directory: Path) -> None:
        """Attribute this memo, once — a derived artifact says who derived it."""
        if (directory / "metadata.json").is_file():
            return
        self._layout.write_metadata(
            directory,
            {
                "coordinate": self._coordinate.canonical,
                "generator": _GENERATOR,
                "generated_at": datetime.now(UTC).isoformat(),
                "describes": "record keys per shard role, for map-style access",
            },
        )

    @staticmethod
    def _read_memo(memo: Path) -> tuple[str, ...]:
        """The memoized key list at *memo*.

        Raises:
            ValueError: If the file is not the document this index writes. A
                memo that cannot be read is refused rather than silently
                re-derived, so a corrupted index is a failure and not a
                mysterious slowdown.
        """
        document = json.loads(memo.read_text(encoding="utf-8"))
        keys = document.get("keys") if isinstance(document, dict) else None
        if not isinstance(keys, list):
            raise ValueError(
                f"{memo} is not a shard-key memo: it records no 'keys' list. Delete it "
                "and it will be re-derived from the shard."
            )
        return tuple(str(key) for key in keys)


class SplitDataset:
    """A shard-published dataset, map-style, over every record.

    ``load`` returns this view of the **whole** artifact. A published
    train/val/test assignment is a separate index list, applied with
    :class:`~molhub.dataset.protocol.SubsetDataset`. Passing *split* keeps
    the old filtered view for tests that still construct one; the façade
    never does.

    Args:
        shards: The dataset definition the records come from.
        index: Which keys each shard holds.
        table: Optional published assignment, keyed by record uuid. Needed
            only for :meth:`assignment`.
        split: If set, expose only that assignment's rows. ``None`` (the
            default) exposes every record in shard order.

    Raises:
        ValueError: If *index* was built over a different source than *shards*.
        KeyError: If *split* is set and *table* has no such name.
    """

    def __init__(
        self,
        shards: ShardSource,
        *,
        index: ShardIndex,
        table: _SplitTable | None = None,
        split: str | None = None,
    ) -> None:
        if index.source is not shards:
            raise ValueError(
                "This split view and its shard index were built over different sources; "
                "rows would be counted in one artifact and read from another."
            )
        if split is not None:
            if table is None:
                raise TypeError("a filtered view needs the published assignment table")
            counts = table.counts()
            if split not in counts:
                raise KeyError(
                    f"{split!r} is not a split of this table, which records {sorted(counts)}."
                )
            self._length = counts[split]
        else:
            self._length = sum(len(index.keys(role)) for role in index.roles)
        self._split = split
        self._table = table
        self._index = index
        self._positions_by_role: dict[str, tuple[int, ...]] = {}

    @property
    def split(self) -> str | None:
        """Filtered assignment name, or ``None`` for the whole artifact."""
        return self._split

    @property
    def source_id(self) -> str:
        return self._index.coordinate.canonical

    def assignment(self) -> dict[str, list[int]]:
        """Published name → indices into this whole-artifact view.

        Raises:
            SplitTableUnavailable: If no assignment table was attached.
            TypeError: If this view is already a filtered subset.
        """
        from molhub.loader.errors import SplitTableUnavailable

        if self._split is not None:
            raise TypeError("assignment() is computed on the whole dataset, not a filtered view")
        if self._table is None:
            raise SplitTableUnavailable(
                f"{self._index.coordinate.canonical} has no published assignment on this "
                "machine. Build it with: python -m molhub.scripts.build_class1_splits"
            )
        by_name: dict[str, list[int]] = {name: [] for name in self._table.counts()}
        cursor = 0
        for role in self._index.roles:
            for key in self._index.keys(role):
                by_name[self._split_of(key, role)].append(cursor)
                cursor += 1
        return by_name

    def __repr__(self) -> str:
        if self._split is None:
            return f"SplitDataset({self._index.coordinate.canonical!r}, records={self._length})"
        return (
            f"SplitDataset({self._index.coordinate.canonical!r}, split={self._split!r}, "
            f"records={self._length})"
        )

    def __len__(self) -> int:
        return self._length

    def __getitem__(self, index: int) -> Sequence[Frame]:
        """The record at *index* within this split.

        Args:
            index: A position in ``[0, len(self))``; negative positions count
                back from the end, as elsewhere in Python.

        Returns:
            The ``Sequence[Frame]`` the shard reader builds.

        Raises:
            TypeError: If *index* is not an integer. Deciding it here is what
                keeps ``ds["train"]`` — the mistake a reader coming from a dict
                makes — from surfacing as ``'<' not supported between instances
                of 'str' and 'int'``, which names this class's bounds check
                rather than the caller's mistake.
            IndexError: If *index* is out of range, or if the shards hold fewer
                records of this split than the table counts. The message names
                the dataset, the split, the bound and the index asked for: this
                is the one refusal a user meets by accident, three frames deep
                in a training loop, and all four facts are already in hand.
            UnknownRecordKey: If a shard's key is outside the table's key space.
        """
        try:
            position = operator.index(index)
        except TypeError:
            raise TypeError(
                f"A dataset is addressed by integer position, not by {index!r} "
                f"({type(index).__name__}). This is {self._index.coordinate.canonical}; "
                "its first record is ds[0]."
            ) from None
        asked = position
        position = position + self._length if position < 0 else position
        if position < 0 or position >= self._length:
            where = (
                f"split {self._split!r} of {self._index.coordinate.canonical}"
                if self._split is not None
                else self._index.coordinate.canonical
            )
            raise IndexError(f"{asked} is outside {where}, which holds {self._length} records.")
        remaining = position
        held = 0
        for role in self._index.roles:
            positions = self._positions(role)
            held += len(positions)
            if remaining < len(positions):
                return self._index.shard(role)[positions[remaining]]
            remaining -= len(positions)
        raise IndexError(
            f"The published files hold {held} records of "
            f"{self._index.coordinate.canonical}, but this view counts "
            f"{self._length}."
        )

    def _positions(self, role: str) -> tuple[int, ...]:
        """Where this view's records sit within the shard *role*."""
        remembered = self._positions_by_role.get(role)
        if remembered is None:
            if self._split is None:
                remembered = tuple(range(len(self._index.keys(role))))
            else:
                remembered = tuple(
                    offset
                    for offset, key in enumerate(self._index.keys(role))
                    if self._split_of(key, role) == self._split
                )
            self._positions_by_role[role] = remembered
        return remembered

    def _split_of(self, key: str, role: str) -> str:
        """The assignment name *key* belongs to."""
        if self._table is None:
            raise RuntimeError("assignment lookup needs the published table")
        try:
            return self._table.split_of(key)
        except KeyError as error:
            raise UnknownRecordKey(
                f"Record key {key!r} of {self._index.coordinate.canonical} has no row in "
                "the split table, which is keyed by record uuid. This dataset's declared "
                "key space is the uuid one; the declared alternative is molecular "
                "identity (each record's mapped_isomeric_smiles hashed to an identity, "
                "looked up in identity_splits.csv.gz), and it is selected by declaration, "
                "never discovered at runtime. No split is defaulted: a fabricated one "
                f"leaks between train and test undetected. (shard role {role!r})"
            ) from error
