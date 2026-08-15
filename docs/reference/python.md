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

::: molhub.load_dataset

::: molhub.load_dataset_builder

::: molhub.DatasetBuilder

::: molhub.DatasetInfo

::: molhub.loader.info.Feature

::: molhub.loader.info.SplitInfo

::: molhub.loader.naming.DatasetName

::: molhub.loader.mapstyle.SplitDataset

::: molhub.loader.mapstyle.ShardIndex

## Molhub

::: molhub.Molhub

## Coordinate

::: molhub.Coordinate

## Manifest

::: molhub.Manifest

## Sources

::: molhub.sources.Source

::: molhub.sources.Fetcher
