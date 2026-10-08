"""revMD17 data source: MD17 trajectories recomputed at PBE/def2-SVP.

Reference:
    Christensen & von Lilienfeld, "On the role of gradients for machine
    learning of molecular energies and forces" MLST 2020.
    https://doi.org/10.1088/2632-2153/abba6f

Usage::

    from molhub.dataset import RevMD17Dataset

    source = RevMD17Dataset(data_dir, molecule="aspirin")
    frame = source[0]   # molpy Frame with atoms block + energy in frame.meta
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from molpy import Block, Frame

from molhub.dataset.hub import ArtifactHub
from molhub.dataset.protocol import TargetSchema
from molhub.molhub import Molhub

COORDINATE = "dataset:molcrafts/revmd17@v4"
"""Where revMD17 lives in the registry. Its manifest carries the locators and the
digests; this module holds no upstream URL of its own.

Upstream publishes each molecule as its own downloadable file, so the manifest
declares one role per molecule and a source fetches only the one it needs —
about 150 MB rather than the 1 GB archive."""

# Canonical 10 molecules of revMD17: the manifest role that serves each, and
# the filename upstream gives it (also the name expected in *root* offline).
_MOLECULES: dict[str, str] = {
    "aspirin": "rmd17_aspirin.npz",
    "azobenzene": "rmd17_azobenzene.npz",
    "benzene": "rmd17_benzene.npz",
    "ethanol": "rmd17_ethanol.npz",
    "malonaldehyde": "rmd17_malonaldehyde.npz",
    "naphthalene": "rmd17_naphthalene.npz",
    "paracetamol": "rmd17_paracetamol.npz",
    "salicylic": "rmd17_salicylic.npz",
    "toluene": "rmd17_toluene.npz",
    "uracil": "rmd17_uracil.npz",
}

_ELEMENT_SYMBOLS: dict[int, str] = {
    1: "H",
    6: "C",
    7: "N",
    8: "O",
}


class RevMD17Dataset:
    """Map-style dataset for the revised MD17 trajectories.

    Each sample is a :class:`molpy.Frame` with an ``atoms`` block
    (``element``, ``x``, ``y``, ``z``, ``number``, ``fx``, ``fy``, ``fz``)
    and ``energy`` in ``frame.meta``.

    Coordinates are in ångström, energies in kcal/mol and forces in
    kcal/(mol·Å), as distributed.

    Args:
        root: Directory holding a pre-downloaded NPZ file. Used only when
            *download* is ``False``; fetched files land in the shared cache.
        molecule: One of the 10 revMD17 molecule names (e.g. ``"aspirin"``).
        download: Fetch this molecule's file through the registry. Set to
            ``False`` in offline / test environments.
        hub: Anything satisfying :class:`~molhub.dataset.hub.ArtifactHub`.
            Defaults to a freshly constructed :class:`~molhub.molhub.Molhub`.

    Class attributes:
        TARGET_SCHEMA: :class:`TargetSchema` naming ``energy`` as graph-level
            and ``forces`` as atom-level.
    """

    TARGET_SCHEMA: TargetSchema = TargetSchema(
        graph_level=frozenset({"energy"}),
        atom_level=frozenset({"forces"}),
    )

    def __init__(
        self,
        root: str | Path,
        molecule: str = "aspirin",
        download: bool = True,
        *,
        hub: ArtifactHub | None = None,
    ) -> None:
        if molecule not in _MOLECULES:
            raise ValueError(
                f"Unknown revMD17 molecule '{molecule}'. Available: {sorted(_MOLECULES)}"
            )
        self.root = Path(root)
        self.molecule = molecule
        self.filename = _MOLECULES[molecule]
        self.filepath = self._locate(download, hub)

        data = np.load(self.filepath)
        for key in ("nuclear_charges", "coords", "energies", "forces"):
            if key not in data:
                raise KeyError(f"revMD17 file missing required key '{key}'")

        # nuclear_charges is the same for every frame
        self._charges = data["nuclear_charges"].astype(np.int64)
        self._coords = data["coords"]  # (n_frames, n_atoms, 3)
        self._energies = data["energies"].reshape(-1)  # (n_frames,)
        self._forces = data["forces"]  # (n_frames, n_atoms, 3)

        self._symbols = np.array(
            [_ELEMENT_SYMBOLS.get(int(z), "?") for z in self._charges],
            dtype="U3",
        )

    def _locate(self, download: bool, hub: ArtifactHub | None) -> Path:
        """Return the local path holding this molecule's NPZ.

        With *download*, the file comes from the registry: resolved by coordinate,
        transferred, and checked against the md5 Figshare publishes before it
        is usable. Without it, it must already sit in ``root`` under the name
        upstream gives it.

        Raises:
            FileNotFoundError: In offline mode, if the file is missing or empty.
        """
        if download:
            return (hub or Molhub()).fetch(COORDINATE, roles=[self.molecule])[self.molecule]

        path = self.root / self.filename
        # A zero-byte file counts as absent: that is what an interrupted
        # transfer leaves behind, and treating it as present makes the failure
        # permanent.
        if not (path.exists() and path.stat().st_size > 0):
            raise FileNotFoundError(
                f"revMD17 file not found at {path}. Set download=True to fetch "
                f"{COORDINATE} from the registry, or place the file there first."
            )
        return path

    @property
    def source_id(self) -> str:
        """A cache key for this exact view of the dataset.

        The coordinate names the whole dataset; a source reads one molecule of
        it, so the name is the coordinate plus a qualifier after a ``#``. That
        separator is deliberately not coordinate syntax — the result names a
        view, not an artifact, and should not pretend otherwise.
        """
        return f"{COORDINATE}#molecule={self.molecule}"

    def __len__(self) -> int:
        return int(self._coords.shape[0])

    def __getitem__(self, idx: int) -> Frame:
        coord = self._coords[idx]  # (natoms, 3)
        forces = self._forces[idx]  # (natoms, 3)

        atoms_blk = Block()
        atoms_blk["element"] = self._symbols
        atoms_blk["x"] = coord[:, 0].astype(np.float64)
        atoms_blk["y"] = coord[:, 1].astype(np.float64)
        atoms_blk["z"] = coord[:, 2].astype(np.float64)
        atoms_blk["number"] = self._charges
        atoms_blk["fx"] = forces[:, 0].astype(np.float64)
        atoms_blk["fy"] = forces[:, 1].astype(np.float64)
        atoms_blk["fz"] = forces[:, 2].astype(np.float64)

        return Frame({"atoms": atoms_blk}, meta={"energy": float(self._energies[idx])})
