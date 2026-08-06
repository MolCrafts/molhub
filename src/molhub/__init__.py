"""MolHub — unified addressing and verified fetching for molecular artifacts.

Datasets, models, and plugins share one stable coordinate syntax, one catalogue,
and one transfer layer that refuses to hand you bytes it has not verified::

    from molhub import Molhub

    hub = Molhub()
    paths = hub.fetch("dataset:molcrafts/qm9@v2")

Layers, each usable on its own:

* :mod:`molhub.registry` — locators, drivers, digests, the content-addressed
  cache. Bytes only; knows nothing about molecules or coordinates.
* :mod:`molhub.index` / :mod:`molhub.manifest` — the catalogue that turns a
  coordinate into locators plus a digest.
* :mod:`molhub.dataset` — molpy ``Frame`` views over fetched bytes.
"""

from molhub._version import __version__
from molhub.coordinate import Coordinate, InvalidCoordinate
from molhub.index import Index, IndexSource, UnknownArtifact
from molhub.manifest import Artifact, InvalidManifest, Manifest, TargetDeclaration
from molhub.molhub import Molhub

__all__ = [
    "__version__",
    "Molhub",
    "Coordinate",
    "InvalidCoordinate",
    "Manifest",
    "Artifact",
    "TargetDeclaration",
    "InvalidManifest",
    "Index",
    "IndexSource",
    "UnknownArtifact",
]
