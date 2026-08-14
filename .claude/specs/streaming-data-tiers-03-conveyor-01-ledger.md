---
title: Conveyor block identity, four-state machine, and crash-safe ledger
status: approved
slug: streaming-data-tiers-03-conveyor-01-ledger
repo: molhub
chain: streaming-data-tiers
created: 2026-08-14
---

# Conveyor block identity, four-state machine, and crash-safe ledger

> **Repo: molhub** (`/home/jicli594/work/molcrafts/molhub`). First sub-spec of the
> `-03-conveyor` chain (`01-ledger` → `02-roster` → `03-prepare` → `04-residency`).
> Parent strategy: `.claude/specs/streaming-data-tiers-01-strategy.md`, whose
> invariant **I5** this spec discharges and whose **I9** lease primitive it lands.

## Summary

The conveyor cannot download, prepare or delete anything until it can say
*which* block it is talking about and *what has already happened to it* — and
say so across a crash. This sub-spec lands only that foundation as a new
pure-Python package `src/molhub/conveyor/`: a frozen `BlockId` built from the
identity tuple the strategy already fixed (`source`, `task`, `split`,
`block_id`), a closed four-member `BlockState` with a frozen legality map that
makes an impossible history unrepresentable on both the write and the read side,
and a single append-only JSONL `Ledger` that replays into a
`Mapping[BlockId, BlockState]`, discards a torn final line left by a kill
mid-append, and grants TTL leases as ordinary ledger records rather than
filesystem locks. No network, no filesystem layout, no prefetch, no torch: the
successors get a durable, unit-testable memory to build on, and the block
lifecycle acquires exactly one authority instead of one per stage.

## Design

### 1. Why identity and the ledger come first, alone

Every later stage in the chain is a *writer* of block state: `02-roster`
enumerates blocks, `03-prepare` moves them REMOTE→DOWNLOADING→READY,
`04-residency` moves them READY→CONSUMED and deletes. If any of those lands
before the state authority exists, each invents its own encoding of "what state
is this block in", and I5's promise ("true state re-derivable from files present
∧ ledger") degrades into three disagreeing opinions. So this sub-spec ships the
authority and nothing else, and it ships it as a unit that needs no network, no
`$MOLHUB_HOME`, and no sibling module to be exercised — `uv run pytest
tests/test_conveyor/test_ledger.py -v` is the entire loop.

### 2. `BlockState` — four members, one frozen legality map

`BlockState` is a closed `Enum` with exactly four members and string *values*
used only at the file boundary:

```python
class BlockState(Enum):
    REMOTE = "remote"
    DOWNLOADING = "downloading"
    READY = "ready"
    CONSUMED = "consumed"
```

A fifth state is not representable: nothing accepts a `str` state, the sole
`str → BlockState` boundary is `BlockState.parse(text)` (raising
`UnknownBlockState`), and every other public signature in the package types the
enum. Residency ("this READY block is pinned and must not be deleted") is
deliberately **not** a state — encoding it as one would be the fifth state I5
forbids; it is a flag owned by `04-residency` and orthogonal to the lifecycle.

Legality is a module-level frozen mapping (`MappingProxyType` over
`frozenset`s), keyed by *exactly* the four members (asserted by test, so adding
a member without adding its row is a failure, not a silent hole). All sixteen
ordered pairs are decided here:

| from \ to | REMOTE | DOWNLOADING | READY | CONSUMED |
|---|---|---|---|---|
| **REMOTE** | legal (idempotent re-declare) | legal (fetch starts) | **illegal** — bytes cannot appear without a download record; this is the half-ready hole I5 exists to close | **illegal** — consuming what was never local |
| **DOWNLOADING** | legal — failure or digest mismatch; partial dropped, retry from scratch (I6) | legal (idempotent re-attempt / resume) | legal — unpack ∧ prepare ∧ verify all succeeded; READY is conjunctive | **illegal** — never consume unverified bytes |
| **READY** | legal — local copy released *without* being consumed (byte-budget eviction under I4, or crash cleanup of prepared files); the only honest way to reclaim bytes without claiming consumption | **illegal** — a re-fetch restarts from REMOTE, otherwise the prepared files are unaccounted for | legal (idempotent re-verify) | legal (consumed) |
| **CONSUMED** | legal — deleted locally; a later pass re-fetches it (coverage-over-time, strategy § 7) | **illegal** — must re-declare REMOTE first, so each cycle is a clean one | **illegal** | legal (idempotent; several consumers finishing) |

Nine legal, seven illegal. Self-transitions are legal on purpose: I5 requires
every stage to be idempotent, so re-running a stage after a crash must record a
fact, not raise. Two methods, one job each: `may_become(other) -> bool` asks,
`transition_to(other) -> BlockState` enforces and raises `IllegalTransition`
naming both endpoints.

### 3. `BlockId` — the strategy's tuple, no new taxonomy

```python
@dataclass(frozen=True)
class BlockId:
    source: str      # pinned MolHub coordinate, e.g. "dataset:themol/torsion-scan@1"
    task: str        # CollectionRole.name — src/molhub/dataset/universal_class_i.py:23
    split: str       # "train" | "validation" | "test", as published upstream
    block_id: str    # manifest artifact role name, e.g. "shard-003"
```

Field names follow strategy § 10 verbatim (`BlockId.block_id` is mildly
redundant and kept anyway — the four-tuple is quoted in the strategy, the note,
and the successor handoffs, and renaming it here would fork the vocabulary).
None of the four fields invents a taxonomy: `task` is a `CollectionRole.name`,
`block_id` is a manifest artifact `role` (`src/molhub/manifest.py:97`), `split`
is the upstream split label, `source` is a MolHub coordinate.

`source` is validated in `__post_init__` through `Coordinate.parse`
(`src/molhub/coordinate.py:70`), re-raised as `InvalidBlockId` with the parse
error as `__cause__`. `task` / `split` / `block_id` must be non-empty and match
`[A-Za-z0-9._@-]+` — a single path-safe segment — else `InvalidBlockId`.

`key() -> str` returns
`f"{Coordinate.parse(source).cache_path()}/{task}/{split}/{block_id}"`, e.g.
`dataset/themol/torsion-scan@1/torsion/train/shard-003`. It reuses
`Coordinate.cache_path()` (`coordinate.py:137`) precisely because that method
already owns the repo's one rule for turning a coordinate into path segments —
the layout the TypeScript client reads on the same machine. Note what is
**not** reused: `BlobStore._segments` (`sources/blobs.py:54`) sanitises unsafe
characters into `_`, which is lossy and could collapse two distinct blocks onto
one path. Validating at construction is strictly stronger than sanitising at
use, so `key()` needs no sanitiser and can never collide.

### 4. `Ledger` — one append-only JSONL, one record per fact

The ledger is a single file (the caller supplies its path; see § 8), one JSON
object per line, written with a single `write()` of one canonical line
terminated by `\n`, then flushed and `fsync`ed. Two record kinds share the file,
discriminated by the `record` key:

```json
{"record":"transition","source":"dataset:themol/torsion-scan@1","task":"torsion",
 "split":"train","block_id":"shard-003","state":"ready","actor":"1234@node042",
 "at":"2026-08-14T09:15:00+00:00","size_bytes":2000000000,"payload":{},"digest":"…"}
{"record":"lease","source":"…","task":"torsion","split":"train","block_id":"shard-003",
 "holder":"1234@node042","at":"…","expires_at":"…","digest":"…"}
```

Value types are frozen dataclasses: `LedgerRecord` (block fields, `state`,
`actor`, `at`, `size_bytes: int | None`, `payload: Mapping[str, str]`) and
`LeaseRecord` (block fields, `holder`, `at`, `expires_at`). `size_bytes` is
`None`, never `0`, when unknown — `0` is a real byte count and must not double
as a sentinel. `payload` is string→string, diagnostics only: **no code in this
package or its successors may branch on payload content.** That rule is what
keeps `payload` from becoming the ambient context blob `CLAUDE.md § Forbid`
rejects; anything a decision depends on gets a typed field.

Public surface, one named thing per method:

- `Ledger(path, *, clock=None, actor=None)` — no IO at construction.
- `append(block, state, *, size_bytes=None, payload=None) -> LedgerRecord` —
  validates the transition against the current view, stamps `actor` and `at`
  from the seams, repairs a torn tail (§ 6), writes, returns the record.
- `records() -> tuple[LedgerRecord, ...]` — every valid transition, file order.
- `replay() -> Mapping[BlockId, BlockState]` — last state per block. A block the
  ledger has never mentioned is **absent**, not `REMOTE`; callers read absence as
  "not started" themselves rather than having the ledger assert a state it never
  witnessed.
- `lease(blocks, *, ttl) -> tuple[LeaseRecord, ...]`
- `release(blocks) -> frozenset[BlockId]`
- `active_leases(*, now=None) -> Mapping[BlockId, tuple[str, ...]]`

Six methods on one class is near the cohesion limit, so the split trigger is
named now: **a third record kind splits the reader.** Transitions and leases
share one class today because they are the same fact stream about the same
subject and share one crash-repair rule; duplicating that rule across two files
would be the real coupling.

Collaborators enter keyword-only with `None` defaults, mirroring
`DownloadCache(transfer=None → HttpsSource())` (`dataset/cache.py:71`):
`clock` satisfies a `@runtime_checkable Protocol` (`Clock.now() -> datetime`,
default `SystemClock` returning tz-aware UTC), and `actor` defaults to
`f"{os.getpid()}@{socket.gethostname()}"`. Those two seams exist for a concrete
reason, not for symmetry: they are what makes the crash-resume regression
byte-identical (§ 7).

### 5. Per-record digest — and its reconciliation with the never-compute rule

Each line carries `"digest"`: sha256 over the canonical JSON of the record body
with the `digest` key removed (`json.dumps(..., sort_keys=True,
separators=(",", ":"))`, UTF-8), computed through
`molhub.sources.digest.Sha256Stream` and compared with `Digest.matches`, which
is constant-time (`sources/digest.py:102`).

**This is `Sha256Stream`'s first production consumer.** It has had none since it
landed — `grep` finds it only in `sources/__init__.py`, its own module, and its
unit test. Per the Iron law, carrying a public, exported, untouched primitive is
debt, and this spec either uses it or should have deleted it. It uses it, and
the value taken is real: a typed `Digest` and a constant-time compare instead of
a bare hex string and `==`.

**Reconciliation with `CLAUDE.md § What must never change casually`** — "molhub
绝不自行计算 digest". That rule is about *upstream artifacts*: a self-computed
digest of someone else's bytes only proves what one download happened to
contain, and demanding one would force hauling a whole artifact before it could
be catalogued. A ledger record is **molhub's own bytes, authored locally, whole,
in memory, one line at a time**. Its digest makes no provenance claim about
anything upstream; it detects local corruption and torn writes in a file molhub
wrote. The rule is untouched, and nothing here computes a digest over fetched
content — that stays exactly as `sources/` has it.

A hash *chain* (each record digesting its predecessor) was considered and
rejected: it buys tamper-evidence nobody asked for, and it forces every appender
to know the previous digest, which serialises the multi-holder lease writes § 6
depends on. Per-record digests are enough for the stated failure mode.

Record size is capped at 4096 bytes including the newline; over-cap raises
`InvalidRecord`. This is not a POSIX atomicity guarantee — it is a bound that
keeps a concurrent-append interleave from spanning many records and makes the
torn-tail repair singular.

### 6. Crash replay — the torn final line, and the repair truncation

Replay reads the whole file and applies exactly these rules:

1. If the last byte is not `\n`, the trailing fragment is a **torn tail**: the
   process died mid-append. It is discarded silently, and the offset of its start
   is remembered as the last good boundary.
2. Every complete line must parse as JSON, carry a known `record` kind, carry
   all required fields, and match its own digest — otherwise `LedgerCorruption`
   naming `path:line`. A corrupt line that is *not* the unterminated tail is a
   hard failure: it means bit rot or an interleaved writer, and guessing would
   be worse than stopping.
3. Transition records fold into the state map in file order, and each fold is
   re-checked against the legality map. A ledger that records an impossible
   history raises `IllegalTransition` naming the line. The state machine is thus
   enforced on read as well as write — a hand-edited or raced file cannot smuggle
   in a history the writer would have refused.
4. Leases fold by `(block, holder)`, last record wins.

The load-bearing detail is **repair**: the first `append` after a replay that
saw a torn tail truncates the file back to the last good boundary before
writing. Without it, the new record would concatenate onto the fragment and
permanently corrupt a line boundary; with it, a killed process resumes into a
byte-identical file. That is exactly what the regression pins.

Named risk, recorded not waived (Iron law):

> **R1 — one transition writer per ledger; any number of lease holders.**
> `append` replays lazily once and then maintains its view incrementally, so a
> *second* process appending transitions concurrently would be invisible to the
> first and could have an illegal transition accepted or a legal one refused.
> Repair truncation has the same exposure: it removes only bytes after the last
> *valid* record, but a line another process appended between replay and
> truncation would be lost. Lease writes are safe under concurrency — each line
> is self-contained, holders differ, ordering does not matter, and
> `active_leases` / `records` / `replay` always re-read from disk, so cross-process
> lease visibility is correct today. The constraint is therefore: **reads
> re-read; transition writes assume a single writer, and repair happens at
> start-up before other processes attach.** Multi-node visibility and the
> writer-election mechanism are `04-residency`'s, per strategy § 10.

### 7. Leases — TTL records, not `fcntl` locks

I9 needs refcounted, plan-scoped deletion across concurrent consumers. The
obvious mechanism, an advisory `fcntl` lock, is wrong here: the target
filesystem is Lustre, where whole-file locking semantics across clients are a
performance and correctness hazard, and a lock dies with its process without
leaving a trace anyone can audit. A lease is instead a durable, timestamped,
digest-checked line in the same log, so a crashed holder's grip expires on its
own and the whole history is inspectable after the fact.

Grant and expiry use **one** rule: a lease is active for `(block, holder)` iff
the newest lease record for that pair has `expires_at > now` (strict — at
exactly `expires_at` the lease is gone). `release(blocks)` therefore appends a
lease record with `expires_at == at`: releasing *is* shortening the lease to
zero, so expiry and release share a single code path and a single test. Release
of a block this holder does not actively hold appends nothing and is simply
absent from the returned set — idempotent, as I5 requires, and observable
without an exception.

Leases are state-independent: a consumer may lease a block that is still REMOTE,
which is precisely the "next I need H31, T72, R291" pre-registration of strategy
§ 10. That independence is why a lease composes with the state machine instead
of becoming a fifth state.

### 8. What this package deliberately does not decide

The `Ledger` takes an explicit path and reads no environment. Resolving a
"conveyor root" under `$MOLHUB_HOME` would invent a second disk-layout contract
before there is a block store to put in it, and would make the unit untestable
without the environment. `03-prepare` owns the root and hands the ledger its
path. There is likewise no schema-version key in the record: a version field
nothing branches on is decoration, and when the format genuinely changes the
conveyor root changes name.

Vocabulary guard (`.claude/notes/notes.md` § Registry / Source / index): the word
**index** is not used for any domain meaning here, and **Catalog** is
unavailable. The enumeration surface is the successor's `roster`.

### Reuse decision

No `librarian_report` was supplied with this task; verdicts below come from
direct inspection of the named files in the current tree.

- `molhub.coordinate.Coordinate` (`src/molhub/coordinate.py:39`, `.parse:70`,
  `.cache_path:137`) — **reuse**. `BlockId` validates `source` through it and
  builds `key()` from `cache_path()`; no second coordinate parser, no second
  path-segment rule.
- `molhub.sources.digest.Sha256Stream` / `Digest` (`sources/digest.py:114`,
  `:32`) — **reuse**, as the per-record digest path. First production consumer;
  closing that debt is part of this spec's rationale (§ 5).
- `molhub.sources.errors` (`sources/errors.py`) — **pattern**, not import. One
  type per distinguishable failure, base class per package. The *layout*
  deviates deliberately: `sources/` has seven error types raised across six
  driver modules, so a shared `errors.py` earns its keep; `conveyor/` has two
  modules whose errors are inseparable from the type that raises them, so
  `ConveyorError` / `IllegalTransition` / `InvalidBlockId` / `UnknownBlockState`
  live in `block.py` and `InvalidRecord` / `LedgerCorruption` in `ledger.py`,
  keeping each module self-contained.
- `molhub.dataset.hub.ArtifactHub` (`dataset/hub.py:21`) — **pattern** for the
  injected `Clock`: `@runtime_checkable Protocol`, shape not subclassing, one
  verb.
- `molhub.dataset.cache.DownloadCache.__init__` (`dataset/cache.py:71`) —
  **pattern** for keyword-only collaborators with `None` defaults resolved to a
  concrete default inside `__init__`.
- `CollectionRole` (`src/molhub/dataset/universal_class_i.py:23`) — **reuse** as
  the `task` vocabulary; `BlockId.task` is a `CollectionRole.name`, not a new
  label space.
- `Manifest.artifact(role)` / `Artifact.role` (`src/molhub/manifest.py:97`,
  `:286`) — **reuse** as the `block_id` vocabulary (`shard-003`).
- `tests/test_sources/test_layering.py` — **pattern** for the AST-based import
  guard; `tests/test_conveyor/test_layering.py` reads the same way.
- `molhub.sources.blobs.BlobStore` (`sources/blobs.py:29`, `_segments:54`) —
  **new — not adopted**: its key sanitiser is lossy where `BlockId` must be
  injective, and root resolution belongs to `03-prepare` (§ 8). No parallel
  store is designed here.
- `molix` / `torch` / `molpy` / `numpy` — **not used**. This package is stdlib +
  `molhub.*` only, enforced by the layering test.

## Files to create or modify

- `src/molhub/conveyor/__init__.py` (new) — package surface re-export only.
- `src/molhub/conveyor/block.py` (new) — `BlockState`, `BlockId`,
  `ConveyorError`, `IllegalTransition`, `InvalidBlockId`, `UnknownBlockState`.
- `src/molhub/conveyor/ledger.py` (new) — `Clock`, `SystemClock`,
  `LedgerRecord`, `LeaseRecord`, `Ledger`, `InvalidRecord`, `LedgerCorruption`.
- `tests/test_conveyor/__init__.py` (new)
- `tests/test_conveyor/test_block.py` (new)
- `tests/test_conveyor/test_ledger.py` (new)
- `tests/test_conveyor/test_layering.py` (new) — import-purity guard.
- `regressions/streaming-data-tiers-03-conveyor-01-ledger.py` (new)

## Tasks

- [ ] Write failing tests for the four-state machine and block identity in `tests/test_conveyor/test_block.py` (all sixteen ordered state pairs parametrized against the legality table, exactly four enum members, map keys equal to the member set, `BlockState.parse` rejecting an unknown name, `BlockId.key()` pinned to literal strings, `InvalidBlockId` for a bad coordinate and for a segment containing `/`)
- [ ] Implement `BlockState`, `BlockId` and the conveyor error types in `src/molhub/conveyor/block.py`, with the legality map frozen at module level and `key()` derived from `Coordinate.cache_path()`
- [ ] Write failing tests for the ledger in `tests/test_conveyor/test_ledger.py` (append stamping and legality refusal, `records()` order, `replay()` last-state-wins and absence-is-not-REMOTE, torn final line discarded, mid-file corrupt line raising `LedgerCorruption` with `path:line`, flipped byte detected, recorded-illegal-history raising on read, lease grant / strict TTL boundary / release / two holders on one block / idempotent release of an unheld block, `InvalidRecord` for naive timestamp and over-cap payload)
- [ ] Implement `LedgerRecord`, `LeaseRecord`, `Clock` / `SystemClock` and `Ledger` in `src/molhub/conveyor/ledger.py`, digesting every record through `molhub.sources.digest.Sha256Stream` and truncating to the last good boundary before the first append after a torn tail
- [ ] Export the package surface in `src/molhub/conveyor/__init__.py`, add `tests/test_conveyor/__init__.py`, and add the import-purity guard `tests/test_conveyor/test_layering.py` (AST scan: every import in `src/molhub/conveyor/*.py` is stdlib or `molhub.*`; no `torch`, `numpy`, `molpy`, `molrs`, `requests`, `h5py`; no `hashlib` — digests go through `molhub.sources.digest`)
- [ ] Add regression example `regressions/streaming-data-tiers-03-conveyor-01-ledger.py` (public API only; hard-coded goldens, no third-party runtime)
- [ ] Run full check + test suite (`uv run pytest -v`, `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`)

## Testing strategy

Unit tests live only under `tests/`, mirroring `src/molhub/conveyor/`
(`block.py` → `test_block.py`, `ledger.py` → `test_ledger.py`), types mirrored
(`BlockState` → `TestBlockState`). Each test targets one method. Every test runs
offline against `tmp_path`, with an injected frozen clock and a fixed actor —
`uv run pytest tests/test_conveyor/test_ledger.py -v` is a complete loop and
boots no sibling module.

`tests/test_conveyor/test_block.py`

- `TestBlockState` — happy: the nine legal pairs via `may_become` and
  `transition_to`. Edge: the seven illegal pairs each raise `IllegalTransition`
  whose message names both endpoints; `len(BlockState) == 4`; the legality map's
  key set equals the member set (guards a member added without a row);
  `parse("ready")` round-trips and `parse("half-ready")` raises
  `UnknownBlockState`.
- `TestBlockId` — happy: `key()` equals the literal
  `"dataset/themol/torsion-scan@1/torsion/train/shard-003"`; equality, hashing
  and frozen-ness (assignment raises). Edge: empty field, `block_id` containing
  `/`, `split` containing a space, and a `source` that is not a coordinate each
  raise `InvalidBlockId`; an unversioned `source` raises (version pinning is a
  molhub never-change rule).

`tests/test_conveyor/test_ledger.py`

- `TestLedgerRecord` — invariants: naive `datetime`, negative `size_bytes`,
  non-string payload value, and an over-4096-byte serialised line each raise
  `InvalidRecord`; `size_bytes=None` is accepted and serialises as `null`.
- `TestLedgerAppend` — a first append writes exactly one line ending in `\n`
  whose parsed body has the eleven expected keys; the record carries the injected
  actor and clock time; appending `READY` onto `REMOTE` raises
  `IllegalTransition` and writes nothing (file length unchanged); appending the
  current state again succeeds (idempotency).
- `TestLedgerReplay` — empty/absent file replays to an empty mapping; a block
  never mentioned is absent rather than `REMOTE`; last state wins across four
  transitions; a file whose final line is truncated mid-record replays to the
  pre-crash mapping and the next append yields a file with no fragment left; a
  corrupt line in the middle raises `LedgerCorruption` whose message contains
  `":2:"`; a single flipped hex character in a record body raises
  `LedgerCorruption` naming that line; a hand-written `remote → ready` pair in
  the file raises `IllegalTransition` on read.
- `TestLedgerLeases` — a lease is active at `expires_at - 1s` and absent at
  `expires_at` exactly (strict boundary) and after; two holders on one block both
  appear and releasing one leaves the other; `release` returns exactly the blocks
  it actually released and re-releasing returns an empty set with no new line;
  leases survive a fresh `Ledger` instance over the same path; leasing a block
  with no transition history is allowed.

`tests/test_conveyor/test_layering.py` — AST import scan over
`src/molhub/conveyor/*.py`, following `tests/test_sources/test_layering.py`:
no third-party import, no `torch`/`molpy`/`molrs`, no `hashlib`.

**Regression example** —
`regressions/streaming-data-tiers-03-conveyor-01-ledger.py`, public API only,
offline, in a `tempfile` directory, with a fixed clock and the literal actor
`"1234@golden-host"` so output bytes are deterministic. It: (1) drives three
blocks through legal transitions and captures the file bytes; (2) simulates a
kill mid-append by appending a fourth transition and truncating the file to a
byte offset inside that final line; (3) opens a fresh `Ledger`, asserts
`replay()` equals a hard-coded `{key: state-name}` mapping identical to the
pre-crash map; (4) re-appends the same transition and asserts the resulting file
is **byte-identical** to the uninterrupted case, pinned by a hard-coded sha256
hex literal and a hard-coded final-line string; (5) leases a block for 60 s and
asserts membership at `+30 s`, absence at `+61 s`, and absence immediately after
`release`; (6) flips one byte in the second line of a copy and asserts
`LedgerCorruption` naming that line. Every golden is a literal produced by this
repo's own code and pinned so a format change is loud; no third-party oracle
runs, and the module header records tool, command and date in the house form.

## Out of scope

- **Block enumeration / the roster** — how blocks are discovered, listed, and
  ordered. `02-roster`. (Alternative considered: folding a roster into the
  ledger. Rejected — the ledger records *facts that happened*; a roster records
  *what exists*, which is derived from manifests and is rebuildable. Merging them
  would make an append-only log the source of truth for a catalogue.)
- **Download / unpack / prepare / digest-at-the-boundary (I6)** and the conveyor
  root layout. `03-prepare`.
- **Byte-bounded queues, eviction, refcounted deletion (I3, I4, I9 enforcement),
  resident flags, coverage accounting (I10)**. `04-residency`, which consumes the
  lease primitive landed here.
- **Multi-node lease visibility and transition-writer election** — R1's
  mitigation. Deliberately deferred; the single-writer constraint is stated, not
  hidden.
- **Hash-chaining / tamper-proofing of the ledger** — considered in § 5 and
  rejected: it serialises multi-holder appends and answers a threat nobody has.
- **Ledger compaction, rotation, and schema versioning** — considered in § 8; a
  version key nothing branches on is decoration, and compaction has no consumer
  until residency exists.
- **The block *content* format** (`PackedStore` / `PackedCache` v2) — molnex
  `streaming-data-tiers-02-block-format`. Nothing here reads block bytes.
- **Any torch, molnex, or molpy dependency**, and any network access.
