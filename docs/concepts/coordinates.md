# Coordinates

A coordinate has the canonical form `kind:namespace/name@version`. The version is mandatory and
`latest` is never resolved implicitly.

<!-- test: exec -->
```python
from molhub.coordinate import Coordinate

coordinate = Coordinate.parse("qm9@v2")
assert coordinate.canonical == "dataset:molcrafts/qm9@v2"
assert coordinate.cache_path() == "dataset/molcrafts/qm9@v2"
```

Coordinates belong to MolHub. Locators belong to upstream platforms and may be replaced or reordered
without changing user code.

## Where the version comes from when you did not type one

The rule above is about **coordinates**, and it does not bend: `Coordinate.parse`
refuses a name with no `@version`, so every coordinate — in a manifest, in a
cache path, in a provenance record — names exactly one immutable artifact.

The dataset loader adds one step *in front of* that. `load_dataset("themol/mbis")`
names an artifact, not a version, and its `revision=` argument is molhub's
`@version` in HuggingFace spelling — never a git sha. Leaving `revision` out
means "the newest the registry declares", decided by a numeric-aware natural
order (`2` before `10`, `v2` before `v3`). Two rules therefore apply in two
places:

- **A coordinate is always fully pinned.** Nothing resolves `latest`, and no
  API hands back an unversioned coordinate.
- **The loader defaults `revision` to the newest declared version, and then
  pins it.** The resolved coordinate is echoed on `DatasetInfo.coordinate`, so a
  run records the version it actually read rather than the name it asked for.

The default is a resolution, not a guess, and it refuses when it cannot be one:
if the declared versions first differ at a text segment — `v2` against `beta` —
no ordering of them means anything, so `AmbiguousRevision` names every declared
revision and asks for an explicit `revision=`. A silently picked version is not
a pinned one.
