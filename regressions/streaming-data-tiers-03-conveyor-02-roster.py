#!/usr/bin/env python
"""Regression: the REMOTE tier projected from the shipped manifest, and corrupt bytes refused.

Exercises the public surface of ``molhub.conveyor``
(``streaming-data-tiers-03-conveyor-02-roster``) offline, in a temporary
directory this script creates, in the three scenarios the spec names:

1. *Projection.* :class:`~molhub.conveyor.BlockRoster` over the **shipped**
   ``src/molhub/registry_data/dataset/themol/mbis/1.yaml`` — parsed by direct
   path, so no ``$MOLHUB_REGISTRY``, no ``$MOLHUB_HOME`` and no network — paired
   with the ``electrostatic`` role of ``Class1Universal2026().load()``. Eight
   blocks, one hot role, 29.6 GB, and the shard-003 size and digest of the
   corruption incident, all as hard-coded literals; every block's ``id.split``
   is ``None``, because a published shard's split cannot be known without
   opening bytes this layer never opens.
2. *Transient mismatch, then success.* An inline two-shard fixture manifest, a
   hub serving right-sized wrong bytes on call 1 and the good payload on call 2,
   a recording ledger and a backoff that never sleeps.
   :meth:`~molhub.conveyor.ShardTransfer.transfer` returns the good bytes after
   exactly two fetches, the corrupt file is gone before the second one, and the
   ledger carries one ``DOWNLOADING`` row for the whole call — the ledger is a
   state log, not a retry log.
3. *Persistent mismatch.* The same fixture, an always-corrupt hub and
   ``retries=3``: :class:`~molhub.conveyor.PersistentDigestMismatch` carrying
   three attempts, no file left behind, ledger rows ``[DOWNLOADING, REMOTE]`` in
   that order with the delete strictly before the ``REMOTE`` row, and the lease
   released on the failure path as well as the success one.

Determinism comes from the seams the package exposes for exactly this: a hub
whose bytes are a fixed schedule, a ledger that only records, and a backoff that
records instead of sleeping. Nothing here opens a socket, reads an environment
variable, consults a clock, or runs a third-party oracle; every expected value
below is a literal, so a change to the projection or the retry sequence is a
loud diff rather than a silent fork.

Provenance of the goldens (no external oracle at any point):

* Scenario 1's literals are transcribed from
  ``src/molhub/registry_data/dataset/themol/mbis/1.yaml``, which
  ``scripts/generate_themol_manifests.py`` generates from the official
  ByteDance-Seed/THEMol ``sha256_ref.csv`` at HuggingFace commit
  ``e029fa677b2638b29efa5930a1173d4e41abcab8``. That file is marked "do not edit
  shard entries by hand"; regenerating it means updating these literals in the
  same commit.
* Scenarios 2-3's fixture digests were taken once, offline, with stdlib
  ``hashlib`` over byte literals authored in this file — the case the repo rule
  ("molhub never computes a digest itself") has always allowed, since it
  catalogues nothing upstream. They are embedded below as literals so this
  script never computes its own expectation.
  command: ``python -c "import hashlib; print(hashlib.sha256(PAYLOAD).hexdigest())"``
  with ``PAYLOAD`` each of the three byte literals below, verbatim; CPython
  3.14.5, stdlib only; 2026-08-14.

tool: python
command: python regressions/streaming-data-tiers-03-conveyor-02-roster.py
date: 2026-08-14
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from molhub import Coordinate, Manifest  # noqa: E402
from molhub.conveyor import (  # noqa: E402
    Backoff,
    BlockId,
    BlockRoster,
    BlockState,
    PersistentDigestMismatch,
    ShardTransfer,
    TransferLedger,
)
from molhub.dataset.universal_class_i import Class1Universal2026  # noqa: E402

# ---------------------------------------------------------------------------
# Scenario 1 goldens — transcribed from the shipped manifest
# ---------------------------------------------------------------------------

_MBIS_MANIFEST = ROOT / "src/molhub/registry_data/dataset/themol/mbis/1.yaml"

_COORDINATE = "dataset:themol/mbis@1"
_ROLE_NAME = "electrostatic"

_BLOCK_ROLES = (
    "shard-000",
    "shard-001",
    "shard-002",
    "shard-003",
    "shard-004",
    "shard-005",
    "shard-006",
    "shard-007",
)
_BLOCK_COUNT = 8
_FIRST_FILENAME = "mbis_0.h5"

#: The 1.45 GB index CSV: fetched like everything else, but T-HOT, so it is
#: reported rather than admitted to a byte-bounded rolling queue.
_HOT_ROLES = ("index",)

#: ~29.6 GB — three quarters of the whole 40 GB T1 rolling budget for one role.
_TOTAL_BYTES = 29_588_617_144

#: The shard from the corruption incident that put a bounded retry in this layer.
_INCIDENT_ROLE = "shard-003"
_INCIDENT_SIZE = 3_549_593_228
_INCIDENT_SHA = "b364c682c2d871951c80db3d0c5daac5aebfe6cc09596e29ed0a64e4d0adc557"

# ---------------------------------------------------------------------------
# Scenarios 2-3 fixture — two shards and one hot role, digests as literals
# ---------------------------------------------------------------------------

_GOOD_PAYLOAD = b"themol mbis shard-000 payload, regression fixture\n"
_GOOD_SIZE = 50
_GOOD_SHA = "c818bac70a249d887ab37bfa0d6705bf8e0343dc3dd7a1d8bfa08fbab2a8a672"

_SECOND_PAYLOAD = b"themol mbis shard-001 payload, regression fixture, one line longer\n"
_SECOND_SIZE = 67
_SECOND_SHA = "15683bc104d5a70a8eb885809bdf71bfbacfedbc6443a75df24355e4c2412f45"

#: Right size, wrong bytes — the shape of the shard-003 incident, and the only
#: payload that proves the digest check does work the ``stat`` pre-filter cannot.
#: Its digest is a literal too, so the failure report is pinned rather than
#: compared against something this script hashed for itself.
_CORRUPT_PAYLOAD = b"?" * _GOOD_SIZE
_CORRUPT_SHA = "a990beb5ec61d1217929aaf748b1e7df2bce5f04240b4ccba6f28480ac4bfcac"

_FIXTURE_ROLE = "shard-000"
_FIXTURE_BLOCK = BlockId(_COORDINATE, _ROLE_NAME, None, _FIXTURE_ROLE)

_COMMIT = "e029fa677b2638b29efa5930a1173d4e41abcab8"

#: A timedelta, not a bare number: the unit of a lease is carried by its type.
_LEASE_TTL = timedelta(seconds=1800)
_RETRIES = 3

#: The ordered verb log each retry scenario must produce, exactly.
_TRANSIENT_JOURNAL = ["lease", "append", "fetch", "wait", "fetch", "release"]
_PERSISTENT_JOURNAL = [
    "lease",
    "append",
    "fetch",
    "wait",
    "fetch",
    "wait",
    "fetch",
    "append",
    "release",
]

_FIXTURE_MANIFEST = f"""\
# Fixture in the shape scripts/generate_themol_manifests.py emits. The two shard
# digests are literals; see this module's docstring for how they were taken.
schema_version: 1
kind: dataset
namespace: themol
name: mbis
version: "1"

title: THEMol MBIS atomic electrostatics
license: CC-BY-NC-4.0

artifacts:
  # Hot tier, and deliberately first: `blocks()` is manifest role order, which a
  # fixture whose shards came first could not tell from sorted order. It carries
  # a size and no digest — legal in the schema, and never inspected here, since
  # the roster reports a hot role instead of projecting it.
  - role: index
    filename: mbis_dataset.csv
    format: csv
    size: 1453041470
    locators:
      - hf://ByteDance-Seed/THEMol@{_COMMIT}/MBIS/mbis_dataset.csv

  - role: shard-000
    filename: mbis_0.h5
    format: hdf5
    digest: "sha256:{_GOOD_SHA}"
    size: {_GOOD_SIZE}
    locators:
      - hf://ByteDance-Seed/THEMol@{_COMMIT}/MBIS/mbis_0.h5

  - role: shard-001
    filename: mbis_1.h5
    format: hdf5
    digest: "sha256:{_SECOND_SHA}"
    size: {_SECOND_SIZE}
    locators:
      - hf://ByteDance-Seed/THEMol@{_COMMIT}/MBIS/mbis_1.h5
"""


# ---------------------------------------------------------------------------
# The three fakes — every outbound dependency of a transfer, and nothing else
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchCall:
    """One recorded ``ArtifactHub.fetch``.

    Attributes:
        coordinate: The coordinate asked for.
        roles: The roles asked for, in order.
        existed: Whether the cache path already held bytes when the call
            arrived — how this script sees that bad bytes were unlinked before
            the re-fetch rather than silently overwritten.
    """

    coordinate: str
    roles: tuple[str, ...]
    existed: bool


class ScheduledHub:
    """An ``ArtifactHub`` serving canned bytes on a per-call schedule.

    Files land on the path :class:`~molhub.sources.blobs.BlobStore` would use,
    so a caller that deletes bad bytes and re-fetches lands on that same path the
    second time — which is precisely the situation the bounded retry exists for.

    Args:
        root: Cache root; files appear under ``<root>/files/<cache path>/<role>``.
        schedule: Bytes served on call 1, 2, …; the last entry repeats, so an
            always-corrupt hub is a one-element schedule.
        journal: Shared ordered verb log.
    """

    def __init__(self, root: Path, schedule: Sequence[bytes], journal: list[str]) -> None:
        self.root = root
        self.schedule = tuple(schedule)
        self.journal = journal
        self.calls: list[FetchCall] = []

    def path_for(self, coordinate: str, role: str) -> Path:
        """Where this hub files *role* of *coordinate*."""
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
class AppendCall:
    """One recorded ``append``.

    Attributes:
        block: The block the row is about.
        state: The state recorded.
        watched_exists: Whether the watched file existed at the instant the row
            was written. This is how "delete the bytes, *then* regress to
            REMOTE" — one ordered pair, since REMOTE claims nothing is local —
            is observable from outside the transfer.
    """

    block: BlockId
    state: BlockState
    watched_exists: bool


class RecordingLedger:
    """A ``TransferLedger`` that records the three verbs a transfer needs.

    Args:
        journal: Shared ordered verb log.
        watch: A file whose presence is snapshotted at every ``append``.
    """

    def __init__(self, journal: list[str], watch: Path) -> None:
        self.journal = journal
        self.watch = watch
        self.appends: list[AppendCall] = []
        self.leases: list[tuple[tuple[BlockId, ...], timedelta]] = []
        self.releases: list[tuple[BlockId, ...]] = []

    def append(self, block: BlockId, state: BlockState) -> None:
        """Record that *block* reached *state*."""
        self.appends.append(AppendCall(block, state, self.watch.exists()))
        self.journal.append("append")

    def lease(self, blocks: Iterable[BlockId], *, ttl: timedelta) -> None:
        """Record a claim on *blocks*."""
        self.leases.append((tuple(blocks), ttl))
        self.journal.append("lease")

    def release(self, blocks: Iterable[BlockId]) -> None:
        """Record giving up a claim on *blocks*."""
        self.releases.append(tuple(blocks))
        self.journal.append("release")

    @property
    def states(self) -> tuple[BlockState, ...]:
        """Every state appended, in order — the ledger rows asserted on below."""
        return tuple(call.state for call in self.appends)


class RecordingBackoff:
    """A ``Backoff`` that records the attempt it was asked to wait for.

    Sleeps nowhere: a regression that waits out a real exponential ladder is a
    regression nobody runs twice.
    """

    def __init__(self, journal: list[str]) -> None:
        self.journal = journal
        self.waits: list[int] = []

    def wait(self, attempt: int) -> None:
        """Record that the caller backed off after *attempt*."""
        self.waits.append(attempt)
        self.journal.append("wait")


def _fixture_roster(workdir: Path) -> BlockRoster:
    """Write the two-shard fixture manifest under *workdir* and project it."""
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / "1.yaml"
    path.write_text(_FIXTURE_MANIFEST, encoding="utf-8")
    role = Class1Universal2026().load().role(_ROLE_NAME)
    return BlockRoster(Manifest.from_path(path), role)


# ---------------------------------------------------------------------------
# Scenario 1 — projection of the shipped manifest
# ---------------------------------------------------------------------------


def check_projection() -> None:
    """The shipped ``themol/mbis@1`` manifest projects the eight literal blocks."""
    manifest = Manifest.from_path(_MBIS_MANIFEST)
    role = Class1Universal2026().load().role(_ROLE_NAME)
    roster = BlockRoster(manifest, role)

    blocks = roster.blocks()
    assert len(blocks) == _BLOCK_COUNT, f"expected {_BLOCK_COUNT} blocks, got {len(blocks)}"
    assert tuple(block.id.block_id for block in blocks) == _BLOCK_ROLES
    assert blocks[0].filename == _FIRST_FILENAME
    assert roster.hot_roles == _HOT_ROLES, f"hot roles drifted: {roster.hot_roles}"
    assert roster.total_bytes() == _TOTAL_BYTES, f"REMOTE tier is now {roster.total_bytes()} bytes"

    # Ledger addressing, and the split the roster is not allowed to invent: the
    # split tables key molecular identity and scan uuid, not shard role.
    for block in blocks:
        assert block.id.source == _COORDINATE
        assert block.id.task == _ROLE_NAME
        assert block.id.split is None, f"{block.id.block_id} was given a fabricated split"
    assert roster.split_provenance is None, "no split table was injected"

    incident = roster.block(BlockId(_COORDINATE, _ROLE_NAME, None, _INCIDENT_ROLE))
    assert incident.size == _INCIDENT_SIZE, f"{_INCIDENT_ROLE} is now {incident.size} bytes"
    assert incident.digest.algorithm == "sha256"
    assert incident.digest.hexdigest == _INCIDENT_SHA, f"digest drifted: {incident.digest}"

    # Carried by identity, not re-derived: a re-computation would be a new object.
    artifact = manifest.artifact(_INCIDENT_ROLE)
    assert incident.digest is artifact.digest, "the digest was re-derived, not carried"
    assert incident.locators is artifact.locators, "the locators were rebuilt, not carried"

    print(
        f"  Projection: {_BLOCK_COUNT} blocks {_BLOCK_ROLES[0]}..{_BLOCK_ROLES[-1]}, "
        f"hot {_HOT_ROLES}, {_TOTAL_BYTES} bytes total, split=None for all; "
        f"{_INCIDENT_ROLE} {_INCIDENT_SIZE} bytes sha256 {_INCIDENT_SHA}"
    )


# ---------------------------------------------------------------------------
# Scenario 2 — corrupt bytes once, then the payload the manifest declares
# ---------------------------------------------------------------------------


def check_transient(workdir: Path) -> None:
    """Right-sized wrong bytes on call 1; the good payload, verified, on call 2."""
    roster = _fixture_roster(workdir)
    block = roster.block(_FIXTURE_BLOCK)
    assert block.size == _GOOD_SIZE
    assert block.digest.hexdigest == _GOOD_SHA

    journal: list[str] = []
    hub = ScheduledHub(workdir / "home", [_CORRUPT_PAYLOAD, _GOOD_PAYLOAD], journal)
    ledger = RecordingLedger(journal, watch=hub.path_for(_COORDINATE, _FIXTURE_ROLE))
    backoff = RecordingBackoff(journal)
    assert isinstance(ledger, TransferLedger), "the recording ledger drifted from the seam"
    assert isinstance(backoff, Backoff), "the recording backoff drifted from the seam"

    transfer = ShardTransfer(hub, ledger, retries=_RETRIES, backoff=backoff, lease_ttl=_LEASE_TTL)
    path = transfer.transfer(block)

    assert path.read_bytes() == _GOOD_PAYLOAD, "the corrupt bytes were returned as good"
    assert len(hub.calls) == 2, f"expected 2 fetches, got {len(hub.calls)}"
    assert [call.roles for call in hub.calls] == [(_FIXTURE_ROLE,), (_FIXTURE_ROLE,)]
    assert [call.coordinate for call in hub.calls] == [_COORDINATE, _COORDINATE]
    # The cache short-circuit would re-serve the identical bad bytes, so the
    # unlink between attempts is what makes the retry more than theatre.
    assert hub.calls[1].existed is False, "the corrupt file survived into the second fetch"

    # One DOWNLOADING row for the whole call: the ledger is a state log, not a
    # retry log, and the attempts are evidence the error would have carried.
    assert ledger.states == (BlockState.DOWNLOADING,), f"ledger rows drifted: {ledger.states}"
    assert ledger.appends[0].block == block.id
    assert BlockState.READY not in ledger.states, "this layer must never write READY"

    assert len(ledger.leases) == 1 and ledger.leases[0] == ((block.id,), _LEASE_TTL)
    assert ledger.releases == [(block.id,)], f"release drifted: {ledger.releases}"
    assert backoff.waits == [1], f"backoff drifted: {backoff.waits}"
    assert journal == _TRANSIENT_JOURNAL, f"call order drifted: {journal}"

    print(
        f"  Transient: {len(hub.calls)} fetches (corrupt then good, {len(_GOOD_PAYLOAD)} bytes "
        f"sha256 {_GOOD_SHA}), corrupt file gone before the re-fetch, "
        f"rows {[state.name for state in ledger.states]}, "
        f"1 lease ttl {int(_LEASE_TTL.total_seconds())}s + 1 release, order {journal}"
    )


# ---------------------------------------------------------------------------
# Scenario 3 — corrupt every time: typed, bounded, and nothing left behind
# ---------------------------------------------------------------------------


def check_persistent(workdir: Path) -> None:
    """Three corrupt deliveries: typed failure, no bytes kept, REMOTE recorded last."""
    roster = _fixture_roster(workdir)
    block = roster.block(_FIXTURE_BLOCK)

    journal: list[str] = []
    hub = ScheduledHub(workdir / "home", [_CORRUPT_PAYLOAD], journal)
    cached = hub.path_for(_COORDINATE, _FIXTURE_ROLE)
    ledger = RecordingLedger(journal, watch=cached)
    backoff = RecordingBackoff(journal)

    transfer = ShardTransfer(hub, ledger, retries=_RETRIES, backoff=backoff, lease_ttl=_LEASE_TTL)
    try:
        transfer.transfer(block)
    except PersistentDigestMismatch as error:
        failure = error
    else:  # pragma: no cover - an unverified block advancing is what I6 forbids
        raise AssertionError("three corrupt deliveries must not produce a verified path")

    attempts = failure.attempts
    assert len(attempts) == _RETRIES, f"expected {_RETRIES} attempts, got {attempts}"
    assert [attempt.index for attempt in attempts] == [1, 2, 3]
    # Right size, wrong bytes: only the digest can name this one.
    assert [attempt.reason for attempt in attempts] == ["digest", "digest", "digest"]
    reported = [(attempt.expected, attempt.actual) for attempt in attempts]
    assert reported == [(f"sha256:{_GOOD_SHA}", f"sha256:{_CORRUPT_SHA}")] * _RETRIES, (
        "expected and actual are reported the wrong way round"
    )
    assert block.id.key() in str(failure), f"the failure does not name the block: {failure}"

    assert not cached.exists(), "corrupt bytes were left in the cache"
    assert len(hub.calls) == _RETRIES, f"retries counts total attempts; got {len(hub.calls)}"
    assert backoff.waits == [1, 2], "a wait after the final attempt buys nothing"

    assert ledger.states == (BlockState.DOWNLOADING, BlockState.REMOTE), (
        f"ledger rows drifted: {[state.name for state in ledger.states]}"
    )
    # REMOTE means "nothing local", so regressing to it is only honest once the
    # garbage is gone — the delete strictly precedes the row.
    assert ledger.appends[-1].watched_exists is False, "REMOTE was recorded while bytes remained"
    assert BlockState.READY not in ledger.states, "this layer must never write READY"

    assert len(ledger.leases) == 1 and ledger.leases[0] == ((block.id,), _LEASE_TTL)
    assert ledger.releases == [(block.id,)], "the lease outlived the failed transfer"
    assert journal == _PERSISTENT_JOURNAL, f"call order drifted: {journal}"

    print(
        f"  Persistent: PersistentDigestMismatch after {len(attempts)} attempts "
        f"(reasons {[attempt.reason for attempt in attempts]}), cache path absent, "
        f"rows {[state.name for state in ledger.states]} with the delete first, "
        f"lease released, order {journal}"
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="molhub-conveyor-roster-") as workdir:
        root = Path(workdir)

        check_projection()
        check_transient(root / "transient")
        check_persistent(root / "persistent")

    print("streaming-data-tiers-03-conveyor-02-roster: OK")


if __name__ == "__main__":
    main()
