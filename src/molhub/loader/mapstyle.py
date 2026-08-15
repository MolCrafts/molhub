"""The i-th record of a split, and an honest account of what asking costs.

``ds[i]`` needs to know which shard owns row *i*, and no published artifact says.
Building that answer eagerly would require every shard on local disk — ≈150 GB
for THEMol MBIS, ≈6.5 TB for the whole collection — which is exactly the
residency invariant the streaming tiers exist to keep. So :class:`ShardIndex`
builds the answer **one shard at a time**, from the group keys
``THEMolShardDataset`` already listed, and memoizes it under the same
:class:`~molhub.conveyor.tier.DerivedLayout` every other derived artifact uses.

The consequence is stated rather than hidden: a map-style view fetches the shard
owning the row you ask for, plus every earlier shard it has not indexed yet.
Sequential access pays once per shard; random access to a late row pays for the
walk. That is HuggingFace's own ``load_dataset`` semantic — it downloads — only
charged out loud.

**One key space, declared, never guessed.** A shard's group keys are read as
record uuids, which is the key space ``mbis_uuid_splits.csv.gz`` and its siblings
hold. A key the table has no row for raises :class:`UnknownRecordKey` naming both
that key space and the declared alternative (molecular identity, via
``mapped_isomeric_smiles`` → ``THEMolUnitEncoder.identity`` →
``identity_splits.csv.gz``). There is no runtime fallback: a fabricated split
leaks between train and test with nothing to detect it.

Reference:
    ``.claude/specs/hf-facade-03-builder-info.md`` § Design (D6), ac-004 and
    ac-005, under the 2026-08-15 operator override recorded in
    ``.claude/notes/notes.md`` (``mol:note:topic:hf-style-api``).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from molhub.conveyor.splits import _SplitTable
from molhub.conveyor.tier import DerivedLayout
from molhub.coordinate import Coordinate
from molhub.dataset.protocol import Sample

__all__ = ["UnknownRecordKey", "ShardRecords", "ShardSource", "ShardIndex", "SplitDataset"]

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


@runtime_checkable
class ShardRecords(Protocol):
    """One shard, already open: its record keys and its records."""

    def keys(self) -> tuple[str, ...]:
        """The shard's record keys, positionally aligned with ``self[i]``."""
        ...

    def __getitem__(self, index: int) -> Sample:
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
    """

    def __init__(
        self,
        shards: ShardSource,
        *,
        coordinate: Coordinate,
        roles: Sequence[str],
        layout: DerivedLayout,
    ) -> None:
        self._source = shards
        self._coordinate = coordinate
        self._roles = tuple(roles)
        self._layout = layout
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
    """One split of a shard-published dataset, map-style.

    ``len`` is the split table's own count — no shard bytes at all.
    ``ds[i]`` walks :attr:`ShardIndex.roles` in order, keeping the records this
    split claims, and reads the i-th of them through the index that opened the
    shard.

    Args:
        shards: The dataset definition the records come from. The same object
            *index* was built over: an index of one artifact's shards paired
            with another's would count rows here and read them there.
        split: Which split this view exposes.
        table: The provenance-verified split assignment, keyed by record uuid.
        index: The shard index, which owns *which keys a shard holds* — this
            class owns *which of them are in this split*.

    Raises:
        ValueError: If *index* was built over a different source than *shards*.
        KeyError: If *table* records no row for *split*; the message names the
            splits it does record, which is what discovery would have said.
    """

    def __init__(
        self,
        shards: ShardSource,
        *,
        split: str,
        table: _SplitTable,
        index: ShardIndex,
    ) -> None:
        if index.source is not shards:
            raise ValueError(
                "This split view and its shard index were built over different sources; "
                "rows would be counted in one artifact and read from another."
            )
        counts = table.counts()
        if split not in counts:
            raise KeyError(
                f"{split!r} is not a split of this table, which records {sorted(counts)}."
            )
        self._split = split
        self._table = table
        self._index = index
        self._length = counts[split]
        self._positions_by_role: dict[str, tuple[int, ...]] = {}

    @property
    def split(self) -> str:
        """The split this view exposes."""
        return self._split

    def __repr__(self) -> str:
        """Which dataset, which split, how much of it — and no shard role.

        This is what ``load_dataset(name, split=...)`` hands back, so its repr is
        the first thing a notebook prints and the first thing a traceback
        carries; ``<SplitDataset object at 0x…>`` names none of the three. All
        three are already in hand — the coordinate from the index, the split and
        its count from the table — so echoing this view costs no fetch, which is
        the same promise ``len`` makes.
        """
        return (
            f"SplitDataset({self._index.coordinate.canonical!r}, split={self._split!r}, "
            f"records={self._length})"
        )

    def __len__(self) -> int:
        return self._length

    def __getitem__(self, index: int) -> Sample:
        """The record at *index* within this split.

        Args:
            index: A position in ``[0, len(self))``; negative positions count
                back from the end, as elsewhere in Python.

        Returns:
            The :class:`molpy.Frame` or :class:`molpy.Trajectory` the shard
            reader builds — no wrapper on top of it.

        Raises:
            IndexError: If *index* is out of range, or if the shards hold fewer
                records of this split than the table counts.
            UnknownRecordKey: If a shard's key is outside the table's key space.
        """
        position = index + self._length if index < 0 else index
        if position < 0 or position >= self._length:
            raise IndexError(
                f"{position} is outside the {self._length} records of split {self._split!r}."
            )
        remaining = position
        held = 0
        for role in self._index.roles:
            positions = self._positions(role)
            held += len(positions)
            if remaining < len(positions):
                return self._index.shard(role)[positions[remaining]]
            remaining -= len(positions)
        raise IndexError(
            f"The shards hold {held} records of split {self._split!r}, but the split "
            f"table counts {self._length}. The table and the shards are from different "
            "releases of this dataset."
        )

    def _positions(self, role: str) -> tuple[int, ...]:
        """Where this split's records sit within the shard *role*.

        Kept once per role: a shard holds ≈50 k records, and re-folding the
        table over all of them on every ``ds[i]`` would make a sequential walk
        quadratic in the size of the dataset.
        """
        remembered = self._positions_by_role.get(role)
        if remembered is None:
            remembered = tuple(
                offset
                for offset, key in enumerate(self._index.keys(role))
                if self._split_of(key, role) == self._split
            )
            self._positions_by_role[role] = remembered
        return remembered

    def _split_of(self, key: str, role: str) -> str:
        """The split *key* belongs to, refusing loudly outside the key space."""
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
