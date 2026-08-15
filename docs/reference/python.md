# Python reference

## Loading datasets

The dataset front door, in HuggingFace spelling. `split` is a required keyword:
`load_dataset` returns one dataset, never a container of splits — discovery is
`load_dataset_builder(name).info.splits`.

<!-- test: skip reads the published THEMol shards and the split derivation under $MOLHUB_HOME -->

```python
from molhub import load_dataset, load_dataset_builder

info = load_dataset_builder("themol/mbis").info   # content, before any bytes
info.features[0]                                  # Feature(name='atomic_charge', level='atom', units='e')
{s.name: s.num_examples for s in info.splits}     # counts, from the split derivation

train = load_dataset("themol/mbis", split="train", revision="1")
len(train)                                        # no shard bytes fetched
train[0]                                          # a molpy Frame
```

### One file at a time

`streaming=True` returns the same split as an iterable dataset instead of a
map-style one. It walks the published files in order, keeps **at most one of them
on local disk** — `disk_budget` bounds what that is allowed to cost — and deletes
each one once it has been read. `take(n)` bounds the walk and releases the file it
stopped inside. Nothing about the transfer, the bookkeeping or the byte
accounting reaches the records: they are the same `molpy.Frame` objects the
map-style view yields.

<!-- test: skip walks the published THEMol shards, which are ~150 GB and not in the test environment -->

```python
from molhub import load_dataset

stream = load_dataset(
    "themol/mbis",
    split="train",
    streaming=True,
    disk_budget=8_000_000_000,   # bytes of fetched files resident at once
)
for frame in stream.take(3):
    print(frame.meta["source_record_id"], frame.meta["source_id"])
```

A dataset published as one whole file has nothing to walk a piece at a time and
says so; read it with `load_dataset(name, split=...)`.

### Materializing a split as blocks

`prepare` writes one split into a molnex block directory, reading it through the
same bounded walk. Blocks are split-pure, so the split is required; what comes
back says where every sealed root is and what it holds. Without molnex
installed it refuses before creating anything, naming the `prepare` extra and the
`MOLNEX_SRC` escape hatch.

<!-- test: skip writes molnex blocks, which needs the THEMol shards and an installed molnex -->

```python
from molhub import prepare

prepared = prepare("themol/torsion-scan", split="train", output_dir="blocks/")
prepared.blocks[0].root          # blocks/themol-torsion-scan@1-train-000
prepared.blocks[0].split         # 'train'
prepared.blocks[0].unit_count    # units sealed into that root
```

molnex reads the directory back with `BlockDataset.load_from_disk("blocks/")`.

A dataset the `molix.block/1` format has no column routes for is refused rather
than exported: `prepare("themol/mbis", ...)` raises before fetching or creating
anything, because writing its geometry would silently drop the atom-level
electrostatics targets the dataset exists for. Read those with
`load_dataset("themol/mbis", split=...)` until the format routes them.

::: molhub.load_dataset

::: molhub.load_dataset_builder

::: molhub.prepare

::: molhub.DatasetBuilder

::: molhub.DatasetInfo

::: molhub.loader.info.Feature

::: molhub.loader.info.SplitInfo

::: molhub.loader.naming.DatasetName

::: molhub.loader.mapstyle.SplitDataset

::: molhub.loader.mapstyle.ShardIndex

::: molhub.loader.streaming.StreamingSplitDataset

::: molhub.loader.streaming.BoundedStream

::: molhub.loader.materialize.BlockExport

## Molhub

::: molhub.Molhub

## Coordinate

::: molhub.Coordinate

## Manifest

::: molhub.Manifest

## Sources

::: molhub.sources.Source

::: molhub.sources.Fetcher
