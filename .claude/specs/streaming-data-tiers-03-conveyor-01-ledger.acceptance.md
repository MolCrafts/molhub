---
slug: streaming-data-tiers-03-conveyor-01-ledger
criteria:
  - id: ac-001
    summary: block lifecycle is a closed four-state machine
    type: code
    pass_when: |
      tests/test_conveyor/test_block.py passes with all sixteen ordered
      (from, to) pairs parametrized: the ten legal pairs of the spec's table
      return True from may_become and are accepted by transition_to, and the
      six illegal ones raise IllegalTransition naming both endpoints.
      len(BlockState) == 4 and the legality map's key set equals the member set.
    status: pending
  - id: ac-002
    summary: no string state and no fifth state crosses a seam
    type: code
    pass_when: |
      BlockState.parse is the only str -> state entry point in
      src/molhub/conveyor/ (it raises UnknownBlockState on an unknown name), no
      other public parameter or return value in block.py or ledger.py is typed
      as a bare state string, and no "resident"/"pending"/"failed" member or
      literal exists anywhere in the package.
    status: pending
  - id: ac-003
    summary: BlockId keys are stable, injective and coordinate-validated
    type: code
    pass_when: |
      tests/test_conveyor/test_block.py asserts
      BlockId("dataset:themol/torsion-scan@1", "torsion", "train",
      "shard-003").key() == "dataset/themol/torsion-scan@1/torsion/train/shard-003"
      as a literal, that BlockId(..., split=None, ...).key() uses the reserved
      "unsplit" segment while split="unsplit" raises InvalidBlockId, and that an
      unparseable or unversioned source, an empty field, or a field containing
      "/" or whitespace each raise InvalidBlockId rather than being sanitised.
    status: pending
  - id: ac-004
    summary: replay reconstructs the state map and refuses impossible histories
    type: code
    pass_when: |
      tests/test_conveyor/test_ledger.py shows replay() returning last-state-wins
      per BlockId over a multi-block file, omitting (not defaulting to REMOTE)
      blocks the ledger never mentioned, and raising IllegalTransition naming the
      line when the file records a remote -> ready pair.
    status: pending
  - id: ac-005
    summary: a kill mid-append leaves a repairable ledger
    type: code
    pass_when: |
      tests/test_conveyor/test_ledger.py truncates a ledger to a byte offset
      inside its final record and shows that a fresh Ledger replays to the
      pre-crash mapping, and that the next append truncates to the last good
      boundary so the resulting file contains no fragment and every line parses.
    status: pending
  - id: ac-006
    summary: a flipped byte is detected and located
    type: code
    pass_when: |
      Flipping one character inside the body of line 2 of a valid ledger makes
      replay() raise LedgerCorruption whose message contains the file path and
      ":2:"; a newline-terminated final line with a corrupted digest also raises
      LedgerCorruption (bit rot, not a crash artifact); only an unterminated
      final line is discarded silently.
    status: pending
  - id: ac-007
    summary: digests go through molhub.sources.digest, never ad hoc
    type: code
    pass_when: |
      `grep -rn "hashlib" src/molhub/conveyor/` returns nothing, ledger.py
      imports Sha256Stream from molhub.sources.digest, and record verification
      compares via Digest.matches (constant-time) rather than string ==.
    status: pending
  - id: ac-008
    summary: TTL leases expire, release immediately, and refcount by holder
    type: code
    pass_when: |
      tests/test_conveyor/test_ledger.py shows active_leases excluding a lease at
      exactly expires_at and after it, including it strictly before, excluding it
      immediately after release, listing both holders when two hold one block,
      and returning an empty frozenset (writing no new line) when a holder
      releases a block it does not hold; additionally two Ledger instances over
      the same path constructed with distinct explicit actor plan ids hold
      independent leases on one block (the plan-scoped I9 convention).
    status: pending
  - id: ac-009
    summary: the conveyor package is stdlib plus molhub only
    type: code
    pass_when: |
      tests/test_conveyor/test_layering.py AST-scans every file in
      src/molhub/conveyor/ and finds no import whose root module is outside the
      standard library or `molhub` — specifically none of torch, numpy, molpy,
      molrs, requests, h5py — at module level or inside any function.
    status: pending
  - id: ac-010
    summary: crash-resume regression reproduces byte-identical goldens offline
    type: runtime
    pass_when: |
      `uv run python regressions/streaming-data-tiers-03-conveyor-01-ledger.py`
      exits 0 with no network, reproducing its hard-coded goldens: the sha256 hex
      literal of the final ledger file and its literal final line are identical
      to the uninterrupted run after truncate-and-resume, the replayed
      {key: state} mapping matches its literal, the 60 s lease is present at
      +30 s and absent at +61 s and after release, and a flipped byte raises
      LedgerCorruption naming the line.
    status: pending
  - id: ac-011
    summary: molhub check and test gates stay green
    type: code
    pass_when: |
      `uv run pytest -v`, `uv run ruff check src/ tests/` and
      `uv run ruff format --check src/ tests/` all pass with the new package and
      tests included.
    status: pending
  - id: ac-012
    summary: record invariants reject the failure-shaped values
    type: code
    pass_when: |
      tests/test_conveyor/test_ledger.py shows InvalidRecord raised for a naive
      datetime, for size_bytes=0 (aligning with the manifest size>0 rule — zero
      is the shape of a failed transfer, .claude/notes/notes.md), for negative
      size_bytes, for a non-string payload value, and for a serialised line over
      4096 bytes; size_bytes=None is accepted and serialises as null.
    status: pending
---

# Acceptance criteria

ac-001 and ac-002 together are what discharge invariant **I5**: the first proves
the transition table, the second proves no one can route around it with a
string or add a fifth state (residency is a flag owned by `04-residency`, never a
state). ac-005 and ac-010 are the crash-recovery pair — the unit test proves the
repair rule, the regression proves it end-to-end at the public API and pins the
bytes, so a change to record serialisation becomes a loud diff rather than a
silent format fork.

ac-007 deserves a note for reviewers. `CLAUDE.md` states that **molhub never
computes a digest of its own**; that rule governs *upstream artifact* content,
where a self-computed hash proves only what one download contained and would
force hauling a whole artifact before cataloguing it. The ledger digest is over
molhub's own locally authored record bytes and makes no provenance claim about
any upstream artifact, so the rule is intact. The criterion additionally closes
standing debt: `Sha256Stream` has had zero production consumers since it landed,
and this spec is its first.

ac-008 lands the lease primitive that invariant **I9** (plan-scoped, refcounted
deletion) will consume in `04-residency`. Leases are ledger records with a TTL
rather than `fcntl` locks because the target filesystem is Lustre and because a
crashed holder must lose its grip without anyone reaping it; release is
implemented as "shorten the lease to zero", so expiry and release share one rule
and this criterion tests one mechanism, not two.
