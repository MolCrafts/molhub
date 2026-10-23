"""An mrec collection stored in HDF5, as a map-style dataset.

The file is an :class:`~molhub.io.hdf5.Hdf5`. The records are
:class:`~molhub.io.mrec.MrecRecords`. This class is the dataset protocol over
that pair. It does not subclass :class:`~molhub.dataset.lmdb.LmdbDataset`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from molpy import Frame

from molhub.dataset.collection import target_units
from molhub.dataset.prefetch import Prefetch
from molhub.dataset.protocol import Dataset
from molhub.io.hdf5 import Hdf5
from molhub.io.mrec import MrecRecords

__all__ = ["Hdf5Dataset"]


class Hdf5Dataset(Prefetch, Dataset):
    """One mrec HDF5 file, one record per index.

    Args:
        path: The collection file.

    Example::

        ds = Hdf5Dataset(path)
        frames = ds[0]
    """

    counted_tables = {"atoms": "atoms_per_record"}

    def __init__(self, path: str | Path) -> None:
        self._records = MrecRecords(Hdf5(path))

    @property
    def path(self) -> Path:
        return self._records.path

    @property
    def units(self) -> dict[str, str]:
        """The collection's quantity -> unit map."""
        return self._records.units

    @property
    def source_id(self) -> str:
        """The identity the collection states, else the file's own path."""
        stated = self._records.collection_meta.get("source_id")
        return str(stated) if stated else f"file:{self.path}"

    @property
    def manifest(self) -> Any:
        """A dataset manifest when the collection names its coordinate."""
        from molhub.coordinate import Coordinate
        from molhub.dataset.definition import DatasetManifest

        coordinate = self._records.collection_meta.get("coordinate")
        if not coordinate:
            return None
        return DatasetManifest(
            coordinate=Coordinate.parse(str(coordinate)), units=target_units(self.units)
        )

    @property
    def index(self) -> dict[str, np.ndarray]:
        """Binding columns and the writer's own."""
        return self._records.index

    @property
    def atoms_per_record(self) -> np.ndarray:
        """Atom rows each record contributes: ``n_atoms × max(n_frames, 1)``."""
        return self._records.atoms_per_record()

    def __len__(self) -> int:
        return len(self._records)

    def stage(self, index: int) -> Any:
        """Copy record *index* off disk. No molpy frames."""
        return self._records.stage(int(index))

    def realize(self, staged: Any) -> tuple[Frame, ...]:
        """Build the frames for what :meth:`stage` returned."""
        return self._records.realize(staged)

    def __getitem__(self, index: int, /) -> tuple[Frame, ...]:
        return self.realize(self.stage(index))

    def keys(self) -> tuple[str, ...]:
        """Each record's identifier: the index ``record_id`` column, else its position."""
        return self._records.keys()

    def molecule_index(self) -> np.ndarray:
        """Dense molecule code per record, from the index ``molecule`` column."""
        return self._records.molecule_index()

    def element_mask(self) -> np.ndarray:
        """Bit ``Z`` set for each element a record carries, from the index."""
        return self._records.element_mask()

    def close(self) -> None:
        self._records.close()
