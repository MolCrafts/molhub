"""LAMALAB curated polymer glass-transition temperatures (PolyMetriX).

One coordinate per Zenodo version of concept DOI ``10.5281/zenodo.14980913``.
The version label is Zenodo's own (``v1`` through ``v7``). The files are not
successive cuts of one table, so a caller names the version; nothing here
picks a default.

No dedicated reader: consume with :class:`~molhub.dataset.csv_dataset.CSVDataset`
after :func:`molhub.fetch`.

The digest and size on each manifest are the values Zenodo publishes. molhub
does not compute either.
"""

from __future__ import annotations

from molhub.coordinate import Coordinate
from molhub.manifest import Artifact, Manifest, TargetDeclaration
from molhub.sources import Digest, Locator

# version, record id, filename, digest, size, what this record adds
_RELEASES: tuple[tuple[str, str, str, str, int, str], ...] = (
    (
        "v1",
        "14980914",
        "LAMALAB_CURATED_Tg_structured.csv",
        "md5:ce2c7b2a879450cbbfff4d7ccea648f9",
        6_024_335,
        "Zenodo v1: PSMILES and experimental Tg.",
    ),
    (
        "v2",
        "15209940",
        "LAMALAB_CURATED_Tg_structured_polymerclass.csv",
        "md5:833ca70192089b0613b3292394b91c57",
        5_296_460,
        "Zenodo v2: adds polymer-class columns.",
    ),
    (
        "v3",
        "15210011",
        "LAMALAB_CURATED_Tg_structured.csv",
        "md5:833ca70192089b0613b3292394b91c57",
        5_296_460,
        "Zenodo v3: structured table republished as its own record. "
        "Same checksum as v2, different filename.",
    ),
    (
        "v4",
        "15210035",
        "LAMALAB_CURATED_Tg_structured_polymerclass.csv",
        "md5:833ca70192089b0613b3292394b91c57",
        5_296_460,
        "Zenodo v4: polymer-class table, same checksum as v2. "
        "PolyMetriX CuratedGlassTempDataset downloads this record.",
    ),
    (
        "v5",
        "15781175",
        "LAMALAB_CURATED_Tg_structured_polymerclass_with_embeddings.csv",
        "md5:31400a5f499394e3a6e0658488a464bb",
        43_615_282,
        "Zenodo v5: polymer class, side-chain, backbone and full-polymer "
        "features, plus PSMILES and BIGSMILES embeddings.",
    ),
    (
        "v6",
        "15783761",
        "LAMALAB_CURATED_Tg_structured_polymerclass_with_embeddings.csv",
        "md5:31400a5f499394e3a6e0658488a464bb",
        43_615_282,
        "Zenodo v6: same embedding file and checksum as v5, published as its own record.",
    ),
    (
        "v7",
        "15789599",
        "LAMALAB_CURATED_Tg_structured_polymerclass_with_embeddings.csv",
        "md5:31400a5f499394e3a6e0658488a464bb",
        43_615_282,
        "Zenodo v7, the current record. Same embedding file and checksum as v5.",
    ),
)

_TITLE = "LAMALAB curated polymer glass-transition temperatures"
_LEAD = (
    "Experimentally measured glass-transition temperatures for polymers, "
    "given as PSMILES plus Tg in kelvin, curated by LAMALAB for PolyMetriX. "
)


def _manifest(
    version: str, record: str, filename: str, digest: str, size: int, note: str
) -> Manifest:
    return Manifest(
        coordinate=Coordinate.parse(f"dataset:molcrafts/polymer-tg@{version}"),
        title=_TITLE,
        description=_LEAD + note,
        license="CC-BY-4.0",
        doi=f"10.5281/zenodo.{record}",
        artifacts={
            "main": Artifact(
                role="main",
                filename=filename,
                format="psmiles-csv",
                media_type="text/csv",
                locators=(Locator.parse(f"zenodo://{record}/{filename}"),),
                digest=Digest.parse(digest),
                size=size,
            )
        },
        targets=TargetDeclaration(graph_level=("labels.Exp_Tg(K)",), atom_level=()),
    )


MANIFESTS: tuple[Manifest, ...] = tuple(_manifest(*release) for release in _RELEASES)
