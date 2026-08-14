"""Shared fixtures for the conveyor tests — two shards, three fakes, no network.

Nothing here imports the modules under construction (``roster``, ``splits``,
``transfer``): a conftest that imports them would turn every test in this
package, including the landed ledger suite, into a collection error the moment
one of them is missing. The fakes therefore speak only ``BlockId`` /
``BlockState`` and plain paths.

Two facts are computed here with :mod:`hashlib` rather than copied from
upstream: the fixture manifest's digests and the split fixture's
``output_sha256`` block. Both are digests of bytes *this file authored*, which
is the case the repo rule ("molhub never computes a digest of its own") has
always allowed — the rule is about cataloguing an upstream artifact.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from molhub.conveyor.block import BlockId, BlockState
from molhub.coordinate import Coordinate
from molhub.dataset.universal_class_i import Class1Universal2026, CollectionRole
from molhub.manifest import Manifest

# ---------------------------------------------------------------------------
# The fixture manifest: one hot index and two shards of a real coordinate.
# ---------------------------------------------------------------------------

COORDINATE = "dataset:themol/mbis@1"
ROLE_NAME = "electrostatic"
COMMIT = "e029fa677b2638b29efa5930a1173d4e41abcab8"

INDEX_BODY = b"uuid,mapped_isomeric_smiles\n"
SHARD_0_BODY = b"themol mbis shard 000 payload bytes"
SHARD_1_BODY = b"themol mbis shard 001 payload bytes, one line longer"

# Right size, wrong bytes — the shape of the mbis shard-003 incident, and the
# only way to prove the digest check is doing work the size check cannot.
CORRUPT_BODY = b"?" * len(SHARD_0_BODY)
# Wrong size — must be rejected by the `stat` pre-filter before anything hashes.
TRUNCATED_BODY = SHARD_0_BODY[:-7]

INDEX_SIZE = len(INDEX_BODY)
SHARD_0_SIZE = len(SHARD_0_BODY)
SHARD_1_SIZE = len(SHARD_1_BODY)

INDEX_SHA = hashlib.sha256(INDEX_BODY).hexdigest()
SHARD_0_SHA = hashlib.sha256(SHARD_0_BODY).hexdigest()
SHARD_1_SHA = hashlib.sha256(SHARD_1_BODY).hexdigest()

INDEX_ARTIFACT = f"""\
  - role: index
    filename: mbis_dataset.csv
    format: csv
    digest: "sha256:{INDEX_SHA}"
    size: {INDEX_SIZE}
    locators:
      - hf://ByteDance-Seed/THEMol@{COMMIT}/MBIS/mbis_dataset.csv
"""

SHARD_0_ARTIFACT = f"""\
  - role: shard-000
    filename: mbis_0.h5
    format: hdf5
    digest: "sha256:{SHARD_0_SHA}"
    size: {SHARD_0_SIZE}
    locators:
      - hf://ByteDance-Seed/THEMol@{COMMIT}/MBIS/mbis_0.h5
"""

SHARD_1_ARTIFACT = f"""\
  - role: shard-001
    filename: mbis_1.h5
    format: hdf5
    digest: "sha256:{SHARD_1_SHA}"
    size: {SHARD_1_SIZE}
    locators:
      - hf://ByteDance-Seed/THEMol@{COMMIT}/MBIS/mbis_1.h5
"""

# A digest with no size: legal in the manifest schema, unusable in a
# byte-bounded queue.
UNSIZED_SHARD_ARTIFACT = f"""\
  - role: shard-002
    filename: mbis_2.h5
    format: hdf5
    digest: "sha256:{SHARD_1_SHA}"
    locators:
      - hf://ByteDance-Seed/THEMol@{COMMIT}/MBIS/mbis_2.h5
"""

# A size with no digest: legal in the manifest schema, unverifiable on arrival.
UNVERIFIABLE_SHARD_ARTIFACT = f"""\
  - role: shard-003
    filename: mbis_3.h5
    format: hdf5
    size: {SHARD_1_SIZE}
    locators:
      - hf://ByteDance-Seed/THEMol@{COMMIT}/MBIS/mbis_3.h5
"""

# Deliberately NOT in sorted order, and with the hot role first: `blocks()` is
# specified as manifest role order, and a fixture whose manifest order happens
# to equal its sorted order could not tell the two apart.
DEFAULT_ARTIFACTS = INDEX_ARTIFACT + SHARD_1_ARTIFACT + SHARD_0_ARTIFACT


def manifest_yaml(*, artifacts: str = DEFAULT_ARTIFACTS) -> str:
    """A valid two-shard manifest for ``dataset:themol/mbis@1``.

    Args:
        artifacts: The YAML ``artifacts:`` block, so a guard test can swap in a
            single malformed-for-the-conveyor entry without a second manifest.
    """
    return (
        "# Fixture in the shape scripts/generate_themol_manifests.py emits.\n"
        "schema_version: 1\n"
        "kind: dataset\n"
        "namespace: themol\n"
        "name: mbis\n"
        'version: "1"\n'
        "\n"
        "title: THEMol MBIS atomic electrostatics\n"
        "license: CC-BY-NC-4.0\n"
        "\n"
        "artifacts:\n"
        f"{artifacts}"
    )


@pytest.fixture
def manifest() -> Manifest:
    """The two-shard fixture manifest, parsed."""
    return Manifest.from_yaml(manifest_yaml())


@pytest.fixture
def role() -> CollectionRole:
    """The shipped collection role that declares ``dataset:themol/mbis@1``."""
    return Class1Universal2026().load().role(ROLE_NAME)


@pytest.fixture
def other_role() -> CollectionRole:
    """A shipped role that does **not** declare this manifest's coordinate."""
    return Class1Universal2026().load().role("torsion")


# ---------------------------------------------------------------------------
# The split fixture: a miniature class1-universal-splits derivation.
# ---------------------------------------------------------------------------

SPLIT_COORDINATE = "dataset:molcrafts/class1-universal-splits@1"
SPLIT_SEED = 20260814
SPLIT_RATIOS = "8:1:1 train:val:test, molecule level"
SPLIT_GENERATOR = "scripts/build_class1_splits.py"

IDENTITY_ROWS = (("identity-1", "train"), ("identity-2", "val"), ("identity-3", "test"))

# One row per split in every table, so `counts()` is the same mapping whether it
# is folded from the rows or read from metadata — the test must not accidentally
# pin a choice the spec leaves open.
UUID_ROWS: Mapping[str, tuple[tuple[str, str, str], ...]] = {
    "hessian": (
        ("hess-a", "identity-1", "train"),
        ("hess-b", "identity-2", "val"),
        ("hess-c", "identity-3", "test"),
    ),
    "mbis": (
        ("mbis-a", "identity-1", "train"),
        ("mbis-b", "identity-2", "val"),
        ("mbis-c", "identity-3", "test"),
    ),
    "torsion-scan": (
        ("scan-a", "identity-1", "train"),
        ("scan-b", "identity-2", "val"),
        ("scan-c", "identity-3", "test"),
    ),
}

# The literal table from scripts/build_class1_splits.py's own `out_name` block.
# `torsion-scan` omits `_uuid_`; a glob would paper over exactly that.
SPLIT_FILENAMES: Mapping[str, str] = {
    "hessian": "hessian_uuid_splits.csv.gz",
    "mbis": "mbis_uuid_splits.csv.gz",
    "torsion-scan": "torsion_scan_splits.csv.gz",
}
IDENTITY_FILENAME = "identity_splits.csv.gz"

SPLIT_COUNTS: Mapping[str, int] = {"train": 1, "val": 1, "test": 1}


def _write_rows(path: Path, header: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    """Write one gzipped CSV exactly as ``build_class1_splits.py`` writes it."""
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(header))
        for row in rows:
            writer.writerow(list(row))


def write_derived_splits(root: Path) -> Path:
    """Write a miniature ``class1-universal-splits/1/`` directory under *root*.

    The ``output_sha256`` block is computed here, by the test, exactly as the
    producing script computes it — which is what makes a later tamper of any
    one table detectable.

    Returns:
        The directory holding the four tables and ``metadata.json``.
    """
    root.mkdir(parents=True, exist_ok=True)
    _write_rows(root / IDENTITY_FILENAME, ("identity", "split"), IDENTITY_ROWS)
    for source, filename in SPLIT_FILENAMES.items():
        _write_rows(root / filename, ("uuid", "identity", "split"), UUID_ROWS[source])

    metadata = {
        "coordinate": SPLIT_COORDINATE,
        "seed": SPLIT_SEED,
        "ratios": SPLIT_RATIOS,
        "generator": SPLIT_GENERATOR,
        "identity_counts": dict(SPLIT_COUNTS),
        "per_source_row_counts": {source: dict(SPLIT_COUNTS) for source in SPLIT_FILENAMES},
        "output_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (IDENTITY_FILENAME, *SPLIT_FILENAMES.values())
        },
    }
    (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return root


@pytest.fixture
def splits_root(tmp_path: Path) -> Path:
    """A provenance-consistent split directory, ready to load."""
    return write_derived_splits(tmp_path / "class1-universal-splits" / "1")


# ---------------------------------------------------------------------------
# The three fakes. Every outbound dependency of a transfer, and nothing else.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchCall:
    """One recorded ``ArtifactHub.fetch``.

    Attributes:
        coordinate: The coordinate asked for.
        roles: The roles asked for, in order.
        existed: Whether the cache path already held bytes when the call
            arrived — how a test sees that a bad file was unlinked before the
            re-fetch instead of being silently overwritten.
    """

    coordinate: str
    roles: tuple[str, ...]
    existed: bool


class FakeHub:
    """An ``ArtifactHub`` serving canned bytes on a per-call schedule.

    Bytes land on the path :class:`~molhub.sources.blobs.BlobStore` would use,
    so a caller that unlinks a bad file and re-fetches lands on the same path
    the second time — which is the situation the transfer's retry exists for.

    Args:
        root: Cache root; files appear under ``<root>/files/<cache path>/<role>``.
        schedule: Bytes served on call 1, 2, …; the last entry repeats, so an
            always-corrupt hub is a one-element schedule.
        journal: Shared ordered log, so a test can compare the order of hub
            calls against ledger calls.
    """

    def __init__(
        self,
        root: Path,
        schedule: Sequence[bytes],
        *,
        journal: list[str] | None = None,
    ) -> None:
        self.root = root
        self.schedule = tuple(schedule)
        self.journal: list[str] = journal if journal is not None else []
        self.calls: list[FetchCall] = []

    def path_for(self, coordinate: str, role: str) -> Path:
        """Where this fake files *role* of *coordinate*."""
        return self.root / "files" / Coordinate.parse(coordinate).cache_path() / role

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        """Serve the scheduled bytes for every requested role."""
        requested = tuple(roles) if roles is not None else ()
        body = self.schedule[min(len(self.calls), len(self.schedule) - 1)]
        served: dict[str, Path] = {}
        existed = False
        for name in requested:
            path = self.path_for(coordinate, name)
            existed = existed or path.exists()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            served[name] = path
        self.calls.append(FetchCall(coordinate, requested, existed))
        self.journal.append("fetch")
        return served


@dataclass(frozen=True)
class LeaseCall:
    """One recorded ``lease``.

    ``ttl`` is a :class:`~datetime.timedelta`, as ``-01``'s
    :meth:`molhub.conveyor.ledger.Ledger.lease` types it: the unit of a lease is
    carried by the type instead of a bare number.
    """

    blocks: tuple[BlockId, ...]
    ttl: timedelta


@dataclass(frozen=True)
class AppendCall:
    """One recorded ``append``.

    Attributes:
        block: The block the row is about.
        state: The state recorded.
        watched_exists: Whether the watched file existed at the instant the row
            was written, or ``None`` when nothing is watched. This is how the
            ordered pair "delete the bytes, *then* regress to REMOTE" is
            observable from outside the transfer.
    """

    block: BlockId
    state: BlockState
    watched_exists: bool | None


@dataclass(frozen=True)
class ReleaseCall:
    """One recorded ``release``."""

    blocks: tuple[BlockId, ...]


class FakeLedger:
    """A ``TransferLedger`` that records the three verbs a transfer needs.

    Args:
        journal: Shared ordered log of verb names.
        watch: A file whose presence is snapshotted at every ``append``.
    """

    def __init__(self, *, journal: list[str] | None = None, watch: Path | None = None) -> None:
        self.journal: list[str] = journal if journal is not None else []
        self.watch = watch
        self.leases: list[LeaseCall] = []
        self.appends: list[AppendCall] = []
        self.releases: list[ReleaseCall] = []

    def append(
        self,
        block: BlockId,
        state: BlockState,
        *,
        size_bytes: int | None = None,
        payload: Mapping[str, str] | None = None,
    ) -> None:
        """Record that *block* reached *state*."""
        watched = None if self.watch is None else self.watch.exists()
        self.appends.append(AppendCall(block, state, watched))
        self.journal.append("append")

    def lease(self, blocks: Iterable[BlockId], *, ttl: timedelta) -> None:
        """Record a claim on *blocks*."""
        self.leases.append(LeaseCall(tuple(blocks), ttl))
        self.journal.append("lease")

    def release(self, blocks: Iterable[BlockId]) -> None:
        """Record giving up a claim on *blocks*."""
        self.releases.append(ReleaseCall(tuple(blocks)))
        self.journal.append("release")

    @property
    def states(self) -> tuple[BlockState, ...]:
        """Every state appended, in order — the ledger rows a test asserts on."""
        return tuple(call.state for call in self.appends)


class RecordingBackoff:
    """A ``Backoff`` that records the attempt it was asked to wait for.

    Sleeps nowhere: a test that waits for a real backoff is a test that will be
    skipped as slow within a month.
    """

    def __init__(self, *, journal: list[str] | None = None) -> None:
        self.journal: list[str] = journal if journal is not None else []
        self.waits: list[int] = []

    def wait(self, attempt: int) -> None:
        """Record that the caller backed off after *attempt*."""
        self.waits.append(attempt)
        self.journal.append("wait")


@pytest.fixture
def journal() -> list[str]:
    """One ordered log the hub, the ledger and the backoff all append to."""
    return []


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    """A cache root for the fake hub, empty at the start of every test."""
    return tmp_path / "molhub-home"
