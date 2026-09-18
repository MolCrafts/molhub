"""Dataset module — protocols and built-in dataset sources."""

from molhub.dataset.bonds import BondMargins, infer_bonds
from molhub.dataset.csv_dataset import CSVDataset
from molhub.dataset.definition import (
    DatasetManifest,
    Datasets,
    UnknownDataset,
    dataset,
)
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.neighbor import NeighborDelegate
from molhub.dataset.omol25 import (
    OMol25,
    OMol25Dataset,
    OMol25Lmdb,
    OMol25Small,
    OMol25SmallFilter,
)
from molhub.dataset.phalkethoh_mm import PhalkethohMMDataset
from molhub.dataset.protocol import (
    Dataset,
    InMemoryDataset,
    IterableDataset,
    SubsetDataset,
    TargetSchema,
    assignment,
)
from molhub.dataset.qm9 import QM9
from molhub.dataset.revmd17 import RevMD17Dataset
from molhub.dataset.statistic import Distrib, Field, StatisticMixin
from molhub.dataset.themol import (
    THEMolHessian,
    THEMolHessianRelax,
    THEMolMBIS,
    THEMolShardDataset,
    THEMolTorsionRelax,
    THEMolTorsionScan,
)
from molhub.dataset.threebpa import ThreeBPADataset
from molhub.dataset.transforms import AtomicDress, ConstantLabel, UnitConvert
from molhub.dataset.universal_class_i import (
    Class1Universal2026,
    CollectionRole,
    MultiSourceDatasetCollection,
)
from molhub.dataset.water_les import WaterLESDataset
from molhub.dataset.zinc_typing import ZincTypingDataset


# MolRecDataset imports molpy.io.mrec. Keep that off the package import
# graph so ProcessPool workers that pickle OMol25Lmdb helpers do not need
# molrec at import time.
def __getattr__(name: str):
    if name == "MolRecDataset":
        from molhub.dataset.molrec import MolRecDataset as _MolRecDataset

        return _MolRecDataset
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


ThreeBPA = ThreeBPADataset
MBIS = THEMolMBIS
Hessian = THEMolHessian
TorsionScan = THEMolTorsionScan

__all__ = [
    "dataset",
    "DatasetManifest",
    "Datasets",
    "UnknownDataset",
    "ArtifactHub",
    "Dataset",
    "IterableDataset",
    "TargetSchema",
    "InMemoryDataset",
    "SubsetDataset",
    "Distrib",
    "Field",
    "StatisticMixin",
    "assignment",
    "CSVDataset",
    "QM9",
    "RevMD17Dataset",
    "ThreeBPA",
    "ThreeBPADataset",
    "ZincTypingDataset",
    "PhalkethohMMDataset",
    "WaterLESDataset",
    "MolRecDataset",
    "AtomicDress",
    "UnitConvert",
    "ConstantLabel",
    "NeighborDelegate",
    "OMol25",
    "OMol25Dataset",
    "OMol25Lmdb",
    "OMol25Small",
    "OMol25SmallFilter",
    "BondMargins",
    "infer_bonds",
    "THEMolShardDataset",
    "THEMolHessian",
    "THEMolHessianRelax",
    "THEMolTorsionScan",
    "THEMolTorsionRelax",
    "THEMolMBIS",
    "MBIS",
    "Hessian",
    "TorsionScan",
    "CollectionRole",
    "MultiSourceDatasetCollection",
    "Class1Universal2026",
]
