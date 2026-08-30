# Python reference

## Loading datasets

A dataset is a class. `load` / `fetch` / `search` are name verbs, not
kind-specific factories. There is no `load_dataset`.

<!-- test: fixture-home -->

```python
import molhub

ds = molhub.load("themol/mbis")
train = molhub.SubsetDataset(ds, molhub.assignment(ds)["train"])
record = train[0]                                        # FrameCollection
frame = record[0]                                        # one geometry
assert {"element", "x", "y", "z", "atomic_charge"} <= set(frame["atoms"].keys())
assert "mbis_shells" in frame
```

`len(train)` is the split table's own count, so it costs no shard bytes.
`train[i]` does cost them: a map-style view fetches the published file that owns
row *i*, plus every earlier file it has not indexed yet. Sequential access pays
once per file, random access to a late row pays for the walk — the same semantic
`datasets.load_dataset` has, charged out loud.

Opening a *declared* split downloads that split's file — `load_dataset("3bpa",
split="test_600K")` fetches the 3BPA file carrying it — and both the map-style
record path announce what they are about to pull on stderr first,
staying silent for anything already cached. One honest gap remains: constructing
the view itself for a declared or whole-content dataset (3BPA, qm9, polymer-tg)
fetches inside the dataset's own constructor and is the one path that can still
move bytes without a notice. A later spec closes it; until then, ask
`molhub info <name>` first if the number matters.

### Which datasets this door serves

`load` / `prepare` dispatch off one table, and
a dataset that is not in it is refused rather than half-served. Eight entries:

| Dataset | Splits | Where they come from |
|---|---|---|
| `themol/hessian`, `themol/mbis`, `themol/torsion-scan` | `train`, `val`, `test` | the published derivation `class1-universal-splits@1` — a table, so counting is free |
| `molcrafts/3bpa` | `train_300K`, `test_300K`, `test_600K`, `test_1200K` | one published extended-XYZ file per split |
| `espaloma/zinc-typing`, `espaloma/phalkethoh-mm-small` | `train`, `val`, `test` (names only) | the payload's own `splits.json`, reachable only once the published bytes have been converted — see the conversion refusal below |
| `molcrafts/qm9`, `molcrafts/polymer-tg` | `train` | nobody publishes a split of them, so their whole content is served as one view, under the name HuggingFace uses for "all of it" |

Three more are addressable and describable but have no split to declare, and
their refusal hands over the class API that opens them: `molcrafts/revmd17`
(`RevMD17Dataset(root, molecule="aspirin").load()` — the molecule is a selector no
coordinate carries), `themol/hessian-relax` and `themol/torsion-relax`
(`THEMolHessianRelax(hub=hub).load(role="shard-000")` and its torsion sibling —
published in parts, with no table saying which record is in which split).
Anything else in the registry is bytes molhub ships no reader for: fetch it with
`molhub fetch <coordinate>` and read it yourself.

### What you get back

A record is a `FrameCollection` (`Sequence[Frame]`) with no molhub wrapper
on top of it. One geometry is a length-1 collection; a multi-frame sampling
unit that must not be broken apart — a torsion profile, a geometry
optimization — is a longer collection whose frames each carry their own
`meta`. `info.record_type` is `FrameCollection` either way.

Where a value sits on a record follows one rule:

- **Per-atom data are columns of the `atoms` block.** Positions are the three
  columns `x`, `y`, `z` — `frame["atoms"]["x"]` — and forces, where a dataset
  carries them, are `fx`, `fy`, `fz`. Read them as `frame["atoms"]["fx"]`, not
  as a `forces` array: `forces` is the *declared target name*, and the columns
  are what the record holds.
- **Scalars are `frame.meta` entries** — `frame.meta["energy"]`. On a
  multi-frame record, each frame carries its own, e.g.
  `record[0].meta["torsion_angle"]`.
- **Anything whose row count is neither one nor the atom count is a named block
  of its own**: `frame["mbis_shells"]`, `frame["hessian"]`
  (`row`/`col`/`value`), `frame["scan"]` (the four scanned atom indices).

`type(record)` prints `molrs.frame.Frame`, not `molpy.Frame`. That is the same
class: molpy re-exports its `Frame` and `Block` from molrs, the Rust core it is
built on (`from molrs.frame import Block, Frame` in molpy's own `__init__`). The
API to program against is molpy's, and molhub imports it as `molpy.Frame`.

Which names a record carries is on the `Frame` itself. `molhub info` prints
the declared names, where each sits (`atom` column / `meta` / named block),
and the unit string the dataset declares.

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
and `molhub info` prints an empty unit for that block.

`meta["source_record_id"]` and `meta["source_id"]` are THEMol provenance — the
record's group key in the published file, and the coordinate-plus-role of the
file it came from. They are written by THEMol's reader, so they are not a
promise every dataset makes: a 3BPA record's `meta` holds `energy` and nothing
else, with its forces in the `fx`/`fy`/`fz` columns.

### How much a dataset weighs

`molhub info themol/mbis` prints every declared byte of the artifact — what a
full download costs, summed over the files the manifest declares. It is a
per-dataset number, not a number for THEMol as a whole: `themol/mbis` is
28.9 GiB; `themol/hessian-relax` is 976.5 GiB.

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

walk = molhub.load(
    "themol/mbis",
    streaming=True,
    disk_budget=8_000_000_000,   # bytes of fetched files resident at once
)
for record in walk.take(1):
    frame = record[0]
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
says so; read it with `load_dataset(name)`.

### Materializing as blocks

`prepare` writes the dataset into a molnex block directory, reading it through
the same bounded walk.

<!-- test: skip writes molnex molix.block/1 blocks, which needs molnex importable -->

```python
from molhub import prepare

prepare("themol/torsion-scan", output_dir="blocks/")
# molnex: BlockDataset.load_from_disk("blocks/")
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
declaration before any byte is fetched, so a typo cannot cost a download.

A dataset the door does not serve at all raises the same type, and the message
hands over the door that *is* open rather than dead-ending on molhub's own
table. `molcrafts/qm9` and `molcrafts/polymer-tg` are not in that group — their
whole content is served as `split="train"` — so what it covers is the three
artifacts whose reader needs a selector a coordinate does not carry:
`load_dataset("revmd17", split="train")` refuses by naming
`RevMD17Dataset(root, molecule="aspirin").load()`, and the two THEMol relax artifacts
refuse by naming `THEMolHessianRelax(hub=hub).load(role="shard-000")` /
`THEMolTorsionRelax(hub=hub).load(role="shard-000")`. For a registry artifact
molhub ships no reader for, the refusal says so and points at
`molhub fetch <coordinate>`.

**`UnsupportedRecordError` — the block format has no columns for this dataset.**
`prepare("themol/mbis", ...)` raises it, and creates nothing: `molix.block/1`
routes none of MBIS's atom-level electrostatics targets, so an export would
write the geometry and topology and silently drop every target the dataset
exists for. Read them with `load_dataset("themol/mbis", split=...)` until the
format routes them.

**`ValueError` — the payload needs a conversion this machine has not run.** Both
espaloma datasets publish bytes their own reader cannot open, and the refusal
comes *before* the download rather than as a `FileNotFoundError` after it. Both
readers want the same converted tree: a `splits.json` beside a `mols/`
directory.

`espaloma/phalkethoh-mm-small` is a zip of DGL heterographs, and molhub ships
the conversion inside the wheel:

```bash
python -m molhub.scripts.convert_espaloma_phalkethoh_mm --src <zip> --out <dir>
```

`--help` answers in any environment, because the arguments are parsed before dgl
is imported; *running* it needs `dgl==1.1.3`, which molhub does not depend on and
which is why the conversion is offline and once. Without dgl it says which
package is missing and that nothing was written. Then point
`PhalkethohMMDataset` at what it wrote.

`espaloma/zinc-typing` is a tarball of SDF structures and has **no** shipped
converter — the module above reads the other payload and would not help. Fetch
the archive with `molhub fetch dataset:espaloma/zinc-typing@1`, write the
`splits.json` + `mols/` tree once yourself, and point `ZincTypingDataset` at it.

<!-- test: fixture-home -->

```python
import molhub

try:
    molhub.prepare("themol/mbis", output_dir="blocks/")
except molhub.UnsupportedRecordError as error:
    print(error)          # nothing was fetched and nothing was created
else:
    raise AssertionError("expected UnsupportedRecordError was not raised")
```

::: molhub.load

::: molhub.prepare

::: molhub.loader.naming.AmbiguousRevision

::: molhub.loader.errors.SplitTableUnavailable

::: molhub.loader.errors.UnknownSplit

::: molhub.loader.mapstyle.SplitDataset

::: molhub.loader.streaming.StreamingSplitDataset

## Molhub

::: molhub.Molhub

## Coordinate

::: molhub.coordinate.Coordinate

## Manifest

::: molhub.manifest.Manifest

## Sources

::: molhub.sources.Source

::: molhub.sources.Fetcher
