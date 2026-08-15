# Finding and fetching

Resolution and search are offline when using the bundled Python registry.

<!-- test: exec -->
```python
from molhub import Molhub

hub = Molhub()
entry = hub.resolve("polymer-tg@1")
assert entry.coordinate.canonical == "dataset:molcrafts/polymer-tg@1"
assert hub.search(query="polymer")[0].coordinate.name == "polymer-tg"
```

Fetching contacts the ordered locators only on a cold cache:

```bash
molhub search polymer
molhub info dataset:molcrafts/polymer-tg@1
molhub fetch polymer-tg@1 --into ./data
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
appears when a notebook or a training script calls
`load_dataset_builder(name).info` — the path that surprised people never went
through `molhub info` at all. It also fires on the map-style record path, where
it opens with `Reading a record of` instead: `train[0]` on a THEMol split pulls
the multi-GiB published file holding row 0, and that cost is now said out loud.
It stays silent for a file already in this home's cache — a warning printed on
every cache hit is one nobody reads by the third call — and stderr keeps a piped
report unchanged.

The same answer in Python is `load_dataset_builder(name).info`, which is where
the command line reads it from — one authority, two renderings:

<!-- test: fixture-home -->

```python
import molhub

builder = molhub.load_dataset_builder("themol/mbis")
assert builder.describe_download_size == 0        # a table-backed dataset describes free
info = builder.info
print(info.description)
print([(split.name, split.num_examples) for split in info.splits])
```

## Reading a dataset, whole or a piece at a time

Two spellings of the same split, differing only in what they keep on disk:

<!-- test: fixture-home -->

```python
import molhub

train = molhub.load_dataset("themol/mbis", split="train")                  # map-style
walk = molhub.load_dataset("themol/mbis", split="train", streaming=True)   # one file at a time

first = train[0]                                 # a molpy.Frame
assert first.meta["source_record_id"]            # which published record this is
assert walk.take(1).limit == 1                   # take(n) bounds the walk
```

Which of the two record types comes back is the dataset's own business and is
stated by `info.record_type`: an MBIS record is one geometry, so it is a
`Frame`, while a `themol/torsion-scan` record is a whole constrained scan and
comes back as a `molpy.Trajectory` whose `.frames` each carry their own
`meta["torsion_angle"]`.

`streaming=True` takes `disk_budget=` — the bytes of fetched files it may keep —
and deletes each file once it has been read, out of the same `$MOLHUB_HOME`
cache `molhub fetch` fills. A completed walk therefore leaves nothing to re-read;
a walk interrupted by an exception keeps the verified file it was inside. See
[the Python reference](../reference/python.md) for the whole rule.

The third spelling is `prepare`, which materializes one split as sealed molnex
blocks through that same bounded walk:

<!-- test: skip writes molnex molix.block/1 blocks, which needs molnex importable -->

```python
from molhub import prepare

prepared = prepare("themol/torsion-scan", split="train", output_dir="blocks/")
assert prepared.blocks[0].split == "train"
assert prepared.blocks[0].root.name == "themol-torsion-scan@1-train-000"
```

`prepare` needs molnex importable and refuses, before writing anything, when it
is not — naming the `prepare` extra (`pip install 'molhub[prepare]'`, which
brings torch) and `MOLNEX_SRC`, which it puts on `sys.path` for you when it is
set. It also refuses a dataset whose targets `molix.block/1` has no column routes
for — `themol/mbis`, whose atom-level electrostatics an export could only drop —
so those are read with `load_dataset` rather than materialized.
