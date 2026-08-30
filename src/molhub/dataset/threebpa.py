"""3BPA data source: the temperature-transferability benchmark for MLPs.

Reference:
    Kovacs et al., "Linear Atomic Cluster Expansion Force Fields for
    Organic Molecules: Beyond RMSE" J. Chem. Theory Comput. 2021.
    https://doi.org/10.1021/acs.jctc.1c00647

3BPA = 3-(benzyloxy)pyridin-2-amine (C13H14N2O). The benchmark ships four
extended-XYZ files, which this source calls *splits* and the manifest files
under the same names as *roles*:

  * ``train_300K``   — 500 structures sampled at 300 K (training pool).
  * ``test_300K``    — held-out 300 K structures (in-distribution).
  * ``test_600K``    — held-out 600 K  (temperature extrapolation).
  * ``test_1200K``   — held-out 1200 K (harder extrapolation).

Usage::

    from molhub.dataset import ThreeBPADataset

    # Retrieved by coordinate, verified, and cached.
    train = ThreeBPADataset("train_300K.xyz", tag="train_300K")

    # Or read from a file already on disk.
    test = ThreeBPADataset(data_dir / "test_600K.xyz", tag="test_600K")
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from molpy import Block, Element, Frame

from molhub.coordinate import Coordinate
from molhub.dataset.definition import dataset
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.protocol import FrameCollection, TargetSchema
from molhub.manifest import Artifact, Manifest, TargetDeclaration
from molhub.molhub import Molhub
from molhub.sources import Locator

COORDINATE = "dataset:molcrafts/3bpa@v1"
"""Where 3BPA lives in the catalog. Locators live on :data:`MANIFEST`."""

_BOTNET_COMMIT = "29e6d467317e4b5967b7ea5cbee54de953fa0d45"
_BOTNET_DIR = (
    f"https://raw.githubusercontent.com/davkovacs/BOTNet-datasets/{_BOTNET_COMMIT}/dataset_3BPA"
)

MANIFEST = Manifest(
    coordinate=Coordinate.parse(COORDINATE),
    title="3BPA — temperature-transferability benchmark for machine-learned potentials",
    description=(
        "DFT energies and forces for 3-(benzyloxy)pyridin-2-amine (C13H14N2O), a large "
        "flexible drug-like molecule. 500 training geometries sampled from 300 K "
        "molecular dynamics, plus held-out sets sampled at 300 K, 600 K and 1200 K, so "
        "a potential fitted in-domain can be scored well out of it. Distances in "
        "angstrom, energies in eV, forces in eV/angstrom."
    ),
    license="MIT",
    doi="10.1021/acs.jctc.1c00647",
    artifacts={
        role: Artifact(
            role=role,
            filename=f"{role}.xyz",
            locators=(Locator.parse(f"{_BOTNET_DIR}/{role}.xyz"),),
            size=size,
        )
        for role, size in (
            ("train_300K", 1_504_880),
            ("test_300K", 5_023_260),
            ("test_600K", 6_434_399),
            ("test_1200K", 6_437_539),
        )
    },
    targets=TargetDeclaration(graph_level=("energy",), atom_level=("forces",)),
)

# The manifest declares one role per benchmark file, and a source's tag selects
# among them. Keeping the two spelled identically is what lets `tag` double as
# the fetch key.
_SPLITS: frozenset[str] = frozenset({"train_300K", "test_300K", "test_600K", "test_1200K"})


def _parse_extxyz(path: Path) -> list[Frame]:
    """Parse an extended-XYZ file shipped with the 3BPA benchmark."""
    frames: list[Frame] = []
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines):
        natoms = int(lines[i].strip())
        comment = lines[i + 1]
        energy: float | None = None
        for tok in comment.split():
            if tok.startswith("energy="):
                energy = float(tok.split("=", 1)[1])
                break
        if energy is None:
            raise ValueError(f"Missing 'energy=...' tag in {path} at structure {len(frames)}")

        symbols: list[str] = []
        xs: list[float] = []
        ys: list[float] = []
        zs: list[float] = []
        fxs: list[float] = []
        fys: list[float] = []
        fzs: list[float] = []

        for row in lines[i + 2 : i + 2 + natoms]:
            parts = row.split()
            symbols.append(parts[0])
            xs.append(float(parts[1]))
            ys.append(float(parts[2]))
            zs.append(float(parts[3]))
            fxs.append(float(parts[4]))
            fys.append(float(parts[5]))
            fzs.append(float(parts[6]))

        numbers = [Element.get_atomic_number(s) for s in symbols]

        atoms_blk = Block()
        atoms_blk["element"] = np.array(symbols, dtype="U3")
        atoms_blk["x"] = np.array(xs, dtype=np.float64)
        atoms_blk["y"] = np.array(ys, dtype=np.float64)
        atoms_blk["z"] = np.array(zs, dtype=np.float64)
        atoms_blk["number"] = np.array(numbers, dtype=np.int64)
        atoms_blk["fx"] = np.array(fxs, dtype=np.float64)
        atoms_blk["fy"] = np.array(fys, dtype=np.float64)
        atoms_blk["fz"] = np.array(fzs, dtype=np.float64)

        frame = Frame()
        frame["atoms"] = atoms_blk
        frame.meta.update({"energy": energy})
        frames.append(frame)

        i += 2 + natoms
    return frames


@dataset(
    name="3bpa",
    namespace="molcrafts",
    version="v1",
    description=(
        "DFT energies and forces for 3-(benzyloxy)pyridin-2-amine (C13H14N2O), "
        "sampled at 300 K, 600 K and 1200 K."
    ),
    license="MIT",
    citation="10.1021/acs.jctc.1c00647",
    tags=("benchmark", "energy", "forces", "dft"),
    # As distributed: the registry description for this coordinate says
    # "energies in eV, forces in eV/angstrom", and the reader rescales nothing.
    # ASCII and solidus-composed, like every other declared unit here, because
    # `molhub.dataset.transforms.UnitConvert` parses these strings back through
    # the molpy unit registry, which knows `angstrom` and not `Å`.
    units={"energy": "eV", "forces": "eV/angstrom"},
)
class ThreeBPADataset:
    """Map-style dataset for one 3BPA extended-XYZ split.

    Each sample is a :class:`molpy.Frame` with an ``atoms`` block
    (``element``, ``x``, ``y``, ``z``, ``number``, ``fx``, ``fy``, ``fz``)
    and ``energy`` in ``frame.meta``.

    Args:
        path: Path to the ``.xyz`` file. When nothing usable is there, the
            split named by *tag* is retrieved through the registry instead and
            *path* is ignored — the bytes land in the shared cache, not here.
        tag: Which split this is. One of :attr:`SPLITS` to be retrievable;
            any other value names a file the caller supplies themselves.
        hub: Anything satisfying :class:`~molhub.dataset.hub.ArtifactHub`.
            Defaults to a freshly constructed :class:`~molhub.molhub.Molhub`.

    Class attributes:
        SPLITS: The four splits the benchmark ships, each also a role in the
            manifest at :data:`COORDINATE`.
        TARGET_SCHEMA: :class:`TargetSchema` for the energy and forces every
            structure carries.
    """

    SPLITS: frozenset[str] = _SPLITS
    TARGET_SCHEMA: TargetSchema = TargetSchema(
        graph_level=frozenset({"energy"}),
        atom_level=frozenset({"forces"}),
    )

    def __init__(self, path: str | Path, *, tag: str, hub: ArtifactHub | None = None) -> None:
        self.tag = tag
        self.path = self._locate(Path(path), hub)
        self._frames = _parse_extxyz(self.path)

    def _locate(self, path: Path, hub: ArtifactHub | None) -> Path:
        """Return the file to parse, retrieving it when *path* holds nothing.

        A zero-byte file counts as absent: that is what an interrupted download
        leaves behind, and parsing it yields an empty dataset rather than an
        error.

        Raises:
            FileNotFoundError: If *path* holds nothing and *tag* does not name
                a split the registry can be asked for.
        """
        if path.is_file() and path.stat().st_size > 0:
            return path
        if self.tag not in _SPLITS:
            raise FileNotFoundError(
                f"3BPA file not found: {path}, and tag {self.tag!r} is not one of "
                f"the 3BPA splits, so it cannot be retrieved from {COORDINATE}. "
                f"Available splits: {', '.join(sorted(_SPLITS))}."
            )
        return (hub or Molhub()).fetch(COORDINATE, roles=[self.tag])[self.tag]

    @property
    def source_id(self) -> str:
        """A cache key for this exact view of the dataset.

        The coordinate names the benchmark as a whole — all four files are one
        artifact, since that is how upstream publishes them and how a user
        thinks about it. One source is one split of that artifact, so the split
        is always a qualifier, appended after a ``#``. That separator is
        deliberately not part of coordinate syntax: what follows names a view,
        not an artifact, and should not pretend otherwise. Everything before it
        round-trips through :meth:`Coordinate.parse`.
        """
        return f"{COORDINATE}#split={self.tag}"

    def __len__(self) -> int:
        return len(self._frames)

    def __getitem__(self, idx: int) -> FrameCollection:
        return (self._frames[idx],)
