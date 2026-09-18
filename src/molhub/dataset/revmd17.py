"""revMD17 dataset: MD17 trajectories recomputed at PBE/def2-SVP.

Labels keep the published native units — energy kcal/mol, forces
kcal/(mol·Å), positions Å — exactly as distributed. molhub never converts
units; consumers convert (e.g. :class:`~molhub.dataset.transforms.UnitConvert`).

Reference:
    Christensen & von Lilienfeld, "On the role of gradients for machine
    learning of molecular energies and forces" MLST 2020.
    https://doi.org/10.1088/2632-2153/abba6f

Usage::

    from molhub.dataset import RevMD17Dataset

    ds = RevMD17Dataset(data_dir, molecule="aspirin").load()
    frame = ds[0]   # molpy Frame with atoms block + energy in frame.meta
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
from molpy import Block, Element, Frame

from molhub.coordinate import Coordinate
from molhub.dataset.definition import dataset
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.protocol import Dataset, TargetSchema
from molhub.dataset.statistic import StatisticMixin
from molhub.manifest import Artifact, Manifest, TargetDeclaration
from molhub.molhub import Molhub
from molhub.sources import Digest, Locator

COORDINATE = "dataset:molcrafts/revmd17@v4"
"""Where revMD17 lives in the catalog. Locators live on :data:`MANIFEST`.

Upstream publishes each molecule as its own downloadable file, so the manifest
declares one role per molecule and a source fetches only the one it needs —
about 150 MB rather than the 1 GB archive."""

_REVMD17_FILES: tuple[tuple[str, str, str, int], ...] = (
    ("aspirin", "rmd17_aspirin.npz", "md5:17fd6fb69066888613f7e16b358a7553", 153_601_803),
    ("azobenzene", "rmd17_azobenzene.npz", "md5:be79df918468eb3579aa73a0becf7390", 175_180_782),
    ("benzene", "rmd17_benzene.npz", "md5:18c9242bc90fbf28215f6dd81e650f16", 88_801_794),
    ("ethanol", "rmd17_ethanol.npz", "md5:eb837fb8deb27d4e0d52f71a03aff776", 67_201_791),
    (
        "malonaldehyde",
        "rmd17_malonaldehyde.npz",
        "md5:cdc1d70c0c34062ddde6e5071eb6fe21",
        67_201_791,
    ),
    ("naphthalene", "rmd17_naphthalene.npz", "md5:0efba19c9907e3852318b1e6008b3b9e", 132_001_800),
    ("paracetamol", "rmd17_paracetamol.npz", "md5:ba10784f7b67635427085f6d7ec2dd97", 146_401_802),
    ("salicylic", "rmd17_salicylic.npz", "md5:900fedf242da438400fa4293348d7dd1", 117_601_798),
    ("toluene", "rmd17_toluene.npz", "md5:0f2913d51f8149c90ab28d697a076f64", 110_401_797),
    ("uracil", "rmd17_uracil.npz", "md5:992a4479c28a07e0cce6da964805be31", 88_801_794),
    ("readme", "readme.txt", "md5:29e6f250bb2d1c461363e24955b5be1e", 2_082),
)

MANIFEST = Manifest(
    coordinate=Coordinate.parse(COORDINATE),
    title="revMD17 — MD17 trajectories recomputed at PBE/def2-SVP",
    description=(
        "100,000 configurations for each of ten small organic molecules, taken from "
        "the original MD17 trajectories and recomputed at the PBE/def2-SVP level with "
        "tight SCF convergence and a dense integration grid, so the labels are "
        "practically free of numerical noise. Energies are in kcal/mol and forces in "
        "kcal/mol/angstrom. Azobenzene carries 99,988 configurations -- 11 DFT "
        "calculations failed on van der Waals clashes and the original trajectory held "
        "99,999. The structures are consecutive MD samples and are not independent; "
        "upstream warns against training on more than 1,000 of them."
    ),
    license="CC0-1.0",
    doi="10.6084/m9.figshare.12672038.v4",
    artifacts={
        role: Artifact(
            role=role,
            filename=filename,
            locators=(Locator.parse(f"figshare://12672038/v4/{filename}"),),
            digest=Digest.parse(digest),
            size=size,
        )
        for role, filename, digest, size in _REVMD17_FILES
    },
    targets=TargetDeclaration(graph_level=("energy",), atom_level=("forces",)),
)

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


@dataset(
    name="revmd17",
    namespace="molcrafts",
    version="v4",
    description="MD17 trajectories recomputed at PBE/def2-SVP, near noise-free labels.",
    license="CC0-1.0",
    citation="10.1088/2632-2153/abba6f",
    tags=("md17", "energy", "forces", "dft", "trajectory"),
    # Native pass-through, as published on Figshare: kcal/mol energies,
    # kcal/(mol·Å) forces. Rescaling is UnitConvert's job, opted into by name.
    units={"energy": "kcal/mol", "forces": "kcal/mol/angstrom"},
)
class RevMD17Dataset(Dataset, StatisticMixin):
    """Map-style dataset for one revised-MD17 molecule.

    Construction does no IO. :meth:`load` is the fetch-and-parse boundary;
    after it, each sample is a :class:`molpy.Frame` with an ``atoms`` block
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

    Raises:
        ValueError: *molecule* is not one of the 10 revMD17 names.

    Class attributes:
        COORDINATE: The pinned registry coordinate.
        TARGET_SCHEMA: :class:`TargetSchema` naming ``energy`` as graph-level
            and ``forces`` as atom-level.
    """

    COORDINATE = COORDINATE
    TARGET_SCHEMA: TargetSchema = TargetSchema(
        graph_level=frozenset({"energy"}),
        atom_level=frozenset({"forces"}),
    )

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        molecule: str = "aspirin",
        download: bool = True,
        hub: ArtifactHub | None = None,
    ) -> None:
        if molecule not in _MOLECULES:
            raise ValueError(
                f"Unknown revMD17 molecule '{molecule}'. Available: {sorted(_MOLECULES)}"
            )
        self.root = Path(root) if root is not None else None
        self.molecule = molecule
        self.filename = _MOLECULES[molecule]
        self._download = download
        self._hub = hub
        self.filepath: Path | None = None
        self._charges: np.ndarray | None = None
        self._symbols: np.ndarray | None = None
        self._coords: np.ndarray | None = None
        self._energies: np.ndarray | None = None
        self._forces: np.ndarray | None = None

    def load(self) -> RevMD17Dataset:
        """Locate or fetch this molecule's NPZ and materialise its arrays.

        Idempotent: a second call returns immediately.

        Returns:
            This dataset, now indexable.

        Raises:
            FileNotFoundError: Offline mode and the file is missing or empty.
            KeyError: The NPZ lacks a required array.
        """
        if self._coords is not None:
            return self
        self.filepath = self._locate()
        data = np.load(self.filepath)
        for key in ("nuclear_charges", "coords", "energies", "forces"):
            if key not in data:
                raise KeyError(f"revMD17 file missing required key '{key}'")

        # nuclear_charges is the same for every frame
        self._charges = data["nuclear_charges"].astype(np.int64)
        self._energies = data["energies"].reshape(-1)  # (n_frames,)
        self._forces = data["forces"]  # (n_frames, n_atoms, 3)
        self._symbols = np.array(
            [Element(int(z)).symbol for z in self._charges],
            dtype="U3",
        )
        self._coords = data["coords"]  # (n_frames, n_atoms, 3)
        return self

    def _locate(self) -> Path:
        """Return the local path holding this molecule's NPZ.

        With ``download``, the file comes from the registry: resolved by
        coordinate, transferred, and checked against the md5 Figshare
        publishes before it is usable. Without it, it must already sit in
        ``root`` under the name upstream gives it.

        Raises:
            FileNotFoundError: In offline mode, if the file is missing or empty.
        """
        if self._download:
            hub = self._hub if self._hub is not None else Molhub()
            return hub.fetch(COORDINATE, roles=[self.molecule])[self.molecule]

        path = (self.root or Path()) / self.filename
        # A zero-byte file counts as absent: that is what an interrupted
        # transfer leaves behind, and treating it as present makes the failure
        # permanent.
        if not (path.exists() and path.stat().st_size > 0):
            raise FileNotFoundError(
                f"revMD17 file not found at {path}. Set download=True to fetch "
                f"{COORDINATE} from the registry, or place the file there first."
            )
        return path

    def _require_loaded(self) -> None:
        if self._coords is None:
            raise RuntimeError(
                "RevMD17Dataset: call load() before indexing; construction does no IO."
            )

    @property
    def source_id(self) -> str:
        """A cache key for this exact view of the dataset.

        The coordinate names the whole dataset; this class reads one molecule
        of it, so the name is the coordinate plus a qualifier after a ``#``.
        That separator is deliberately not coordinate syntax — the result
        names a view, not an artifact, and should not pretend otherwise.
        """
        return f"{COORDINATE}#molecule={self.molecule}"

    def __len__(self) -> int:
        self._require_loaded()
        assert self._coords is not None
        return int(self._coords.shape[0])

    def __getitem__(self, idx: int) -> Sequence[Frame]:
        self._require_loaded()
        assert self._coords is not None
        assert self._forces is not None and self._energies is not None
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
        frame.meta = {"energy": float(self._energies[idx])}
        return (frame,)
