"""revMD17 DataSource: revised MD17 molecular dynamics trajectories.

Reference:
    Christensen & von Lilienfeld, "On the role of gradients for machine
    learning of molecular energies and forces" MLST 2020.
    https://doi.org/10.1088/2632-2153/abba6f

Usage::

    from molhub.dataset import RevMD17Source

    source = RevMD17Source(data_dir, molecule="aspirin")
    frame = source[0]   # molpy Frame with atoms block + energy in metadata
"""

from __future__ import annotations

import ssl
from pathlib import Path

import numpy as np
from molpy.core.frame import Block, Frame

from molhub.dataset.protocol import TargetSchema

ssl._create_default_https_context = ssl._create_unverified_context  # type: ignore[assignment]

# Canonical 10 molecules of revMD17 and their filenames on the mirror.
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


class RevMD17Source:
    """Map-style dataset for the revised MD17 trajectories.

    Each sample is a :class:`molpy.core.frame.Frame` with an ``atoms`` block
    (``element``, ``x``, ``y``, ``z``, ``number``, ``fx``, ``fy``, ``fz``)
    and ``energy`` in ``frame.metadata``.

    Energies are in kcal/mol and forces in kcal/(mol·Å) as distributed.

    Args:
        root: Directory for the downloaded NPZ file.
        molecule: One of the 10 revMD17 molecule names (e.g. ``"aspirin"``).
        download: Download the file if it does not exist.
    """

    BASE_URL = "https://figshare.com/ndownloader/files/23950376"

    TARGET_SCHEMA: TargetSchema = TargetSchema(
        graph_level=frozenset({"energy"}),
        atom_level=frozenset({"forces"}),
    )

    def __init__(
        self,
        root: str | Path,
        molecule: str = "aspirin",
        download: bool = True,
    ) -> None:
        if molecule not in _MOLECULES:
            raise ValueError(
                f"Unknown revMD17 molecule '{molecule}'. "
                f"Available: {sorted(_MOLECULES)}"
            )
        self.root = Path(root)
        self.molecule = molecule
        self.filename = _MOLECULES[molecule]
        self.filepath = self.root / self.filename
        self.root.mkdir(parents=True, exist_ok=True)

        if download and not self.filepath.exists():
            raise FileNotFoundError(
                f"revMD17 file not found at {self.filepath}. "
                f"Download the archive from {self.BASE_URL} and extract "
                f"{self.filename} into {self.root}."
            )
        if not self.filepath.exists():
            raise FileNotFoundError(f"revMD17 file missing: {self.filepath}")

        data = np.load(self.filepath)
        for key in ("nuclear_charges", "coords", "energies", "forces"):
            if key not in data:
                raise KeyError(f"revMD17 file missing required key '{key}'")

        # nuclear_charges is the same for every frame
        self._charges = data["nuclear_charges"].astype(np.int64)
        self._coords = data["coords"]  # (n_frames, n_atoms, 3)
        self._energies = data["energies"].reshape(-1)  # (n_frames,)
        self._forces = data["forces"]  # (n_frames, n_atoms, 3)

        symbols = np.array(
            [_ELEMENT_SYMBOLS.get(int(z), "?") for z in self._charges],
            dtype="U3",
        )

        self._symbols = symbols
        self._z = self._charges

    @property
    def source_id(self) -> str:
        size = self.filepath.stat().st_size
        return f"revmd17:{self.molecule}:size={size}:n={len(self)}"

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

        frame = Frame()
        frame["atoms"] = atoms_blk
        frame.metadata["energy"] = float(self._energies[idx])
        return frame
