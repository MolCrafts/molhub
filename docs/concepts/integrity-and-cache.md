# Integrity and cache

The transport contract is status check, temporary file, complete stream, optional published-digest
check, then atomic rename. A partial response never occupies the final cache path.

The cache key is coordinate plus artifact role:

```text
$MOLHUB_HOME/files/<kind>/<namespace>/<name>@<version>/<role>
```

This is not a content-addressed store. The coordinate already names the version, including sources
whose platform publishes no digest. Python and Node deliberately share this layout.

## What else lives under a molhub home

`files/` is the cross-client contract and the only thing the TypeScript client
reads. Three more roots sit beside it, all written by the Python side:

```text
$MOLHUB_HOME/derived/<namespace>/<name>/<version>/   derived artifacts + metadata.json
$MOLHUB_HOME/conveyor/ledger.jsonl                   the bookkeeping log
$MOLHUB_HOME/conveyor/raw/  conveyor/blocks/         the two byte-budgeted tiers
```

**`derived/` holds what this machine computed rather than downloaded.** The
layout is coordinate-shaped — `<namespace>/<name>/<version>/` — and every
artifact directory carries a `metadata.json` recording who derived it and when;
a document missing `generator` or `generated_at` is refused rather than filed,
because that is the one provenance question a path cannot answer. Two things
are filed there today: the Class-I split derivation
(`derived/molcrafts/class1-universal-splits/1/`, the four gzipped CSVs written
by `python -m molhub.scripts.build_class1_splits`), and the per-shard record-key
memos that map-style access writes under the dataset's own coordinate, so a
second process never re-opens a published file just to list its keys. Nothing
in `derived/` is downloadable; deleting it costs a recomputation, not a
re-download.

**`conveyor/ledger.jsonl` is the bookkeeping.** One append-only JSON line per
transition of one payload — `REMOTE` (nothing local), `DOWNLOADING`, `READY`
(local, verified), `CONSUMED` — plus the leases that say who is currently
holding something. It is a state log, not a retry log, and it is on disk rather
than in memory precisely so a report survives the process that produced it.

**`conveyor/raw/` and `conveyor/blocks/` are the two tiers**, one for published
files in flight and one for sealed derived blocks, each with its own byte budget
(40 GB by default) and its own candidate set, so pressure on one can never evict
an entry of the other. Neither is under `files/`.

## Streaming deletes what it has read

A streaming walk (`load_dataset(..., streaming=True)`) fetches each published
file through the same hub everything else uses, which means into the same
`files/` cache — and then, once it has read the file to the end, records it
consumed, **deletes those bytes** and releases its claim. It is a bounded-disk
read, not a download: the point is that walking a 28.9 GiB dataset costs one
file of disk rather than 28.9 GiB of it.

Two consequences, both by design:

- A walk that runs to completion leaves nothing cached, so a second walk
  re-fetches. If you want the bytes to stay, read the split map-style.
- A walk interrupted by an exception from the code reading the records does
  **not** delete. It closes the file handle and gives up the claim, and stops
  there: the file is verified and local, its last recorded state is `READY`, and
  the next run re-verifies it on the cache hit. A decode bug does not cost a
  re-download of a multi-gigabyte file.

## Reporting on it from the command line

Two nouns run through these reports. A **block** is one payload the conveyor
addresses and moves — a published file on the way in, or a sealed molnex block
directory on the way out. A **unit** is one indivisible sampling record inside a
block: one `Frame`, or one whole `Trajectory` such as a torsion scan, and the
granularity below which a batch plan cannot cut.

```bash
molhub cache verify                 # re-check cached files against their manifests' digests
molhub cache status                 # per-tier residency against each tier's budget
molhub cache coverage               # what this machine has seen of the declared corpus
```

`cache verify` walks the registry, re-hashes every cached file with the
algorithm its manifest published and reports how many were checked, how many
disagree (exit code 1), and how many carry no published digest to check against.

`cache status` prints one line per tier — entries, bytes resident, bytes
budgeted — and exits 1 when a tier holds more than its budget allows, because
that is the bounded-residency invariant failing on disk and a status verb nothing
can gate on is not worth running. `--budget-raw` and `--budget-blocks` set the
two numbers; `--home` selects the cache root.

`cache coverage` replays `conveyor/ledger.jsonl` and prints blocks seen, blocks
consumed as a share of the corpus, units seen, and the byte totals (downloaded,
prepared, evicted, raw released). The denominator is the block roster projected
from the registry's own manifests — without one the command exits 1 rather than
printing a coverage number nobody can interpret.
