---
title: Conveyor REMOTE-tier block roster and digest-verified shard transfer
status: approved
grilled: true
slug: streaming-data-tiers-03-conveyor-02-roster
repo: molhub
chain: streaming-data-tiers-03-conveyor
created: 2026-08-14
---

# Conveyor REMOTE-tier block roster and digest-verified shard transfer

> **Repo: molhub** (`/home/jicli594/work/molcrafts/molhub`). Second of the
> four-part `-03-conveyor` chain. Depends on `-01-ledger` for `BlockId`,
> `BlockState` and `Ledger`; those surfaces are consumed exactly as `-01`
> defines them and are not redesigned here.

## Summary

The conveyor cannot schedule anything until it can answer two questions about
the REMOTE tier: *what blocks exist, how big are they, and what must their bytes
hash to* — and *how do those bytes get here without a corrupt shard ever being
mistaken for a good one*. This spec lands both, and nothing else. `BlockRoster`
**projects** the blocks of one collection role out of the registry manifests
molhub already ships (`src/molhub/registry_data/dataset/themol/*/1.yaml`), so
the roster owns no index of its own and cannot drift from the registry;
`ShardTransfer` schedules `Molhub.fetch` through the existing `ArtifactHub`
seam, re-verifies the delivered file against the manifest digest, retries a
bounded number of times on mismatch, and fails with a typed aggregate error
rather than letting a bad block advance. It owns no transport: `Fetcher` and its
drivers are generalized *around*, never edited.

Two findings, named per the Iron law. **(1) Found — L1 concurrency hazard, not
fixed here.** `BlobStore.temp_path` (`src/molhub/sources/blobs.py:69-75`) derives
one fixed `.part` path per cache key, and `Fetcher.fetch` returns a cached file
without any digest check (`src/molhub/sources/fetcher.py:82-84`). Two processes
fetching the same shard therefore interleave writes into one `.part`; whichever
verifies first renames a file the other is still writing into the cache, and
every later reader is served those bytes forever with no check. This spec
neutralizes the race *for conveyor callers* with a ledger lease and by
re-verifying unconditionally, and it deletes bytes that fail verification so the
cache short-circuit cannot fossilize them. **It does not fix L1**; that is routed
to `/mol:fix` (pid/uuid-suffixed temp name) and must not be recorded as handled.
**(2) Found — the REMOTE roster cannot honestly fill `BlockId.split` for an
upstream-published shard**, because the split table keys molecular identities and
scan uuids, not shard roles. This spec refuses to fabricate one; see § Design.

## Design

### Layer position and the one-way edge

`molhub.conveyor` sits above both `molhub.sources` (bytes) and `molhub.dataset`
(semantics): it may import `molhub.manifest`, `molhub.sources` and
`molhub.dataset`, and neither of those may import `molhub.conveyor`.
`tests/test_sources/test_layering.py` already pins the L1 half of that rule
(transport imports no `molhub.dataset`); this spec adds the mirror guard for the
new package. The conveyor is pure Python over stdlib plus molhub's own types —
no `torch`, no `numpy`, no `h5py`. It never opens a shard; it reasons about
files, sizes and digests only.

**Naming.** Per `.claude/notes/notes.md` § *Registry / Source / index*, `index`
carries no domain meaning in molhub — hence `Roster`, and not `Catalog`, which
the same note reserves against `Registry`. The manifest artifact role literally
named `index` is frozen registry data under a versioned schema and is left
exactly as it is; the roster classifies it as hot-tier and excludes it from the
rolling queue (below).

### `RemoteBlock` and `BlockRoster` — projection, not a parallel index

```python
@dataclass(frozen=True)
class RemoteBlock:
    id: BlockId                      # from -01-ledger
    filename: str                    # Artifact.filename, verbatim
    size: int                        # Artifact.size, verbatim
    digest: Digest                   # Artifact.digest, same object
    locators: tuple[Locator, ...]    # Artifact.locators, same object
```

`BlockRoster(manifest: Manifest, role: CollectionRole, *, splits: SplitTable |
None = None)` projects eagerly in `__init__` (loud at construction, as
`Manifest.from_mapping` is) and exposes single-concern readers:
`blocks() -> tuple[RemoteBlock, ...]` in manifest role order,
`block(id: BlockId) -> RemoteBlock` (raises `KeyError` listing available ids,
following `Manifest.artifact`), `total_bytes() -> int`,
`hot_roles: tuple[str, ...]`, `split_provenance: SplitProvenance | None`, and
`role: CollectionRole`.

Binding rules of the projection:

- **Nothing is re-derived.** `filename`, `size`, `digest`, `locators` are the
  `Artifact`'s values; `digest` and `locators` are carried by *identity* (both
  are frozen), so a re-computation would be visible as a new object. `RemoteBlock`
  declares **no** unit, target, sampling-unit or reference-method field —
  those facts belong to the injected `CollectionRole` and are read from it
  (`roster.role.units`, `roster.role.sampling_unit`). Copying them onto every
  block would be exactly the god-struct the house rules forbid, and would create
  a second place for them to be wrong.
- **`BlockId` is molhub's existing addressing, plus task and split.**
  `source = manifest.coordinate.canonical`, `block_id = <artifact role>` — which
  is precisely the `(coordinate, roles=[role])` pair `ArtifactHub.fetch` takes
  and the `<coordinate>/<role>` key `BlobStore` files bytes under. `task =
  role.name`. No new identity is invented anywhere in this chain.
- **Which artifacts become blocks.** Roles matching the registry's shard
  convention `shard-<digits>` (established by
  `scripts/generate_themol_manifests.py`) become blocks; every other role is
  reported through `hot_roles` and never enters the byte-bounded rolling queue —
  the `index` CSV is T-HOT by `-01-strategy` § 6, and a 1.45 GB CSV silently
  admitted to a 40 GB rolling budget is a real accounting error. A manifest that
  yields no shard role raises `NoShardArtifacts` rather than producing an empty
  roster, so a manifest naming its shards differently fails loudly.
- **Refuse what the invariants cannot cover.** `Artifact.size` and
  `Artifact.digest` are each individually optional in the manifest schema. A
  block with no declared size cannot be admitted to a byte-bounded queue (I4);
  a block with no digest cannot satisfy "a mismatching block never reaches
  READY" (I6). The roster therefore raises `UnsizedBlock` / `UnverifiableBlock`
  at construction, which is why `RemoteBlock.size` and `.digest` are
  non-optional types. Verification uses whatever algorithm the platform
  published (HF sha256 here; `Digest.matches` already rejects a cross-algorithm
  comparison).
- **Consistency guard.** `manifest.coordinate.canonical` must appear in
  `role.source_coordinates`, else `RoleSourceMismatch` — this catches pairing
  `dataset:themol/hessian@1` with the `electrostatic` role, which would produce
  a roster that is individually well-formed and wholly wrong.
- The roster takes a `Manifest`, **not** a coordinate and not a `Registry`.
  Resolution is the caller's job; keeping it out means the roster is unit-testable
  from a YAML string with no `$MOLHUB_REGISTRY`, no `$MOLHUB_HOME`, no network.

Real numbers from the shipped manifest, used as the regression goldens:
`dataset:themol/mbis@1` projects **8 blocks**, `hot_roles == ("index",)`,
`total_bytes() == 29_588_617_144` (≈ 29.6 GB). That one role's REMOTE tier is
three quarters of the entire 40 GB T1 rolling budget, and
`dataset:themol/hessian@1` is 50 shards at ≈ 4.8 GB ≈ 239 GB — concrete
confirmation of I4's insistence that queues bound **bytes**, not block count.

### The split a REMOTE roster is not allowed to invent

`BlockId` carries a `split`, and for an upstream-published shard the roster
**cannot fill it and must not fake it**: `class1-universal-splits@1` keys
molecular identity and scan uuid, not shard role, and resolving uuid → shard
means opening the HDF5 bytes the roster deliberately never opens. Every block a
published manifest projects therefore has `id.split is None`, which is the
honest signal that the block is **not split-pure**. I2 / I7 split-purity is a
property of *derived* blocks, produced by the derivation conveyor
(`-01-strategy` § 9); filling `split` is the job of the sub-spec that cuts and
publishes those, on manifests it writes itself.

`SplitTable` therefore enters the roster for the one job it can do without
bytes: binding the projection to a **provenance-verified** split-manifest
version, exposed as `BlockRoster.split_provenance`, so a derived split-pure
block is later traceable to the exact split file sha256 that assigned it.
Anything needing a per-molecule split reads `SplitTable.split_of(uuid)` directly.

### `SplitTable` — the split assignment of record, with its provenance

`SplitTable.from_derived(root: Path, *, source: str)` reads
`$MOLHUB_HOME/derived/molcrafts/class1-universal-splits/1/` — one per-source
file plus `metadata.json` — and verifies each file it reads with
`Digest.of_file(path).matches(...)` against that file's recorded
`output_sha256` in `metadata.json`, raising `SplitProvenanceMismatch` on any
disagreement. The per-source filenames are **not** uniform, so resolution is an
explicit literal mapping (mirroring `scripts/build_class1_splits.py`'s own
`out_name` table), never a glob: `hessian → hessian_uuid_splits.csv.gz`,
`mbis → mbis_uuid_splits.csv.gz`, `torsion-scan → torsion_scan_splits.csv.gz`
(note the last omits `_uuid_`); an unknown source raises `KeyError` naming the
known ones. It exposes `split_of(uuid) -> str`, `counts() -> Mapping[str, int]`,
and `provenance: SplitProvenance` (frozen: coordinate, seed, ratios, generator,
per-file sha256). It loads **one** source's table per instance, not all four,
because the whole set is millions of rows and the caller only ever needs one.

A second alternate constructor, `SplitTable.from_identity(root: Path)`, loads
`identity_splits.csv.gz` (header `identity,split` — molecule identities, no
uuids) under the same provenance verification, exposing the same `split_of`
(keyed by identity) and `counts`. This is the table `-03-prepare`'s
`PrepareJob(split_of=...)` mapping is built from — one implementation, one
provenance check, two key spaces, each honest about which it holds. [Added
2026-08-14 after spec-audit: `-03` needs identity-keyed routing and must not
grow a second split loader.]

Computing a digest here does **not** contradict `.claude/notes/notes.md`
("molhub 绝不自行计算 digest"). That rule forbids inventing a digest for an
*upstream* artifact in order to catalogue it. This is the already-legitimate
other case — checking a completed local artifact against a digest its own
producer recorded — exactly as `Fetcher._fetch_one` does at
`src/molhub/sources/fetcher.py:108`.

### `ShardTransfer` — bounded, leased, re-verified

```python
class ShardTransfer:
    def __init__(self, hub: ArtifactHub, ledger: TransferLedger, *,
                 retries: int = 3, backoff: Backoff | None = None,
                 lease_ttl: float = 3600.0) -> None: ...
    def transfer(self, block: RemoteBlock) -> Path: ...
```

`ArtifactHub` (`src/molhub/dataset/hub.py:22`) is reused verbatim — one verb,
`fetch(coordinate, roles=...)`. `TransferLedger` is a new
`@runtime_checkable Protocol` declared in `transfer.py` naming only the three
verbs a transfer needs (`append`, `lease`, `release`); `-01-ledger`'s `Ledger`
satisfies it by shape and declares nothing, exactly as `Molhub` satisfies
`ArtifactHub`. This is a required-side view of `-01`'s surface, not a redesign
of it, and it is what lets the transfer's unit tests run against a fake ledger
with no `-01` implementation booted. `Backoff` is likewise a one-verb protocol
(`wait(attempt: int) -> None`); the default `ExponentialBackoff` splits the pure
`delay(attempt) -> float` from the sleeping `wait`, so the schedule is testable
without a clock and tests inject a recording fake.

`transfer(block)` performs exactly this sequence, and the sequence is the
contract:

1. `ledger.lease([block.id], ttl=lease_ttl)` — **before** the first fetch (`ttl` is keyword-only per `-01-ledger` §4). This is
   the mitigation for the fixed `.part` hazard: two conveyor processes can no
   longer be inside `BlobStore.temp_path(key)` for the same key at once.
2. `ledger.append(block.id, BlockState.DOWNLOADING)` — **once per call**,
   whatever the attempt count. The ledger is a state log, not a retry log;
   attempts are evidence carried by the error, not rows.
3. Up to `retries` attempts **in total** (`retries=3` means three attempts, not
   one plus three; `retries < 1` raises `ValueError`). Each attempt:
   `hub.fetch(block.id.source, roles=[block.id.block_id])`, then
   `path.stat().st_size == block.size`, then
   `Digest.of_file(path, algorithm=block.digest.algorithm).matches(block.digest)`.
   Size is checked first because a truncated 4 GB file is one `stat` to detect
   and ~20 s to hash; a wrong size always implies a wrong digest, so this is one
   predicate with a fast pre-filter, not two failure modes.
4. On a failed attempt: **unlink the file the hub returned, then back off, then
   re-fetch.** The unlink is load-bearing, not tidiness — `Fetcher.fetch` returns
   a cached file without re-verifying it (`fetcher.py:82-84`), so leaving bad
   bytes in the cache would make every "retry" return the identical bad bytes
   and the bounded retry would be theatre.
5. On success: return the verified `Path`. The block stays **DOWNLOADING**.
   READY is conjunctive by `-01-strategy` § 3 — downloaded *and* unpacked *and*
   prepared *and* verified — and this spec does none of the middle two. **No code
   in this spec ever writes `BlockState.READY`**, which is how I6 is satisfied
   structurally rather than by vigilance.
6. On exhausting `retries`: raise `PersistentDigestMismatch` carrying every
   attempt (index, locator/path, expected and actual digest or size, waited
   seconds) in the aggregate style of `AllLocatorsFailed`
   (`src/molhub/sources/errors.py:55`) — after having unlinked the bad bytes and
   then appended `BlockState.REMOTE`. **That order is the whole justification for
   the regression:** REMOTE means "nothing local", so regressing to it is only
   honest once the garbage is gone. Delete-then-append is one ordered pair and is
   pinned by test.
7. `finally: ledger.release(...)` — on success and on failure alike.

`PersistentDigestMismatch` deliberately does **not** subclass
`molhub.sources.DigestMismatch`: that type means "upstream changed, update the
manifest, stop using this mirror", and code catching it must not silently
swallow "the same artifact failed verification three times in a row". The
incident this bounds is real — `themol/mbis` shard-003 served corrupt bytes once
with a correct manifest — which is precisely the case `Fetcher`'s no-retry
semantics are wrong for and the reason retry lives here rather than there.

> **Carried verbatim, and not to be mistaken for handled.** `BlobStore.temp_path`
> (`sources/blobs.py:69-75`) derives ONE fixed `.part` path per key — a real
> multi-process correctness hazard in L1; this spec neutralizes it by lease at
> the conveyor layer but does **NOT** fix L1; the underlying gap is routed
> separately to `/mol:fix` (pid/uuid-suffixed temp name) and must not be
> mistaken for handled.

`Fetcher` (`sources/fetcher.py`) is generalized **around**, not inside: its
no-retry upstream-changed semantics stay untouched and the file is not edited.
Lease renewal for transfers longer than `lease_ttl`, parallel transfers, queue
backpressure and byte-budget enforcement are the next sub-specs'; this one moves
one shard at a time, correctly.

### Reuse decision

No `librarian_report` was supplied with this task (cross-repo invocation), so
these verdicts come from direct inspection of the paths cited; a blueprint
refresh before `-03` is advisable.

- `ArtifactHub` (`src/molhub/dataset/hub.py:22`) — **reuse**. The transfer's
  only transport dependency; it owns no driver, no URL, no HTTP.
- `Molhub.fetch` (`src/molhub/molhub.py:70`) — **reuse** through the protocol,
  never by name, so a fake hub needs no registry.
- `Digest.of_file` / `Digest.matches` (`src/molhub/sources/digest.py:86`, `:102`)
  — **reuse** for both the transfer re-verification and the split provenance
  check. No new hashing code.
- `Fetcher` (`src/molhub/sources/fetcher.py:30`) — **reuse unchanged**,
  generalized around. Its file is not edited by this spec.
- `BlobStore` (`src/molhub/sources/blobs.py:29`) — **reuse** indirectly; its
  fixed-`.part` gap is mitigated by lease and routed out, not fixed here.
- `AllLocatorsFailed` (`src/molhub/sources/errors.py:55`) — **pattern**. The
  aggregate-error shape (every attempt in one traceback) is copied, not the type.
- `DigestMismatch` (`src/molhub/sources/errors.py:47`) — **pattern**, explicitly
  not a base class; see above.
- `Manifest` / `Artifact` (`src/molhub/manifest.py:194`, `:75`) — **reuse** as
  the one and only remote block index. No parallel index file is created.
- `CollectionRole` (`src/molhub/dataset/universal_class_i.py:23`) — **reuse** for
  task name, sampling unit and units; the roster reads them, never copies them.
- `Coordinate` (`src/molhub/coordinate.py`) — **reuse** for `BlockId.source`.
- `BlockId` / `BlockState` / `Ledger` (`-01-ledger`) — **reuse** exactly as `-01`
  defines them; the `TransferLedger` protocol is a narrow required-side view,
  not a second ledger.
- `scripts/build_class1_splits.py` outputs — **reuse** as data (its
  `metadata.json` `output_sha256` block is what the provenance check verifies);
  the script is not imported — it is a script, and nothing in-tree reads its
  outputs yet, so `SplitTable` is genuinely **new**.
- `Registry` / `RegistrySource` — **new — not adopted** here. Coordinate
  resolution stays the caller's, so the roster is exercisable from a YAML string.
- Closest pattern: `src/molhub/dataset/hub.py` + `src/molhub/manifest.py` —
  `@runtime_checkable` one-verb Protocols for injected collaborators, frozen
  dataclasses, `from_*` alternate constructors, typed errors whose messages say
  what to do next, module docstrings that argue the boundary. New modules read
  the same way.

## Files to create or modify

> Paths relative to `/home/jicli594/work/molcrafts/molhub`.

- `src/molhub/conveyor/roster.py` (new) — `RemoteBlock`, `BlockRoster`,
  `RosterError` + `NoShardArtifacts` / `UnsizedBlock` / `UnverifiableBlock` /
  `RoleSourceMismatch`
- `src/molhub/conveyor/splits.py` (new) — `SplitTable`, `SplitProvenance`,
  `SplitProvenanceMismatch`
- `src/molhub/conveyor/transfer.py` (new) — `TransferLedger`, `Backoff`,
  `ExponentialBackoff`, `ShardTransfer`, `TransferError` +
  `PersistentDigestMismatch`
- `src/molhub/conveyor/__init__.py` — created by `-01-ledger`; this spec appends
  the roster / splits / transfer exports (new if `-01` has not landed it)
- `tests/test_conveyor/__init__.py` — same dependency on `-01`
- `tests/test_conveyor/conftest.py` (new) — the two-shard fixture manifest, fake
  `ArtifactHub`, fake `TransferLedger`, recording `Backoff`
- `tests/test_conveyor/test_roster.py` (new)
- `tests/test_conveyor/test_splits.py` (new)
- `tests/test_conveyor/test_transfer.py` (new)
- `tests/test_conveyor/test_layering.py` (new)
- `regressions/streaming-data-tiers-03-conveyor-02-roster.py` (new)

## Tasks

- [ ] Write failing unit tests for `SplitTable` in `tests/test_conveyor/test_splits.py` (`TestSplitTable`): gz row parsing, `split_of`, `counts`, provenance fields, the explicit per-source filename mapping (incl. the `torsion-scan` irregular name and `KeyError` on an unknown source), `from_identity` over `identity_splits.csv.gz`, and `SplitProvenanceMismatch` on a tampered `.csv.gz` (RED)
- [ ] Implement `SplitTable` (`from_derived` + `from_identity`), `SplitProvenance` and `SplitProvenanceMismatch` in `src/molhub/conveyor/splits.py`, verifying each file against `metadata.json` `output_sha256` with `Digest.of_file(...).matches(...)`
- [ ] Write failing unit tests for the roster in `tests/test_conveyor/test_roster.py` (`TestRemoteBlock`, `TestBlockRoster`) over the two-shard fixture manifest added to `tests/test_conveyor/conftest.py`: field-identity carry, `hot_roles`, `total_bytes`, `block(id)`, `split is None`, and each typed guard (RED)
- [ ] Implement `RemoteBlock`, `BlockRoster` and the guards `NoShardArtifacts` / `UnsizedBlock` / `UnverifiableBlock` / `RoleSourceMismatch` in `src/molhub/conveyor/roster.py`
- [ ] Write failing unit tests for `ShardTransfer` in `tests/test_conveyor/test_transfer.py` (`TestShardTransfer`, `TestExponentialBackoff`) against a fake `ArtifactHub` and fake `TransferLedger`: lease-before-fetch, release-in-finally, transient retry with unlink, one `DOWNLOADING` append per call, never `READY`, delete-then-`REMOTE` on persistent failure, `retries` counted as total attempts (RED)
- [ ] Implement `TransferLedger`, `Backoff`, `ExponentialBackoff`, `ShardTransfer` and `PersistentDigestMismatch` in `src/molhub/conveyor/transfer.py`
- [ ] Add `tests/test_conveyor/test_layering.py` pinning the one-way edge (no `molhub.sources` or `molhub.dataset` module imports `molhub.conveyor`; `src/molhub/conveyor/**` imports only stdlib and `molhub.*`, never `torch` / `numpy` / `h5py`) and export the new surface from `src/molhub/conveyor/__init__.py` alongside `-01-ledger`'s, adding `tests/test_conveyor/__init__.py`
- [ ] Add regression example `regressions/streaming-data-tiers-03-conveyor-02-roster.py` (public API only; hard-coded goldens, no third-party runtime)
- [ ] Run full check + test suite (`uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, `uv run pytest -v`) and confirm `git diff --stat` reports no change under `src/molhub/sources/`

## Testing strategy

Unit tests only under `tests/`, path-mirroring `src/molhub/conveyor/`, types
mirrored (`BlockRoster` → `TestBlockRoster`), one method per test, fakes for
every outbound dependency, no network (the default `addopts = "-m 'not network'"`
already excludes the marked suite; nothing here is marked).

`tests/test_conveyor/test_splits.py` → `TestSplitTable`
- happy path: a three-row `.csv.gz` plus a matching `metadata.json` yields the
  expected `split_of` values and `counts()`.
- provenance: a `.csv.gz` whose bytes no longer match the recorded
  `output_sha256` raises `SplitProvenanceMismatch` naming the file.
- provenance fields: `coordinate`, `seed`, `ratios`, `generator` are surfaced
  from `metadata.json` verbatim.
- edge: unknown uuid → `KeyError` listing nothing rather than a silent default;
  a missing `metadata.json` → typed error, never an unverified load.

`tests/test_conveyor/test_roster.py` → `TestRemoteBlock`, `TestBlockRoster`
- each `RemoteBlock` field equals its `Artifact` field; `digest` and `locators`
  are the *same objects* (proof of no re-derivation).
- `RemoteBlock` exposes no unit / target / sampling-unit attribute.
- `blocks()` is manifest role order; `block(id)` round-trips; unknown id raises
  `KeyError` listing the available ids.
- `hot_roles == ("index",)` on the fixture; `total_bytes()` sums shards only.
- `BlockId` composition: `source == manifest.coordinate.canonical`,
  `task == role.name`, `block_id == <artifact role>`, `split is None`.
- guards: artifact with `size=None` → `UnsizedBlock`; `digest=None` →
  `UnverifiableBlock`; manifest with no `shard-<n>` role → `NoShardArtifacts`;
  role not declaring this coordinate → `RoleSourceMismatch`.
- `split_provenance` is `None` without a `SplitTable` and is the table's
  provenance with one.

`tests/test_conveyor/test_transfer.py` → `TestShardTransfer`, `TestExponentialBackoff`
- happy path: one attempt, returns the hub's path, `hub` called with exactly
  `(block.id.source, roles=[block.id.block_id])`.
- lease: `lease` is recorded before the first `fetch` call; `release` runs on
  success **and** after a raised `PersistentDigestMismatch` (both asserted from
  the fake ledger's call log).
- transient: corrupt-then-good fake → returns the good path, exactly two
  `fetch` calls, exactly one `DOWNLOADING` append, the corrupt file unlinked
  before the second fetch, one recorded backoff wait.
- persistent: always-corrupt fake → `PersistentDigestMismatch` with three
  recorded attempts, file absent afterwards, ledger rows exactly
  `[DOWNLOADING, REMOTE]` in that order.
- never READY: no call in any scenario appends `BlockState.READY`.
- size pre-filter: a right-digest-impossible truncated file fails on size and is
  retried, and the recorded attempt names `size` as the reason.
- bounds: `retries=1` performs one attempt; `retries=0` raises `ValueError`.
- `TestExponentialBackoff` targets the pure `delay(attempt)` schedule only —
  no test sleeps.

`tests/test_conveyor/test_layering.py` — AST-level structural guards in the
style of `tests/test_sources/test_layering.py`: no module under
`src/molhub/sources/` or `src/molhub/dataset/` imports `molhub.conveyor`; no
module under `src/molhub/conveyor/` imports anything outside stdlib and
`molhub.*`; `torch`, `numpy` and `h5py` appear in no conveyor import; a
never-called static proof that `-01`'s `Ledger` and molhub's `Molhub` fit the
`TransferLedger` and `ArtifactHub` seams (checked by `ty`, mirroring
`tests/test_dataset/test_hub.py:16`).

**Regression example** — `regressions/streaming-data-tiers-03-conveyor-02-roster.py`,
public API only, offline, stdlib only, three scenarios with hard-coded goldens:

1. *Projection.* Parse the shipped
   `src/molhub/registry_data/dataset/themol/mbis/1.yaml` with
   `Manifest.from_path` (direct path, so no `$MOLHUB_REGISTRY` dependence), take
   the `electrostatic` role from `Class1Universal2026().load()`, and assert
   literals: `8` blocks, `hot_roles == ("index",)`,
   `total_bytes() == 29_588_617_144`, `blocks()[0].filename == "mbis_0.h5"`,
   the `shard-003` block's `size == 3_549_593_228` and digest hex
   `b364c682c2d871951c80db3d0c5daac5aebfe6cc09596e29ed0a64e4d0adc557`
   (the shard from the corruption incident), and `id.split is None` for all
   eight. These goldens are transcribed from the manifest, which is generated
   and marked "do not edit by hand"; regenerating it requires updating them in
   the same commit.
2. *Transient mismatch then success.* An inline two-shard fixture manifest in a
   `tmp` dir, a fake hub serving corrupt bytes on call 1 and the good payload on
   call 2, a recording ledger and a no-sleep backoff. Assert: the returned path
   holds the good bytes, two fetch calls, ledger rows `[DOWNLOADING]`, one lease
   and one release. The expected sha256 of the good payload is embedded in the
   fixture manifest as a **literal** with a comment naming the command
   (`python -c "import hashlib; ..."`) and date, so the script never computes its
   own expectation.
3. *Persistent mismatch.* Same fixture, always-corrupt hub, `retries=3`. Assert
   `PersistentDigestMismatch` with three recorded attempts, the cache path
   absent, ledger rows `[DOWNLOADING, REMOTE]` in that order, and the lease
   released.

No third-party oracle runs at any point; `hashlib`, `gzip`, `csv` and `json` are
stdlib.

## Out of scope

- **Fixing `BlobStore.temp_path`'s fixed `.part` name** — routed to `/mol:fix`
  (pid/uuid-suffixed temp path in `src/molhub/sources/blobs.py`). The lease here
  serializes conveyor callers only; a non-conveyor caller still races.
- **Any edit to `src/molhub/sources/`** — `Fetcher`'s no-retry
  upstream-changed semantics, the driver table, and the transport contract are
  unchanged; the diff-clean check is an acceptance criterion.
- **Unpack / prepare / `READY`** — the conjunctive READY transition, unpacking,
  conversion and per-block preprocessing belong to the next sub-spec. Nothing
  here writes `BlockState.READY`.
- **Queue backpressure, byte budgets, deletion and refcounting (I3, I4, I9,
  I10)** — later `-03-conveyor` sub-specs. This one transfers a single shard.
- **Parallel or resumable transfers, range requests, lease renewal, multi-node
  lease visibility** — deferred; `lease_ttl` is a documented parameter, not a
  renewal mechanism.
- **Cutting split-pure derived blocks and filling `BlockId.split`** — the
  derivation conveyor's, on manifests it publishes itself.
- **`BlockId` / `BlockState` / `Ledger` design** — owned by `-01-ledger` and
  consumed as given.
- **Opening shard bytes** — no HDF5, no CSV row parsing of THEMol indexes, no
  molecule-level anything. The roster reasons about files, not molecules.
- **Registering a new coordinate or editing registry manifests** — the roster
  projects what the registry already says.
