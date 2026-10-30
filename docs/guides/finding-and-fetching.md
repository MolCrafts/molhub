# Finding and fetching

Resolution and search are offline when using the bundled Python registry.

<!-- test: exec -->
```python
from molhub import Molhub

hub = Molhub()
entry = hub.resolve("polymer-tg@v1")
assert entry.coordinate.canonical == "dataset:molcrafts/polymer-tg@v1"
assert hub.resolve("polymer-tg@v7").doi == "10.5281/zenodo.15789599"
assert hub.search(query="polymer")[0].coordinate.name == "polymer-tg"
```

Fetching contacts the ordered locators only on a cold cache:

```bash
molhub search polymer
molhub info dataset:molcrafts/polymer-tg@v7
molhub fetch polymer-tg@v7 --into ./data
```

In Python, call `hub.fetch(coordinate, roles=["main"])`. In Node, pass an explicit registry snapshot
to `Molhub` and call its asynchronous `fetch` method.

## What is in there, before you read it

`molhub info` answers the content question first — description, what one record
carries, and which splits exist with their counts. The files that carry the
dataset are transport, so they live behind `--files`:

```bash
molhub info themol/mbis            # description, features, splits and counts
molhub info themol/mbis --files    # …and the roles, sizes, digests and locators
molhub info themol/mbis --home /scratch/molhub   # read a second cache root
```

`--home` is there because the answer partly comes off disk: THEMol's split counts
are read from the split derivation under the cache root, so without it there
would be no way to describe a dataset against a second molhub home except by
exporting `$MOLHUB_HOME` around the command.

**Whether describing costs a download depends on where the splits come from.**
For a dataset whose splits a published derivation states — the three THEMol
subsets — the counts come from one gzipped table already on disk, and `info`
fetches no dataset bytes at all. (It does need that derivation to have been
built; if it has not, the command says so and names
`python -m molhub.scripts.build_class1_splits`, which writes it.) Everywhere
else the count is the dataset's own `len`, and having it means reading the
files. That is true of `molhub info molcrafts/3bpa`, which downloads all four
benchmark files — about 18.5 MiB — before it can print one count per split, and
it is equally true of `molhub info qm9`: qm9 publishes no split, so its whole
content is served as `train`, and counting that one split means loading the
dataset. Neither command is free.

What says so is a notice printed to stderr before the first byte moves:

```text
Counting the splits of dataset:molcrafts/3bpa@v1 will download 18.5 MiB (19400078 B) first. The files stay in the molhub cache, so reading them again costs nothing.
```

The notice belongs to the **library**, not to the CLI, so the same sentence
appears when a notebook or a training script calls `load`. It also
fires on the map-style record path, where it opens with `Reading a record of`
instead: `train[0]` on a THEMol split pulls the multi-GiB published file
holding row 0, and that cost is now said out loud. It stays silent for a file
already in this home's cache — a warning printed on every cache hit is one
nobody reads by the third call — and stderr keeps a piped report unchanged.

Describe an artifact from the shell. There is no second Python type for this:

```console
$ molhub info themol/mbis
```

<!-- test: fixture-home -->

```python
import molhub

ds = molhub.load("themol/mbis")
assert len(ds) > 0
```

## Reading a dataset, whole or a piece at a time

Two spellings of the same split, differing only in what they keep on disk:

<!-- test: fixture-home -->

```python
import molhub

ds = molhub.load("themol/mbis")                  # map-style, whole artifact
walk = molhub.load("themol/mbis", streaming=True)   # one file at a time

record = ds[0]                                   # FrameCollection = Sequence[Frame]
frame = record[0]                                # one geometry
assert frame.meta["source_record_id"]            # which published record this is
assert walk.take(1).limit == 1                   # take(n) bounds the walk
```

An MBIS record is a length-1 `FrameCollection`. A `themol/torsion-scan`
record is a longer collection whose frames each carry their own
`meta["torsion_angle"]`. There is no `Trajectory` on this surface.

`streaming=True` takes `disk_budget=` — the bytes of fetched files it may keep —
and deletes each file once it has been read, out of the same `$MOLHUB_HOME`
cache `molhub fetch` fills. A completed walk therefore leaves nothing to re-read;
a walk interrupted by an exception keeps the verified file it was inside. See
[the Python reference](../reference/python.md) for the whole rule.

The third spelling is `prepare`, which materializes one split as sealed
blocks through that same bounded walk:

<!-- test: skip prepare has no default writer; pass writer_factory= -->

```python
from molhub import prepare

prepare("themol/torsion-scan", output_dir="blocks/")
```

`prepare` has no default writer. Pass `writer_factory=` a writer of your own;
omitting it raises `ValueError` before anything is written. It also refuses a
dataset whose targets have no column on `RawUnit` — `themol/mbis`, whose
atom-level electrostatics an export could only drop — so those are read with
`load` rather than materialized. The writer's format string is left as
recorded: molhub checks that the sealed manifest names the split, the unit
count and a block digest.
