"""LAMALAB curated polymer glass-transition temperatures.

No dedicated reader: consume with :class:`~molhub.dataset.csv_dataset.CSVDataset`
after :func:`molhub.fetch`.
"""

from __future__ import annotations

from molhub.coordinate import Coordinate
from molhub.manifest import Artifact, Manifest, TargetDeclaration
from molhub.sources import Digest, Locator

COORDINATE = "dataset:molcrafts/polymer-tg@1"

MANIFEST = Manifest(
    coordinate=Coordinate.parse(COORDINATE),
    title="LAMALAB curated polymer glass-transition temperatures",
    description=(
        "Experimentally measured glass-transition temperatures for polymers, "
        "given as PSMILES plus Tg in kelvin, curated by LAMALAB."
    ),
    license="CC-BY-4.0",
    doi="10.5281/zenodo.14980914",
    artifacts={
        "main": Artifact(
            role="main",
            filename="LAMALAB_CURATED_Tg_structured.csv",
            locators=(Locator.parse("zenodo://14980914/LAMALAB_CURATED_Tg_structured.csv"),),
            digest=Digest.parse("md5:ce2c7b2a879450cbbfff4d7ccea648f9"),
            size=6_024_335,
        )
    },
    targets=TargetDeclaration(graph_level=("labels.Exp_Tg(K)",), atom_level=()),
)
