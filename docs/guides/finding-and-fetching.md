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

## What is in there, before anything moves

`molhub info` answers the content question first — description, what one record
carries, and which splits exist with their counts — and fetches nothing to do it.
The files that carry the dataset are transport, so they live behind `--files`:

```bash
molhub info themol/mbis            # description, features, splits and counts
molhub info themol/mbis --files    # …and the roles, sizes, digests and locators
```

The same answer in Python is `load_dataset_builder(name).info`, which is where
the command line reads it from — one authority, two renderings:

<!-- test: skip reads the THEMol split derivation under $MOLHUB_HOME -->

```python
from molhub import load_dataset_builder

info = load_dataset_builder("themol/mbis").info
print(info.description)
print([(split.name, split.num_examples) for split in info.splits])
```

## Reading a dataset, whole or a piece at a time

Three spellings of the same split, differing only in what they keep on disk:

<!-- test: skip needs the published THEMol shards and the split derivation under $MOLHUB_HOME -->

```python
from molhub import load_dataset, prepare

train = load_dataset("themol/torsion-scan", split="train")                # map-style: train[0]
walk = load_dataset("themol/torsion-scan", split="train", streaming=True)  # one file at a time
prepared = prepare("themol/torsion-scan", split="train", output_dir="blocks/")  # molnex blocks

first = next(iter(walk))                        # one whole scan, as a molpy.Trajectory
assert first.frames[0].meta["source_record_id"]
assert prepared.blocks[0].split == "train"
assert prepared.blocks[0].root.name == "themol-torsion-scan@1-train-000"
```

`streaming=True` takes `disk_budget=` — the bytes of fetched files it may keep —
and `.take(n)` bounds the walk. `prepare` needs molnex installed and refuses,
before writing anything, when it is not; see the `prepare` extra and `MOLNEX_SRC`
in `pyproject.toml`. It also refuses a dataset whose targets `molix.block/1` has
no column routes for — `themol/mbis`, whose atom-level electrostatics an export
could only drop — so those are read with `load_dataset` rather than materialized.
