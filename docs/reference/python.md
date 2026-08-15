# Python reference

## Loading datasets

The dataset front door, in HuggingFace spelling. `split` is a required keyword:
`load_dataset` returns one dataset, never a container of splits — discovery is
`load_dataset_builder(name).info.splits`. `revision` is molhub's `@version`, not
a git sha; leaving it out takes the newest version the registry declares, and
`info.coordinate` echoes the one that was resolved, so a run can record what it
actually read.

<!-- test: fixture-home -->

```python
import molhub

info = molhub.load_dataset_builder("themol/mbis").info   # content, before any shard bytes
assert info.coordinate.canonical.startswith("dataset:themol/mbis@")
assert info.features[0] == molhub.Feature(name="atomic_charge", level="atom", units="e")
assert [split.name for split in info.splits]             # names, from the split derivation

train = molhub.load_dataset("themol/mbis", split="train")
assert len(train)                                        # the split table's count
frame = train[0]                                         # a molpy Frame
assert {"element", "x", "y", "z", "atomic_charge"} <= set(frame["atoms"].keys())
assert "mbis_shells" in frame
```

`len(train)` is the split table's own count, so it costs no shard bytes.
`train[i]` does cost them: a map-style view fetches the published file that owns
row *i*, plus every earlier file it has not indexed yet. Sequential access pays
once per file, random access to a late row pays for the walk — the same semantic
`datasets.load_dataset` has, charged out loud.

### What you get back

A record is a molpy object with no molhub wrapper on top of it. One geometry is a
`molpy.Frame`; a multi-frame sampling unit that must not be broken apart — a
torsion profile, a geometry optimization — is a `molpy.Trajectory` whose
`.frames` are `Frame`s, each with its own `meta`. `info.record_type` says which
of the two a dataset yields before you open it.

Where a value sits on a record follows one rule:

- **Per-atom data are columns of the `atoms` block.** Positions are the three
  columns `x`, `y`, `z` — `frame["atoms"]["x"]` — and forces, where a dataset
  carries them, are `fx`, `fy`, `fz`. Read them as `frame["atoms"]["fx"]`, not
  as a `forces` array: `forces` is the *declared target name*, and the columns
  are what the record holds.
- **Scalars are `frame.meta` entries** — `frame.meta["energy"]`. On a
  `Trajectory`, each frame carries its own, e.g.
  `trajectory.frames[0].meta["torsion_angle"]`.
- **Anything whose row count is neither one nor the atom count is a named block
  of its own**: `frame["mbis_shells"]`, `frame["hessian"]`
  (`row`/`col`/`value`), `frame["scan"]` (the four scanned atom indices).

`type(record)` prints `molrs.frame.Frame`, not `molpy.Frame`. That is the same
class: molpy re-exports its `Frame` and `Block` from molrs, the Rust core it is
built on (`from molrs.frame import Block, Frame` in molpy's own `__init__`). The
API to program against is molpy's, and molhub imports it as `molpy.Frame`.

Which names a record carries, where each of them sits and what it is measured in
is `info.features` — one `Feature(name, level, units)` per declared target, in
name order. `level` is `"atom"` (an `atoms` column), `"meta"` (a `frame.meta`
entry) or `"block"` (a named block); `units` is the unit string the dataset
declares, and `""` when it declares none.

For `themol/mbis` that resolves to fourteen per-atom columns and one block:

| Feature | Level | Units |
|---|---|---|
| `atomic_charge` | `atoms` column | `e` |
| `atomic_volume` | `atoms` column | `angstrom^3` |
| `dipole_x`, `dipole_y`, `dipole_z` | `atoms` columns | `e*angstrom` |
| `quadrupole_xx` … `quadrupole_zz` (nine ordered index pairs) | `atoms` columns | `e*angstrom^2` |
| `mbis_shells` | block | see below |

The `mbis_shells` block is one row per MBIS Slater **shell**, not per atom:
hydrogen carries one shell, most heavy atoms two, a third-period atom can carry
three, so it has more rows than the molecule has atoms and its rows do not line
up with `atoms` at all. Its three columns are `atom` (the shell's atom index),
`population` (in `e`) and `inverse_width` (in `angstrom^-1`). The two floats
disagree on their unit, which is why the block declares no single `units` string
and `Feature("mbis_shells", "block", "")` carries an empty one.

`meta["source_record_id"]` and `meta["source_id"]` are THEMol provenance — the
record's group key in the published file, and the coordinate-plus-role of the
file it came from. They are written by THEMol's reader, so they are not a
promise every dataset makes: a 3BPA record's `meta` holds `energy` and nothing
else, with its forces in the `fx`/`fy`/`fz` columns.

### How much a dataset weighs

`info.download_size` is every declared byte of the artifact — what a full
download costs, in bytes, summed over the files the manifest declares. It is a
per-dataset number, not a number for THEMol as a whole: `themol/mbis` declares
`31041658614` bytes (28.9 GiB), while `themol/hessian-relax` declares
`1048543472353` (976.5 GiB). `print(info)` renders the count in binary units and
keeps the exact value on `download_size` for whatever greps it.

### One file at a time

`streaming=True` returns the same split as an iterable dataset instead of a
map-style one. It walks the published files in manifest order, keeps **at most
one of them on local disk** — `disk_budget` bounds what that is allowed to cost,
and a file too large for the budget is refused before it is fetched — and
deletes each file once it has been read. `take(n)` bounds the walk and releases
the file it stopped inside.

<!-- test: fixture-home -->

```python
import molhub

walk = molhub.load_dataset(
    "themol/mbis",
    split="train",
    streaming=True,
    disk_budget=8_000_000_000,   # bytes of fetched files resident at once
)
for frame in walk.take(1):
    print(frame.meta["source_record_id"], frame.meta["source_id"])
```

The file a walk deletes is the one in `$MOLHUB_HOME` — the same cache
`molhub fetch` fills and the map-style view reads, since a walk fetches through
the same hub. Two consequences worth stating plainly:

- **A walk that finishes leaves nothing behind, so walking it again re-fetches
  it.** That is the design: a bounded-disk read of a 28.9 GiB dataset cannot
  also be a warm cache of it. If you want the bytes to stay, read the split
  map-style.
- **A walk that crashes keeps what it had.** When the code reading the records
  raises, the walk closes the file handle and gives up its claim, and stops
  there: it does not record the file as consumed and does not delete it. The
  bytes are verified and still local, so a decode bug does not cost a re-download
  of a multi-gigabyte file.

Nothing about the transfer, the bookkeeping or the byte accounting reaches the
records: they are the same `molpy.Frame` objects the map-style view yields.

A dataset published as one whole file has nothing to walk a piece at a time and
says so; read it with `load_dataset(name, split=...)`.

### Materializing a split as blocks

`prepare` writes one split into a molnex block directory, reading it through the
same bounded walk. Blocks are split-pure, so the split is required; what comes
back says where every sealed root is and what it holds.

<!-- test: skip writes molnex molix.block/1 blocks, which needs molnex importable -->

```python
from molhub import prepare

prepared = prepare("themol/torsion-scan", split="train", output_dir="blocks/")
prepared.blocks[0].root          # blocks/themol-torsion-scan@1-train-000
prepared.blocks[0].split         # 'train'
prepared.blocks[0].unit_count    # units sealed into that root
prepared.blocks[0].frame_count   # frames those units hold
```

molnex reads the directory back with `BlockDataset.load_from_disk("blocks/")`.

Blocks are molnex's format and molnex is not on PyPI, so `prepare` resolves its
writer — by really importing `molix.store.block` and `torch` — **before** it
creates anything, and refuses with an `ImportError` naming both ways out:
`pip install 'molhub[prepare]'` for the publishable half (torch), and a molnex
source checkout for the other. `MOLNEX_SRC` is that escape hatch and is honoured
here: its value is put at the front of `sys.path` before the probe and left
there, because the writer imports molnex again when it opens its first block.
Point it at the checkout's `src/` directory. Injecting `writer_factory=` a
writer of your own bypasses the whole question.

### When a split cannot be opened

Four refusals, each decided before anything is fetched. The three named types are
importable from `molhub` itself — `except molhub.UnknownSplit` catches exactly
what the layer underneath raised — and the fourth is a plain `ValueError`.

**`SplitTableUnavailable` — the split derivation has never been built here.**
THEMol's splits are a published derivation,
`dataset:molcrafts/class1-universal-splits@1`, filed under
`$MOLHUB_HOME/derived/molcrafts/class1-universal-splits/1/`. Nothing downloads
it: nobody publishes that assignment, it is derived on your machine by the
generator molhub ships.

```bash
python -m molhub.scripts.build_class1_splits
```

It folds together the index file of all three THEMol subsets it covers
(`hessian`, `mbis`, `torsion-scan`), which on a machine that has not cached them
is a multi-gigabyte download — so it states the cost and stops until it is
re-run with `--fetch`, which is you authorising that download. `--seed` fixes
the shuffle (default `20260814`) and `--molhub-home` selects the home it writes
under, defaulting to `$MOLHUB_HOME`. The assignment is molecule-level: every
conformer, scan and subset row of one molecule lands in one split.

**`UnknownSplit` — a name this dataset does not declare.** A `KeyError` that
renders as a sentence listing the names that do exist. It is decided against the
declaration before any byte is fetched, so a typo cannot cost a download. A
dataset that declares no splits at all raises the same type: its whole content
is one view.

**`UnsupportedRecordError` — the block format has no columns for this dataset.**
`prepare("themol/mbis", ...)` raises it, and creates nothing: `molix.block/1`
routes none of MBIS's atom-level electrostatics targets, so an export would
write the geometry and topology and silently drop every target the dataset
exists for. Read them with `load_dataset("themol/mbis", split=...)` until the
format routes them.

**`ValueError` — the payload needs a conversion this machine has not run.** Both
espaloma datasets publish bytes their own reader cannot open (a tarball of SDF
structures, a zip of DGL heterographs), and the refusal comes *before* the
download rather than as a `FileNotFoundError` after it.

<!-- test: fixture-home -->

```python
import molhub

try:
    molhub.load_dataset("themol/mbis", split="validation")
except molhub.UnknownSplit as error:
    print(error)          # names the splits this dataset does declare
else:
    raise AssertionError("expected UnknownSplit was not raised")

try:
    molhub.prepare("themol/mbis", split="train", output_dir="blocks/")
except molhub.UnsupportedRecordError as error:
    print(error)          # nothing was fetched and nothing was created
else:
    raise AssertionError("expected UnsupportedRecordError was not raised")
```

::: molhub.load_dataset

::: molhub.load_dataset_builder

::: molhub.prepare

::: molhub.DatasetBuilder

::: molhub.DatasetInfo

::: molhub.loader.info.Feature

::: molhub.loader.info.SplitInfo

::: molhub.loader.info.ByteSize

::: molhub.loader.naming.DatasetName

::: molhub.loader.naming.AmbiguousRevision

::: molhub.loader.errors.SplitTableUnavailable

::: molhub.loader.errors.UnknownSplit

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
