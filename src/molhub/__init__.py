"""MolHub — unified addressing and verified fetching for molecular artifacts.

Datasets, models, and plugins share one stable coordinate syntax, one registry,
and one transfer layer that never leaves a half-written or wrong-status response
at the path it hands you::

    from molhub import Molhub

    hub = Molhub()
    paths = hub.fetch("dataset:molcrafts/qm9@v2")

For datasets there is a second, higher door in HuggingFace spelling::

    from molhub import load_dataset, load_dataset_builder, prepare

    load_dataset_builder("themol/mbis").info      # content, before any bytes
    load_dataset("themol/mbis", split="train")    # one split, map-style
    load_dataset("themol/mbis", split="train", streaming=True)   # …a file at a time
    prepare("themol/torsion-scan", split="train", output_dir="blocks/")  # …as blocks

Layers, each usable on its own:

* :mod:`molhub.sources` — locators, drivers, digests, and the on-disk cache
  keyed by coordinate and role. Bytes only; knows nothing about molecules.
* :mod:`molhub.registry` / :mod:`molhub.manifest` — the registry that turns a
  coordinate into an ordered list of locators, plus whatever digest the
  publishing platform declared.
* :mod:`molhub.dataset` — molpy ``Frame`` views over fetched bytes.
* :mod:`molhub.loader` — the dataset functions above, and the builder, walk and
  export types behind them.

All three dataset functions are defined in :mod:`molhub.loader` — the two
reading ones in its ``__init__``, :func:`~molhub.loader.materialize.prepare`
beside the :class:`~molhub.loader.materialize.BlockExport` it delegates to — and
re-exported here. So is everything those three promise a caller will be able to
**name**:

* the refusals a script writes ``except`` against —
  :class:`~molhub.loader.errors.SplitTableUnavailable` (build the split
  derivation with ``python -m molhub.scripts.build_class1_splits``),
  :class:`~molhub.loader.errors.UnknownSplit` (ask
  ``load_dataset_builder(name).info.splits`` what the names are),
  :class:`~molhub.loader.naming.AmbiguousRevision`,
  :class:`~molhub.loader.mapstyle.UnknownRecordKey`,
  :class:`~molhub.conveyor.errors.UnsupportedRecordError`,
  :class:`~molhub.conveyor.errors.UnroutableUnitError`,
  :class:`~molhub.conveyor.splits.SplitProvenanceMismatch` and
  :class:`~molhub.sources.errors.AllLocatorsFailed` (every mirror of a published
  file is down — the one failure here that is nobody's bug, and the one a script
  retries or reports rather than debugs);
* the records they hand back and a caller annotates or ``isinstance``-checks —
  :class:`~molhub.conveyor.prepare.PreparedBlocks`,
  :class:`~molhub.loader.info.Feature` and
  :class:`~molhub.loader.info.SplitInfo`.

Each is the same object the defining module holds: catching
``molhub.UnroutableUnitError`` catches what the layer underneath actually
raised. Reaching them any other way means importing a private layering detail
this front door exists to hide. This module is the front door, not a place work
is written.
"""

from molhub._version import __version__
from molhub.coordinate import Coordinate, InvalidCoordinate
from molhub.loader import (
    AllLocatorsFailed,
    AmbiguousRevision,
    DatasetBuilder,
    DatasetInfo,
    Feature,
    PreparedBlocks,
    SplitInfo,
    SplitProvenanceMismatch,
    SplitTableUnavailable,
    UnknownRecordKey,
    UnknownSplit,
    UnroutableUnitError,
    UnsupportedRecordError,
    load_dataset,
    load_dataset_builder,
    prepare,
)
from molhub.manifest import Artifact, InvalidManifest, Manifest, TargetDeclaration
from molhub.molhub import Molhub
from molhub.registry import Registry, RegistrySource, UnknownArtifact

__all__ = [
    "__version__",
    "load_dataset",
    "load_dataset_builder",
    "prepare",
    "DatasetBuilder",
    "DatasetInfo",
    "Feature",
    "SplitInfo",
    "PreparedBlocks",
    "AllLocatorsFailed",
    "AmbiguousRevision",
    "SplitProvenanceMismatch",
    "SplitTableUnavailable",
    "UnknownRecordKey",
    "UnknownSplit",
    "UnroutableUnitError",
    "UnsupportedRecordError",
    "Molhub",
    "Coordinate",
    "InvalidCoordinate",
    "Manifest",
    "Artifact",
    "TargetDeclaration",
    "InvalidManifest",
    "Registry",
    "RegistrySource",
    "UnknownArtifact",
]
