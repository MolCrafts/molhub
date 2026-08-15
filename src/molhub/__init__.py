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
re-exported here. This module is the front door, not a place work is written.
"""

from molhub._version import __version__
from molhub.coordinate import Coordinate, InvalidCoordinate
from molhub.loader import (
    DatasetBuilder,
    DatasetInfo,
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
